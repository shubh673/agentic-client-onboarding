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
import json
import logging
import tempfile
import uuid
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ValidationError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.onboarding_chat import (
    ALLOWED_EXTS,
    MAX_BYTES,
    pending_expect,
    resume_session,
    session_values,
    start_session,
    stream_turn,
)
from app.agents.tools.document_tools import OcrError, ocr_file_bytes
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


async def _resolve_upload_input(thread_id: str, file: UploadFile) -> str:
    """Validate an uploaded file and return the value to resume the graph with.

    At a file step (PAN / Aadhaar) the upload is stored locally and its path is
    returned. At a text step (details / confirm) the file is OCR'd via Textract
    and the extracted text is returned so `extract` can pull out the KYC fields.

    Raises HTTPException on a bad/oversize file, OCR failure, or empty OCR text.
    """
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

    if pending_expect(thread_id) == "file":
        stored = UPLOAD_DIR / f"{thread_id}-{uuid.uuid4().hex}{suffix}"
        stored.write_bytes(contents)
        return str(stored)

    try:
        text = await asyncio.to_thread(ocr_file_bytes, contents, suffix, thread_id)
    except OcrError as e:
        logger.warning("chatbot OCR failed: %s", e)
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            "Couldn't process the file. Please type your details or try another file.",
        ) from e
    if not text.strip():
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Couldn't read any text from that file. Please type your details or try another file.",
        )
    return f"[Details extracted from uploaded document]\n{text}"


@router.post("/upload", response_model=ChatbotResponse)
async def upload(
    thread_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> dict:
    user_input = await _resolve_upload_input(thread_id, file)
    try:
        snapshot = await asyncio.to_thread(resume_session, thread_id, user_input)
    except Exception as e:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, str(e)) from e

    return await _maybe_submit(snapshot, thread_id, db, customer)


# ---------------------------------------------------------------------------
# Streaming (SSE) variants — stream Groq tokens as the LLM generates them.
# Events: `delta` ({"text": ...}) for each chunk, then a final `snapshot`
# (full ChatbotResponse payload), or `error` ({"detail": ...}) on failure.
# ---------------------------------------------------------------------------

_SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}


def _sse(event: str, data: dict) -> str:
    return f"event: {event}\ndata: {json.dumps(data)}\n\n"


def _turn_response(
    thread_id: str,
    user_input: str | None,
    db: AsyncSession,
    customer: Customer,
) -> StreamingResponse:
    """Stream one conversation turn as SSE, submitting the application if complete."""

    async def gen():
        snapshot: dict | None = None
        try:
            async for kind, payload in stream_turn(thread_id, user_input):
                if kind == "delta":
                    yield _sse("delta", {"text": payload})
                else:
                    snapshot = payload
            if snapshot is not None:
                snapshot = await _maybe_submit(snapshot, thread_id, db, customer)
                yield _sse("snapshot", snapshot)
        except Exception as e:  # noqa: BLE001
            logger.exception("chatbot stream failed")
            yield _sse("error", {"detail": str(e)})

    return StreamingResponse(
        gen(), media_type="text/event-stream", headers=_SSE_HEADERS
    )


@router.post("/start/stream")
async def start_stream(
    customer: Customer = Depends(current_customer),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    thread_id = str(uuid.uuid4())
    return _turn_response(thread_id, None, db, customer)


@router.post("/message/stream")
async def message_stream(
    payload: MessageRequest,
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> StreamingResponse:
    if not payload.text.strip():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "text is required")
    return _turn_response(payload.thread_id, payload.text, db, customer)


@router.post("/upload/stream")
async def upload_stream(
    thread_id: str = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> StreamingResponse:
    # Validate + OCR up front so a bad file fails with a normal HTTP error before
    # the SSE stream opens; only the graph turn itself is streamed.
    user_input = await _resolve_upload_input(thread_id, file)
    return _turn_response(thread_id, user_input, db, customer)
