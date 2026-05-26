"""Stage-1 intake helper, reused by both the form endpoint and the chatbot.

Persists an Application + its two documents (PAN, Aadhaar), emits the initial
log entries, and kicks off Stages 2–8 in the background. Mirrors what the
existing form-based `POST /applications` does — exposed here so the chatbot can
reuse it once the conversation has captured everything.
"""

from __future__ import annotations

import asyncio
import uuid

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Application, ApplicationDocument, Customer
from app.schemas import ApplicationCreate
from app.utils.aws import s3_key_for, upload_bytes
from app.utils.files import ALLOWED_MIME, EXT_BY_MIME, sniff_mime
from app.utils.stage_runner import emit_initial_logs, run_stages, schedule


async def _put_doc(
    application_id: uuid.UUID,
    doc_type: str,
    data: bytes,
    max_bytes: int,
) -> tuple[str, str, int]:
    if not data:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{doc_type}_file is empty",
        )
    if len(data) > max_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            f"{doc_type}_file exceeds {max_bytes} bytes",
        )
    sniffed = sniff_mime(data[:16])
    if sniffed is None or sniffed not in ALLOWED_MIME:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{doc_type}_file must be JPEG, PNG, or PDF",
        )
    key = s3_key_for(application_id, doc_type, EXT_BY_MIME[sniffed])
    await asyncio.to_thread(upload_bytes, key, data, sniffed)
    return key, sniffed, len(data)


async def submit_application(
    db: AsyncSession,
    customer: Customer,
    payload: ApplicationCreate,
    pan_data: bytes,
    pan_filename: str,
    aadhaar_data: bytes,
    aadhaar_filename: str,
    max_upload_bytes: int,
) -> Application:
    """Persist the application + documents, emit Stage-1 logs, schedule Stages 2-8."""
    application = Application(
        full_name=payload.full_name,
        dob=payload.dob,
        mobile=payload.mobile,
        email=payload.email,
        address=payload.address,
        pan_number=payload.pan_number,
        aadhaar_number=payload.aadhaar_number,
        customer_id=customer.id,
        current_stage=2,
        status="stage_1_complete",
    )
    db.add(application)
    await db.flush()

    try:
        for doc_type, data, original in (
            ("pan", pan_data, pan_filename),
            ("aadhaar", aadhaar_data, aadhaar_filename),
        ):
            s3_key, mime, size = await _put_doc(
                application.id, doc_type, data, max_upload_bytes
            )
            db.add(
                ApplicationDocument(
                    application_id=application.id,
                    doc_type=doc_type,
                    original_filename=original or doc_type,
                    s3_key=s3_key,
                    mime_type=mime,
                    size_bytes=size,
                )
            )
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR,
            f"Failed to save uploads: {e}",
        ) from e

    await db.commit()
    await db.refresh(application, ["documents"])

    await emit_initial_logs(application.id)
    schedule(run_stages(application.id))

    return application
