"""Document Verification tools.

Self-contained: owns its boto3 Textract client + the OCR call, plus the
regex matchers used by DocumentVerificationAgent. No LangChain decorators —
the agent calls these functions directly.

Boto3 is blocking; call `textract_ocr` from async code via
`asyncio.to_thread` so the event loop stays responsive.
"""
from __future__ import annotations

import re
import time
import uuid
from functools import lru_cache

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings
from app.utils.aws import delete_s3_object, upload_bytes

# Suffix -> MIME for the temp S3 upload used by `ocr_file_bytes`.
_MIME_BY_SUFFIX = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".pdf": "application/pdf",
}


class OcrError(RuntimeError):
    """Raised when AWS Textract fails on an uploaded document.

    Wraps the underlying boto3 / Textract error so callers can show a
    customer-facing reason ("OCR failed on PAN card: …") without leaking
    boto3 internals. The original exception is preserved as `__cause__`.
    """


@lru_cache
def _textract_client() -> BaseClient:
    s = get_settings()
    return boto3.client(
        "textract",
        region_name=s.AWS_REGION,
        aws_access_key_id=s.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=s.AWS_SECRET_ACCESS_KEY,
    )


def textract_ocr(s3_key: str) -> str:
    """Run AWS Textract DetectDocumentText on the given S3 object and
    return all detected LINE blocks joined by newlines.

    Raises:
        OcrError: any boto3/Textract failure (network, throttling,
            UnsupportedDocumentException, AccessDenied, etc.). The original
            exception is attached via `raise ... from`.
    """
    bucket = get_settings().AWS_S3_BUCKET
    try:
        resp = _textract_client().detect_document_text(
            Document={"S3Object": {"Bucket": bucket, "Name": s3_key}}
        )
    except (BotoCoreError, ClientError) as exc:
        raise OcrError(f"Textract failed for s3://{bucket}/{s3_key}: {exc}") from exc

    lines = [b["Text"] for b in resp.get("Blocks", []) if b.get("BlockType") == "LINE"]
    return "\n".join(lines)


def textract_pdf_text(
    s3_key: str, *, poll_seconds: float = 1.0, max_polls: int = 60
) -> str:
    """OCR a (possibly multi-page) PDF in S3 via the async Textract API.

    Starts a DetectDocumentText job, polls until it finishes, follows
    NextToken pagination, and returns all detected LINE blocks joined by
    newlines. Polling only — no SNS/SQS topic required.

    Raises:
        OcrError: job failure, timeout, or any boto3/Textract error. The
            original exception (if any) is attached via `raise ... from`.
    """
    bucket = get_settings().AWS_S3_BUCKET
    client = _textract_client()
    try:
        start = client.start_document_text_detection(
            DocumentLocation={"S3Object": {"Bucket": bucket, "Name": s3_key}}
        )
        job_id = start["JobId"]

        status = "IN_PROGRESS"
        for _ in range(max_polls):
            resp = client.get_document_text_detection(JobId=job_id)
            status = resp.get("JobStatus", "IN_PROGRESS")
            if status != "IN_PROGRESS":
                break
            time.sleep(poll_seconds)
        else:
            raise OcrError(
                f"Textract job {job_id} for s3://{bucket}/{s3_key} timed out "
                f"after {max_polls} polls"
            )

        if status != "SUCCEEDED":
            reason = resp.get("StatusMessage", status)
            raise OcrError(
                f"Textract job {job_id} for s3://{bucket}/{s3_key} {status}: {reason}"
            )

        # `resp` is the first results page; follow NextToken for the rest.
        lines: list[str] = []
        next_token = None
        while True:
            page = (
                resp
                if next_token is None
                else client.get_document_text_detection(
                    JobId=job_id, NextToken=next_token
                )
            )
            lines.extend(
                b["Text"]
                for b in page.get("Blocks", [])
                if b.get("BlockType") == "LINE"
            )
            next_token = page.get("NextToken")
            if not next_token:
                break
    except (BotoCoreError, ClientError) as exc:
        raise OcrError(f"Textract failed for s3://{bucket}/{s3_key}: {exc}") from exc

    return "\n".join(lines)


def ocr_file_bytes(data: bytes, suffix: str, thread_id: str) -> str:
    """Upload file bytes to a temp S3 key, OCR them, delete the object, return text.

    PDFs use the async multi-page path (`textract_pdf_text`); images use the
    synchronous single-page path (`textract_ocr`). The temp object is always
    deleted afterwards so OCR scratch files don't accumulate in the bucket.

    Raises:
        OcrError: on any upload/Textract failure.
    """
    suffix = suffix.lower()
    mime = _MIME_BY_SUFFIX.get(suffix, "application/octet-stream")
    key = f"chatbot-ocr/{thread_id}/{uuid.uuid4().hex}{suffix}"
    try:
        upload_bytes(key, data, mime)
    except (BotoCoreError, ClientError) as exc:
        raise OcrError(f"Failed to stage {key} for OCR: {exc}") from exc

    try:
        if suffix == ".pdf":
            return textract_pdf_text(key)
        return textract_ocr(key)
    finally:
        try:
            delete_s3_object(key)
        except (BotoCoreError, ClientError):
            pass  # best-effort cleanup; don't mask the OCR result/error


def verify_pan_match(ocr_text: str, expected_pan: str) -> bool:
    """Return True iff the 10-character expected PAN appears in the OCR
    text after upper-casing and stripping non-alphanumerics. PAN format
    is AAAAA9999A."""
    cleaned = re.sub(r"[^A-Z0-9]", "", ocr_text.upper())
    return expected_pan.upper() in cleaned


def verify_aadhaar_match(ocr_text: str, expected_aadhaar: str) -> bool:
    """Return True iff the 12-digit expected Aadhaar appears in the OCR
    text (digits-only). Falls back to a last-4-digit match because
    Textract sometimes drops a group in `1234 5678 9012`."""
    digits = re.sub(r"\D", "", ocr_text)
    return expected_aadhaar in digits or expected_aadhaar[-4:] in digits
