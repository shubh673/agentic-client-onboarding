"""Stage 3 — KYC agent (DUMMY).

This agent is a stub: it calls `run_kyc_check` (which currently returns a
hardcoded "approved" response) and emits the same log trail a real KYC
provider integration would. The shape — async `run`, structured result
dataclass, log callback — matches the reference LangGraph project so you
can swap the body of `app.agents.tools.kyc_tools.run_kyc_check` for a real
provider call later without touching the orchestrator.

To integrate a real provider:
    1. Replace the body of `run_kyc_check` with the provider SDK / HTTP call.
    2. Keep the return shape (`status`, `sanctions`, `pep`, `adverse_media`,
       `reference_id`) — or extend it; this agent only reads `status` and
       `reference_id`.
    3. Nothing in `stage_runner.py` needs to change.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Awaitable, Callable

from app.agents.tools.kyc_tools import run_kyc_check

logger = logging.getLogger(__name__)

EmitLog = Callable[[int, str, str], Awaitable[None]]


@dataclass
class KYCResult:
    approved: bool = False
    reference_id: str = ""
    details: dict[str, Any] = field(default_factory=dict)


class KYCAgent:
    """Dummy Stage 3 agent — emits the canonical sanctions/PEP/adverse-media
    log trail and returns the result from `run_kyc_check`.

    The small `asyncio.sleep` calls in between log lines preserve the
    "agent is doing work" pacing the UI was built around. Drop them when
    `run_kyc_check` becomes a real (and therefore slow) network call.
    """

    STAGE = 3

    # Per-substep pacing — kept tiny so the user sees each line land.
    SANCTIONS_DELAY_S = 0.5
    PEP_DELAY_S = 0.5
    ADVERSE_MEDIA_DELAY_S = 0.5

    async def run(
        self,
        *,
        full_name: str,
        pan_number: str,
        aadhaar_number: str,
        emit_log: EmitLog,
    ) -> KYCResult:
        await emit_log(self.STAGE, "info", "KYC agent invoked")

        # Call the (currently dummy) provider tool. Wrapped in to_thread in
        # case the real integration is a blocking SDK call later.
        try:
            response = await asyncio.to_thread(
                run_kyc_check, full_name, pan_number, aadhaar_number
            )
        except Exception as exc:  # noqa: BLE001
            logger.exception("KYC provider call failed")
            await emit_log(self.STAGE, "error", f"KYC provider call failed: {exc}")
            return KYCResult(approved=False, reference_id="", details={"error": str(exc)})

        # Replay the canonical log trail. With a real provider these
        # status values come from `response`; for the dummy they are fixed.
        await emit_log(self.STAGE, "info", "Sanctions list screening (OFAC, UN, EU)")
        await asyncio.sleep(self.SANCTIONS_DELAY_S)
        await emit_log(
            self.STAGE,
            "success" if response.get("sanctions") == "clear" else "error",
            f"Sanctions screening: {response.get('sanctions', 'unknown')}",
        )

        await emit_log(self.STAGE, "info", "PEP (politically exposed persons) screening")
        await asyncio.sleep(self.PEP_DELAY_S)
        await emit_log(
            self.STAGE,
            "success" if response.get("pep") == "clear" else "error",
            f"PEP screening: {response.get('pep', 'unknown')}",
        )

        await emit_log(self.STAGE, "info", "Adverse media scan")
        await asyncio.sleep(self.ADVERSE_MEDIA_DELAY_S)
        await emit_log(
            self.STAGE,
            "success" if response.get("adverse_media") == "no_hits" else "error",
            f"Adverse media: {response.get('adverse_media', 'unknown')}",
        )

        approved = response.get("status") == "approved"
        reference_id = response.get("reference_id", "")

        if approved:
            await emit_log(
                self.STAGE,
                "success",
                f"KYC approved (reference {reference_id})",
            )
            await emit_log(
                self.STAGE,
                "success",
                "Stage 3 complete — handing off to Eligibility agent",
            )
        else:
            await emit_log(
                self.STAGE,
                "error",
                f"KYC not approved (reference {reference_id})",
            )

        return KYCResult(approved=approved, reference_id=reference_id, details=response)
