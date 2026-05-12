"""Stage 2 — Document Verification agent.

Mirrors the LangGraph `doc_verification` node in the reference project, but
runs as plain Python: the agent calls its tools in a fixed order and returns
a structured result. No LLM is involved — the work is fully deterministic.

Public surface:
    DocumentVerificationAgent.run(...) -> DocVerificationResult

Callers pass an async `emit_log(stage, level, message)` callback so live
progress lines reach the WebSocket subscribers without coupling this agent
to the persistence layer.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Awaitable, Callable

from app.agents.tools.document_tools import (
    textract_ocr,
    verify_aadhaar_match,
    verify_pan_match,
)

logger = logging.getLogger(__name__)

EmitLog = Callable[[int, str, str], Awaitable[None]]


def _mask_pan(pan: str) -> str:
    if len(pan) != 10:
        return pan
    return f"{pan[:3]}XX{pan[5:9]}X"


def _mask_aadhaar(aadhaar: str) -> str:
    if len(aadhaar) != 12:
        return aadhaar
    return f"XXXX XXXX {aadhaar[-4:]}"


@dataclass
class DocVerificationResult:
    """Structured outcome of a Stage 2 run, returned to the orchestrator.

    `passed` is True iff both PAN and Aadhaar matched. `reason` is populated
    on failure (joined human-readable string) and used as the application's
    `verification_reason` so the UI can surface it on the re-upload screen.
    """

    pan_matched: bool = False
    aadhaar_matched: bool = False
    pan_ocr_text: str = ""
    aadhaar_ocr_text: str = ""
    failures: list[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return self.pan_matched and self.aadhaar_matched and not self.failures

    @property
    def reason(self) -> str | None:
        return "; ".join(self.failures) if self.failures else None


class DocumentVerificationAgent:
    """Deterministic Stage 2 agent — Textract OCR + regex match.

    Usage:
        agent = DocumentVerificationAgent()
        result = await agent.run(
            pan_number=app.pan_number,
            aadhaar_number=app.aadhaar_number,
            pan_s3_key=docs["pan"].s3_key,
            aadhaar_s3_key=docs["aadhaar"].s3_key,
            emit_log=emitter,
        )
        if result.passed: ...
    """

    STAGE = 2

    async def run(
        self,
        *,
        pan_number: str,
        aadhaar_number: str,
        pan_s3_key: str,
        aadhaar_s3_key: str,
        emit_log: EmitLog,
    ) -> DocVerificationResult:
        result = DocVerificationResult()

        await emit_log(self.STAGE, "info", "Document Verification agent invoked")

        # --- PAN ---
        await emit_log(self.STAGE, "info", "Running Textract OCR on PAN card")
        try:
            result.pan_ocr_text = await asyncio.to_thread(textract_ocr, pan_s3_key)
        except Exception as exc:  # noqa: BLE001 — surfaced into the result
            logger.exception("Textract failed on PAN (%s)", pan_s3_key)
            msg = f"OCR failed on PAN card: {exc}"
            result.failures.append(msg)
            await emit_log(self.STAGE, "error", msg)
        else:
            result.pan_matched = verify_pan_match(result.pan_ocr_text, pan_number)
            if result.pan_matched:
                await emit_log(
                    self.STAGE,
                    "success",
                    f"PAN number matched on uploaded PAN card ({_mask_pan(pan_number)})",
                )
            else:
                msg = f"PAN number {_mask_pan(pan_number)} not found on uploaded PAN card"
                result.failures.append(msg)
                await emit_log(self.STAGE, "error", msg)

        # --- Aadhaar ---
        await emit_log(self.STAGE, "info", "Running Textract OCR on Aadhaar card")
        try:
            result.aadhaar_ocr_text = await asyncio.to_thread(textract_ocr, aadhaar_s3_key)
        except Exception as exc:  # noqa: BLE001
            logger.exception("Textract failed on Aadhaar (%s)", aadhaar_s3_key)
            msg = f"OCR failed on Aadhaar card: {exc}"
            result.failures.append(msg)
            await emit_log(self.STAGE, "error", msg)
        else:
            result.aadhaar_matched = verify_aadhaar_match(
                result.aadhaar_ocr_text, aadhaar_number
            )
            if result.aadhaar_matched:
                await emit_log(
                    self.STAGE,
                    "success",
                    f"Aadhaar number matched on uploaded Aadhaar card "
                    f"({_mask_aadhaar(aadhaar_number)})",
                )
            else:
                msg = (
                    f"Aadhaar number {_mask_aadhaar(aadhaar_number)} not found "
                    "on uploaded Aadhaar card"
                )
                result.failures.append(msg)
                await emit_log(self.STAGE, "error", msg)

        if result.passed:
            await emit_log(self.STAGE, "success", "Stage 2 complete — handing off to KYC agent")
        else:
            await emit_log(self.STAGE, "error", "Stage 2 failed — re-upload required")

        return result
