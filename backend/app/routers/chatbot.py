"""HTTP endpoints for the LangGraph onboarding chatbot.

Endpoints (all under /api/chatbot, requires auth):
- POST /start            -> begin a session, return first agent message
- POST /message          -> send text reply, return next agent message
- POST /upload           -> send file reply, return next agent message

When the conversation completes (both PAN + Aadhaar uploaded), the captured
data is fed into `submit_application` — the same helper used by the form-based
intake — which creates the Application, persists the docs to S3, emits Stage-1
logs, and schedules Stages 2-8. The final response carries `application_id`
so the frontend can navigate to the detail page and watch live logs.
"""

from __future__ import annotations

import asyncio
import logging
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.onboarding_chat import (
    ALLOWED_EXTS,
    MAX_BYTES,
    resume_session,
    session_values,
    start_session,
)
from app.config import get_settings
from app.database import get_db
from app.models import Customer
from app.schemas import ApplicationCreate
from app.utils.intake import submit_application
from app.utils.jwt_auth import current_customer

router = APIRouter(prefix="/chatbot", tags=["chatbot"])
logger = logging.getLogger(__name__)
settings = get_settings()

UPLOAD_DIR = Path(tempfile.gettempdir()) / "onboarding_chatbot_uploads"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


class ChatbotResponse(BaseModel):
    thread_id: str
    message: str
    expect: str
    doc: str | None = None
    complete: bool
    data: dict
    uploads: dict
    application_id: str | None = None
    submission_error: str | None = None


class MessageRequest(BaseModel):
    thread_id: str
    text: str


def _parse_dob(raw: str | None):
    if not raw:
        return None
    for fmt in ("%d-%m-%Y", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


async def _maybe_submit(
    snapshot: dict,
    thread_id: str,
    db: AsyncSession,
    customer: Customer,
) -> dict:
    """If the conversation completed, persist the application via the shared
    intake helper and tack `application_id` onto the response."""
    if not snapshot.get("complete"):
        return snapshot
    if not snapshot["uploads"].get("pan_card") or not snapshot["uploads"].get(
        "aadhaar_card"
    ):
        return snapshot

    values = session_values(thread_id)
    pan_path = values.get("pan_card_path")
    aadhaar_path = values.get("aadhaar_card_path")
    if not pan_path or not aadhaar_path:
        return snapshot

    data = snapshot.get("data", {})
    dob = _parse_dob(data.get("dob"))
    if dob is None:
        snapshot["submission_error"] = (
            f"Could not parse date of birth: {data.get('dob')!r}"
        )
        return snapshot

    try:
        payload = ApplicationCreate(
            full_name=data["full_name"],
            dob=dob,
            mobile=data["mobile"],
            email=data["email"],
            address=data["address"],
            pan_number=data["pan"],
            aadhaar_number=data["aadhaar"],
        )
    except (KeyError, ValidationError) as e:
        snapshot["submission_error"] = f"Captured details failed validation: {e}"
        return snapshot

    try:
        pan_data = Path(pan_path).read_bytes()
        aadhaar_data = Path(aadhaar_path).read_bytes()
        application = await submit_application(
            db,
            customer,
            payload,
            pan_data,
            Path(pan_path).name,
            aadhaar_data,
            Path(aadhaar_path).name,
            settings.MAX_UPLOAD_BYTES,
        )
    except HTTPException as e:
        snapshot["submission_error"] = str(e.detail)
        return snapshot
    except Exception as e:
        logger.exception("chatbot intake submission failed")
        snapshot["submission_error"] = f"Failed to create application: {e}"
        return snapshot

    snapshot["application_id"] = str(application.id)

    # Cleanup local uploaded files now that they're safely in S3.
    for p in (pan_path, aadhaar_path):
        try:
            Path(p).unlink(missing_ok=True)
        except Exception:
            pass

    return snapshot


@router.post("/start", response_model=ChatbotResponse)
async def start(
    customer: Customer = Depends(current_customer),
) -> dict:
    thread_id = str(uuid.uuid4())
    return await asyncio.to_thread(start_session, thread_id)


@router.post("/message", response_model=ChatbotResponse)
async def message(
    payload: MessageRequest,
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> dict:
    if not payload.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "text is required")
    try:
        snapshot = await asyncio.to_thread(
            resume_session, payload.thread_id, payload.text
        )
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)) from e
    return await _maybe_submit(snapshot, payload.thread_id, db, customer)


@router.post("/upload", response_model=ChatbotResponse)
async def upload(
    thread_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> dict:
    suffix = Path(file.filename or "").suffix.lower()
    if suffix not in ALLOWED_EXTS:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Only JPG, PNG, or PDF files are accepted.",
        )

    contents = await file.read()
    if len(contents) > MAX_BYTES:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            f"File is over {MAX_BYTES // (1024 * 1024)} MB.",
        )

    stored = UPLOAD_DIR / f"{thread_id}-{uuid.uuid4().hex}{suffix}"
    stored.write_bytes(contents)

    try:
        snapshot = await asyncio.to_thread(resume_session, thread_id, str(stored))
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)) from e

    return await _maybe_submit(snapshot, thread_id, db, customer)
