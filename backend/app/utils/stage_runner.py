import asyncio
import logging
import re
import uuid

from sqlalchemy import select

from app.database import SessionLocal
from app.models import Application, ApplicationDocument, ApplicationLog
from app.schemas import ApplicationResponse, LogEntryResponse
from app.utils.aws import detect_text
from app.utils.ws_manager import manager

logger = logging.getLogger(__name__)

INITIAL_DELAY_S = 1.0

_BG_TASKS: set[asyncio.Task] = set()


def schedule(coro) -> asyncio.Task:
    task = asyncio.create_task(coro)
    _BG_TASKS.add(task)
    task.add_done_callback(_BG_TASKS.discard)
    return task


# (delay_before_seconds, level, message_template)
# The sum of delays inside a stage drives how long that stage spends in "running".
# Templates may reference {full_name}, {email}, {pan_masked}, {aadhaar_masked}.
StageScript = list[tuple[float, str, str]]

STAGE_SCRIPTS: dict[int, StageScript] = {
    1: [
        (0.0, "info", "Customer application received"),
        (0.3, "success", "Captured personal details: {full_name}"),
        (0.4, "info", "Validating field formats (email, mobile, PAN, Aadhaar)"),
        (0.4, "success", "Identity documents uploaded: PAN ({pan_masked}), Aadhaar ({aadhaar_masked})"),
        (0.4, "success", "Stage 1 complete — handing off to Document Verification agent"),
    ],
    # Stage 2 is implemented programmatically in _play_stage_2 — it runs real
    # Textract OCR and compares against the user-entered numbers.
    3: [
        (0.4, "info", "KYC agent invoked"),
        (0.7, "info", "Sanctions list screening (OFAC, UN, EU)"),
        (0.6, "success", "Sanctions screening: clear"),
        (0.7, "info", "PEP (politically exposed persons) screening"),
        (0.5, "success", "PEP screening: clear"),
        (0.6, "info", "Adverse media scan"),
        (0.7, "success", "Adverse media: no hits"),
        (0.4, "success", "Stage 3 complete — handing off to Eligibility agent"),
    ],
    4: [
        (0.4, "info", "Eligibility agent invoked"),
        (0.6, "info", "Applying product rules"),
        (0.6, "info", "Querying credit bureau"),
        (0.8, "success", "Credit bureau score: 745"),
        (0.5, "success", "Eligible for selected product"),
        (0.4, "success", "Stage 4 complete — handing off to Pricing agent"),
    ],
    5: [
        (0.4, "info", "Pricing agent invoked"),
        (0.6, "info", "Applying rate card and risk-based adjustments"),
        (0.7, "success", "Computed offer: APR 11.5%, processing fee ₹499"),
        (0.5, "info", "Generating offer letter"),
        (0.5, "success", "Offer letter generated"),
        (0.4, "success", "Stage 5 complete — handing off to Disclosure agent"),
    ],
    6: [
        (0.4, "info", "Regulatory Disclosure agent invoked"),
        (0.5, "info", "Generating regulatory disclosures"),
        (0.5, "info", "Awaiting customer acknowledgement"),
        (0.6, "success", "Acknowledgement captured"),
        (0.4, "success", "Stage 6 complete — handing off to Account Creation agent"),
    ],
    7: [
        (0.4, "info", "Account Creation agent invoked"),
        (0.6, "info", "Calling core banking API"),
        (0.7, "success", "Ledger account provisioned: AC{account_suffix}"),
        (0.5, "info", "Linking downstream systems (cards, statements)"),
        (0.5, "success", "Downstream provisioning complete"),
        (0.4, "success", "Stage 7 complete — handing off to Welcome agent"),
    ],
    8: [
        (0.4, "info", "Welcome agent invoked"),
        (0.4, "success", "Card dispatch triggered"),
        (0.4, "success", "Welcome email sent to {email}"),
        (0.4, "success", "Onboarding complete"),
    ],
}


def _mask_pan(pan: str) -> str:
    if len(pan) != 10:
        return pan
    return f"{pan[:3]}XX{pan[5:9]}X"


def _mask_aadhaar(aadhaar: str) -> str:
    if len(aadhaar) != 12:
        return aadhaar
    return f"XXXX XXXX {aadhaar[-4:]}"


def _format_message(template: str, app: Application) -> str:
    return template.format(
        full_name=app.full_name,
        email=app.email,
        mobile=app.mobile,
        pan_masked=_mask_pan(app.pan_number),
        aadhaar_masked=_mask_aadhaar(app.aadhaar_number),
        account_suffix=str(app.id)[-6:].upper(),
    )


async def _broadcast_application(app_id: uuid.UUID) -> None:
    async with SessionLocal() as db:
        result = await db.execute(select(Application).where(Application.id == app_id))
        app = result.scalar_one_or_none()
        if app is None:
            return
        await db.refresh(app, ["documents"])
        payload = ApplicationResponse.model_validate(app).model_dump(mode="json")
    await manager.broadcast(str(app_id), {"type": "application_update", "application": payload})


async def _emit_log(app_id: uuid.UUID, stage: int, level: str, template: str) -> None:
    async with SessionLocal() as db:
        result = await db.execute(select(Application).where(Application.id == app_id))
        app = result.scalar_one_or_none()
        if app is None:
            return
        message = _format_message(template, app)
        entry = ApplicationLog(application_id=app_id, stage=stage, level=level, message=message)
        db.add(entry)
        await db.commit()
        await db.refresh(entry)
        payload = LogEntryResponse.model_validate(entry).model_dump(mode="json")
    await manager.broadcast(str(app_id), {"type": "log_appended", "log": payload})


async def _set_status(
    app_id: uuid.UUID,
    *,
    current_stage: int,
    status: str,
    verification_reason: str | None = None,
    clear_verification_reason: bool = False,
) -> None:
    async with SessionLocal() as db:
        result = await db.execute(select(Application).where(Application.id == app_id))
        app = result.scalar_one_or_none()
        if app is None:
            return
        app.current_stage = current_stage
        app.status = status
        if clear_verification_reason:
            app.verification_reason = None
        elif verification_reason is not None:
            app.verification_reason = verification_reason
        await db.commit()


async def _play_stage(app_id: uuid.UUID, stage: int) -> None:
    for delay, level, template in STAGE_SCRIPTS.get(stage, []):
        if delay:
            await asyncio.sleep(delay)
        await _emit_log(app_id, stage, level, template)


async def emit_initial_logs(app_id: uuid.UUID) -> None:
    """Emit Stage 1 logs synchronously (no inter-line delays).

    Called from the POST handler so the customer-facing logs are already
    persisted before the response returns. The detail page lands on a
    populated log list instead of "waiting for the agent…".
    """
    for _delay, level, template in STAGE_SCRIPTS.get(1, []):
        await _emit_log(app_id, 1, level, template)


async def _load_app_with_docs(app_id: uuid.UUID) -> Application | None:
    async with SessionLocal() as db:
        result = await db.execute(select(Application).where(Application.id == app_id))
        app = result.scalar_one_or_none()
        if app is None:
            return None
        await db.refresh(app, ["documents"])
        return app


def _verify_pan(text: str, expected_pan: str) -> bool:
    """Expected PAN (10 chars, A-Z & 0-9) must appear as a substring of the OCR text after upper+strip-non-alnum."""
    cleaned = re.sub(r"[^A-Z0-9]", "", text.upper())
    return expected_pan.upper() in cleaned


def _verify_aadhaar(text: str, expected_aadhaar: str) -> bool:
    """Aadhaar OCR is often spaced as '1234 5678 9012'; full match preferred, last-4 fallback."""
    digits = re.sub(r"\D", "", text)
    return expected_aadhaar in digits or expected_aadhaar[-4:] in digits


async def _play_stage_2(app_id: uuid.UUID) -> bool:
    """Run Textract OCR on the PAN and Aadhaar S3 objects and compare against the
    user-entered numbers. Emits live logs as it goes. Returns True on pass."""
    await _emit_log(app_id, 2, "info", "Document Verification agent invoked")

    app = await _load_app_with_docs(app_id)
    if app is None:
        return False

    docs: dict[str, ApplicationDocument] = {d.doc_type: d for d in app.documents}
    if "pan" not in docs or "aadhaar" not in docs:
        reason = "Missing PAN or Aadhaar document"
        await _emit_log(app_id, 2, "error", reason)
        await _set_status(
            app_id,
            current_stage=2,
            status="stage_2_failed",
            verification_reason=reason,
        )
        return False

    failures: list[str] = []

    await _emit_log(app_id, 2, "info", "Running Textract OCR on PAN card")
    try:
        pan_text = await asyncio.to_thread(detect_text, docs["pan"].s3_key)
    except Exception as e:
        logger.exception("Textract failed on PAN for %s", app_id)
        reason = f"OCR failed on PAN card: {e}"
        await _emit_log(app_id, 2, "error", reason)
        failures.append(reason)
    else:
        if _verify_pan(pan_text, app.pan_number):
            await _emit_log(
                app_id, 2, "success", f"PAN number matched on uploaded PAN card ({_mask_pan(app.pan_number)})"
            )
        else:
            reason = f"PAN number {_mask_pan(app.pan_number)} not found on uploaded PAN card"
            await _emit_log(app_id, 2, "error", reason)
            failures.append(reason)

    await _emit_log(app_id, 2, "info", "Running Textract OCR on Aadhaar card")
    try:
        aadhaar_text = await asyncio.to_thread(detect_text, docs["aadhaar"].s3_key)
    except Exception as e:
        logger.exception("Textract failed on Aadhaar for %s", app_id)
        reason = f"OCR failed on Aadhaar card: {e}"
        await _emit_log(app_id, 2, "error", reason)
        failures.append(reason)
    else:
        if _verify_aadhaar(aadhaar_text, app.aadhaar_number):
            await _emit_log(
                app_id,
                2,
                "success",
                f"Aadhaar number matched on uploaded Aadhaar card ({_mask_aadhaar(app.aadhaar_number)})",
            )
        else:
            reason = f"Aadhaar number {_mask_aadhaar(app.aadhaar_number)} not found on uploaded Aadhaar card"
            await _emit_log(app_id, 2, "error", reason)
            failures.append(reason)

    if failures:
        combined = "; ".join(failures)
        await _emit_log(app_id, 2, "error", "Stage 2 failed — re-upload required")
        await _set_status(
            app_id,
            current_stage=2,
            status="stage_2_failed",
            verification_reason=combined,
        )
        return False

    await _emit_log(app_id, 2, "success", "Stage 2 complete — handing off to KYC agent")
    return True


async def _run_stage_2_and_after(app_id: uuid.UUID) -> None:
    """Stage 2 (real OCR) followed by stages 3..8. Used by both the fresh-application
    path and the re-upload path. Halts at stage_2_failed; does not retry."""
    await _set_status(app_id, current_stage=2, status="stage_2_running", clear_verification_reason=True)
    await _broadcast_application(app_id)

    passed = await _play_stage_2(app_id)
    if not passed:
        # _play_stage_2 already wrote stage_2_failed + verification_reason.
        await _broadcast_application(app_id)
        return

    await _set_status(app_id, current_stage=3, status="stage_2_complete")
    await _broadcast_application(app_id)
    await asyncio.sleep(0.4)

    for stage in (3, 4, 5, 6, 7, 8):
        await _set_status(app_id, current_stage=stage, status=f"stage_{stage}_running")
        await _broadcast_application(app_id)
        await _play_stage(app_id, stage)
        await _set_status(
            app_id, current_stage=stage + 1, status=f"stage_{stage}_complete"
        )
        await _broadcast_application(app_id)
        await asyncio.sleep(0.4)

    await _set_status(app_id, current_stage=9, status="completed")
    await _broadcast_application(app_id)


async def run_stages(app_id: uuid.UUID) -> None:
    """Drive an application through stages 2..8 with live logs + state broadcasts.

    Stage 1 logs are emitted synchronously by the POST handler before this
    runner is scheduled. Stage 2 runs real Textract OCR; on mismatch the runner
    halts at stage_2_failed and the UI invites the user to re-upload.
    """
    try:
        await asyncio.sleep(INITIAL_DELAY_S)
        await _run_stage_2_and_after(app_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("stage runner failed for application %s", app_id)


async def rerun_from_stage_2(app_id: uuid.UUID) -> None:
    """Re-run Stage 2 (and continuation) after the customer re-uploads."""
    try:
        await _run_stage_2_and_after(app_id)
    except asyncio.CancelledError:
        raise
    except Exception:
        logger.exception("stage 2 rerun failed for application %s", app_id)
