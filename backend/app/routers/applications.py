import asyncio
import uuid
from datetime import date, datetime, timezone

from fastapi import (
    APIRouter,
    Depends,
    File,
    Form,
    HTTPException,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
    status,
)
from fastapi.responses import RedirectResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import SessionLocal, get_db
from app.models import Application, ApplicationDocument, ApplicationLog, Customer
from app.schemas import ApplicationCreate, ApplicationResponse, LogEntryResponse
from app.utils.aws import presigned_get
from app.utils.files import upload_to_s3
from app.utils.intake import submit_application
from app.utils.jwt_auth import current_customer, verify_token
from app.utils.stage_runner import (
    rerun_from_stage_2,
    schedule,
)
from app.utils.ws_manager import manager as ws_manager

router = APIRouter(prefix="/applications", tags=["applications"])
settings = get_settings()


@router.post("", response_model=ApplicationResponse, status_code=status.HTTP_201_CREATED)
async def create_application(
    full_name: str = Form(...),
    dob: date = Form(...),
    mobile: str = Form(...),
    email: str = Form(...),
    address: str = Form(...),
    pan_number: str = Form(...),
    aadhaar_number: str = Form(...),
    pan_file: UploadFile = File(...),
    aadhaar_file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> ApplicationResponse:
    try:
        payload = ApplicationCreate(
            full_name=full_name,
            dob=dob,
            mobile=mobile,
            email=email,
            address=address,
            pan_number=pan_number,
            aadhaar_number=aadhaar_number,
        )
    except ValidationError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, e.errors()) from e

    pan_data = await pan_file.read()
    aadhaar_data = await aadhaar_file.read()

    application = await submit_application(
        db,
        customer,
        payload,
        pan_data,
        pan_file.filename or "pan",
        aadhaar_data,
        aadhaar_file.filename or "aadhaar",
        settings.MAX_UPLOAD_BYTES,
    )
    return ApplicationResponse.model_validate(application)


@router.patch("/{application_id}/documents", response_model=ApplicationResponse)
async def reupload_documents(
    application_id: uuid.UUID,
    pan_file: UploadFile | None = File(None),
    aadhaar_file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> ApplicationResponse:
    if pan_file is None and aadhaar_file is None:
        raise HTTPException(
            status.HTTP_400_BAD_REQUEST,
            "Provide at least one of pan_file or aadhaar_file",
        )

    result = await db.execute(select(Application).where(Application.id == application_id))
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    if application.customer_id != customer.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your application")
    if application.status != "stage_2_failed":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Re-upload only allowed when status is stage_2_failed",
        )

    docs_result = await db.execute(
        select(ApplicationDocument).where(ApplicationDocument.application_id == application_id)
    )
    docs_by_type: dict[str, ApplicationDocument] = {
        d.doc_type: d for d in docs_result.scalars().all()
    }

    replacements: list[tuple[str, UploadFile]] = []
    if pan_file is not None:
        replacements.append(("pan", pan_file))
    if aadhaar_file is not None:
        replacements.append(("aadhaar", aadhaar_file))

    try:
        for doc_type, upload in replacements:
            s3_key, mime, size = await upload_to_s3(
                upload, application_id, doc_type, settings.MAX_UPLOAD_BYTES
            )
            doc = docs_by_type.get(doc_type)
            if doc is None:
                raise HTTPException(
                    status.HTTP_409_CONFLICT,
                    f"No existing {doc_type} document to replace",
                )
            doc.s3_key = s3_key
            doc.mime_type = mime
            doc.size_bytes = size
            doc.original_filename = upload.filename or doc.original_filename
            doc.uploaded_at = datetime.now(timezone.utc)
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(
            status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to save uploads: {e}"
        ) from e

    application.status = "stage_2_running"
    application.current_stage = 2
    application.verification_reason = None
    await db.commit()
    # `updated_at` has onupdate=func.now() — Postgres recomputes it on UPDATE
    # and SQLAlchemy leaves it expired. Refresh it explicitly here so the
    # ApplicationResponse serialization doesn't trigger an async lazy load
    # inside Pydantic's sync model_validate (MissingGreenlet).
    await db.refresh(application, ["updated_at", "documents"])

    schedule(rerun_from_stage_2(application_id))

    return ApplicationResponse.model_validate(application)


@router.websocket("/{application_id}/events")
async def application_events(websocket: WebSocket, application_id: uuid.UUID) -> None:
    # Browsers can't set custom headers on `new WebSocket(...)`, so the access
    # token is passed as a query parameter. Validate before accepting.
    token = websocket.query_params.get("token")
    if not token:
        await websocket.close(code=4401)
        return
    try:
        claims = verify_token(token)
    except HTTPException:
        await websocket.close(code=4401)
        return
    sub = claims.get("sub")

    app_id = str(application_id)

    async with SessionLocal() as db:
        cust_result = await db.execute(select(Customer).where(Customer.cognito_sub == sub))
        customer = cust_result.scalar_one_or_none()
        if customer is None:
            await websocket.close(code=4401)
            return

        result = await db.execute(select(Application).where(Application.id == application_id))
        application = result.scalar_one_or_none()
        if application is None or application.customer_id != customer.id:
            await websocket.close(code=4403)
            return
        await db.refresh(application, ["documents"])
        snapshot = ApplicationResponse.model_validate(application).model_dump(mode="json")

    await ws_manager.connect(app_id, websocket)

    try:
        await websocket.send_json({"type": "application_update", "application": snapshot})
    except Exception:
        pass

    try:
        while True:
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(app_id, websocket)


@router.get("", response_model=list[ApplicationResponse])
async def list_applications(
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> list[ApplicationResponse]:
    result = await db.execute(
        select(Application)
        .where(Application.customer_id == customer.id)
        .order_by(Application.created_at.desc())
    )
    return [ApplicationResponse.model_validate(a) for a in result.scalars().all()]


@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> ApplicationResponse:
    result = await db.execute(select(Application).where(Application.id == application_id))
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    if application.customer_id != customer.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your application")
    return ApplicationResponse.model_validate(application)


@router.get("/{application_id}/logs", response_model=list[LogEntryResponse])
async def list_application_logs(
    application_id: uuid.UUID,
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> list[LogEntryResponse]:
    app_result = await db.execute(select(Application).where(Application.id == application_id))
    application = app_result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    if application.customer_id != customer.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your application")

    result = await db.execute(
        select(ApplicationLog)
        .where(ApplicationLog.application_id == application_id)
        .order_by(ApplicationLog.ts.asc())
    )
    return [LogEntryResponse.model_validate(row) for row in result.scalars().all()]


@router.get("/{application_id}/documents/{doc_type}")
async def get_document(
    application_id: uuid.UUID,
    doc_type: str,
    db: AsyncSession = Depends(get_db),
    customer: Customer = Depends(current_customer),
) -> RedirectResponse:
    if doc_type not in {"pan", "aadhaar"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "doc_type must be 'pan' or 'aadhaar'")

    app_result = await db.execute(select(Application).where(Application.id == application_id))
    application = app_result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    if application.customer_id != customer.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not your application")

    result = await db.execute(
        select(ApplicationDocument).where(
            ApplicationDocument.application_id == application_id,
            ApplicationDocument.doc_type == doc_type,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    url = await asyncio.to_thread(presigned_get, doc.s3_key, settings.PRESIGNED_URL_TTL_SECONDS)
    return RedirectResponse(url, status_code=307)
