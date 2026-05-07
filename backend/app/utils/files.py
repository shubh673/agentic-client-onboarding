import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status

ALLOWED_MIME = {"image/jpeg", "image/png", "application/pdf"}
EXT_BY_MIME = {"image/jpeg": ".jpg", "image/png": ".png", "application/pdf": ".pdf"}

# Magic-number signatures for the formats we accept. Avoids depending on libmagic
# (which needs a system DLL on Windows) for this small whitelist.
_SIGNATURES: list[tuple[bytes, str]] = [
    (b"\xff\xd8\xff", "image/jpeg"),
    (b"\x89PNG\r\n\x1a\n", "image/png"),
    (b"%PDF-", "application/pdf"),
]


def sniff_mime(head: bytes) -> str | None:
    for sig, mime in _SIGNATURES:
        if head.startswith(sig):
            return mime
    return None


async def save_upload(
    upload: UploadFile,
    application_id: uuid.UUID,
    doc_type: str,
    upload_root: Path,
    max_bytes: int,
) -> tuple[Path, str, int]:
    """Read, validate, and write an upload to disk.

    Returns (stored_path, sniffed_mime, size_bytes). Raises HTTPException on
    oversize or disallowed file types.
    """
    data = await upload.read()
    size = len(data)

    if size == 0:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, f"{doc_type}_file is empty")
    if size > max_bytes:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{doc_type}_file exceeds {max_bytes} bytes")

    sniffed = sniff_mime(data[:16])
    if sniffed is None or sniffed not in ALLOWED_MIME:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            f"{doc_type}_file must be JPEG, PNG, or PDF",
        )

    target_dir = upload_root / str(application_id)
    target_dir.mkdir(parents=True, exist_ok=True)
    target_path = target_dir / f"{doc_type}{EXT_BY_MIME[sniffed]}"
    target_path.write_bytes(data)

    return target_path, sniffed, size
