"""Document Verification tools.

Self-contained: owns its boto3 Textract client + the OCR call, plus the
regex matchers used by DocumentVerificationAgent. No LangChain decorators —
the agent calls these functions directly.

Boto3 is blocking; call `textract_ocr` from async code via
`asyncio.to_thread` so the event loop stays responsive.
"""
from __future__ import annotations

import re
from functools import lru_cache

import boto3
from botocore.client import BaseClient
from botocore.exceptions import BotoCoreError, ClientError

from app.config import get_settings


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
