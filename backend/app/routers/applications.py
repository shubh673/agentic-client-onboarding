import uuid
from datetime import date

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
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import SessionLocal, get_db
from app.models import Application, ApplicationDocument, ApplicationLog
from app.schemas import ApplicationCreate, ApplicationResponse, LogEntryResponse
from app.utils.files import save_upload
from app.utils.stage_runner import run_stages, schedule
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

    application = Application(
        full_name=payload.full_name,
        dob=payload.dob,
        mobile=payload.mobile,
        email=payload.email,
        address=payload.address,
        pan_number=payload.pan_number,
        aadhaar_number=payload.aadhaar_number,
        current_stage=2,  # advance — Step 1 complete
        status="stage_1_complete",
    )
    db.add(application)
    await db.flush()  # populate application.id without committing

    upload_root = settings.upload_path
    try:
        for doc_type, upload in (("pan", pan_file), ("aadhaar", aadhaar_file)):
            stored_path, mime, size = await save_upload(
                upload, application.id, doc_type, upload_root, settings.MAX_UPLOAD_BYTES
            )
            db.add(
                ApplicationDocument(
                    application_id=application.id,
                    doc_type=doc_type,
                    original_filename=upload.filename or f"{doc_type}",
                    stored_path=str(stored_path.relative_to(upload_root.parent)),
                    mime_type=mime,
                    size_bytes=size,
                )
            )
    except HTTPException:
        await db.rollback()
        raise
    except Exception as e:
        await db.rollback()
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, f"Failed to save uploads: {e}") from e

    await db.commit()
    await db.refresh(application, ["documents"])

    # Kick off the agent simulation in the background. Each stage transition is
    # persisted and broadcast over WebSocket to anyone watching this application.
    schedule(run_stages(application.id))

    return ApplicationResponse.model_validate(application)


@router.websocket("/{application_id}/events")
async def application_events(websocket: WebSocket, application_id: uuid.UUID) -> None:
    app_id = str(application_id)
    await ws_manager.connect(app_id, websocket)

    # Send an initial snapshot so a freshly connected client doesn't have to wait
    # for the next state change to render.
    async with SessionLocal() as db:
        result = await db.execute(select(Application).where(Application.id == application_id))
        application = result.scalar_one_or_none()
        if application is not None:
            await db.refresh(application, ["documents"])
            payload = ApplicationResponse.model_validate(application).model_dump(mode="json")
            try:
                await websocket.send_json({"type": "application_update", "application": payload})
            except Exception:
                pass

    try:
        while True:
            # We don't expect inbound traffic from the client; just keep the
            # connection open and discard anything received.
            await websocket.receive_text()
    except WebSocketDisconnect:
        pass
    finally:
        await ws_manager.disconnect(app_id, websocket)


@router.get("", response_model=list[ApplicationResponse])
async def list_applications(db: AsyncSession = Depends(get_db)) -> list[ApplicationResponse]:
    result = await db.execute(select(Application).order_by(Application.created_at.desc()))
    return [ApplicationResponse.model_validate(a) for a in result.scalars().all()]


@router.get("/{application_id}", response_model=ApplicationResponse)
async def get_application(application_id: uuid.UUID, db: AsyncSession = Depends(get_db)) -> ApplicationResponse:
    result = await db.execute(select(Application).where(Application.id == application_id))
    application = result.scalar_one_or_none()
    if application is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Application not found")
    return ApplicationResponse.model_validate(application)


@router.get("/{application_id}/logs", response_model=list[LogEntryResponse])
async def list_application_logs(
    application_id: uuid.UUID, db: AsyncSession = Depends(get_db)
) -> list[LogEntryResponse]:
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
) -> FileResponse:
    if doc_type not in {"pan", "aadhaar"}:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "doc_type must be 'pan' or 'aadhaar'")

    result = await db.execute(
        select(ApplicationDocument).where(
            ApplicationDocument.application_id == application_id,
            ApplicationDocument.doc_type == doc_type,
        )
    )
    doc = result.scalar_one_or_none()
    if doc is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Document not found")

    abs_path = settings.upload_path.parent / doc.stored_path
    if not abs_path.exists():
        raise HTTPException(status.HTTP_404_NOT_FOUND, "File missing on disk")
    return FileResponse(path=abs_path, media_type=doc.mime_type, filename=doc.original_filename)
