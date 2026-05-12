"""Document Verification tools.

Plain functions (no `@tool` decorator and no LLM in the loop) so the
DocumentVerificationAgent can call them directly. Mirrors the shape of
`agent/app/tools/document_tools.py` in the reference project.
"""
from __future__ import annotations

import re

from app.utils.aws import detect_text


def textract_ocr(s3_key: str) -> str:
    """Run AWS Textract DetectDocumentText on the given S3 object and
    return all detected LINE blocks joined by newlines.

    Boto3 is synchronous — callers must invoke this from a worker thread
    (`asyncio.to_thread`) so the FastAPI event loop stays responsive.
    """
    return detect_text(s3_key)


def verify_pan_match(ocr_text: str, expected_pan: str) -> bool:
    """Return True iff the 10-character expected PAN appears in the OCR
    text after upper-casing and stripping non-alphanumerics. PAN format
    is AAAAA9999A."""
    cleaned = re.sub(r"[^A-Z0-9]", "", ocr_text.upper())
    return expected_pan.upper() in cleaned


def verify_aadhaar_match(ocr_text: str, expected_aadhaar: str) -> bool:
    """Return True iff the 12-digit expected Aadhaar appears in the OCR
    text (digits-only comparison). Falls back to a last-4-digit match
    because Textract sometimes drops a group when Aadhaar prints as
    `1234 5678 9012`."""
    digits = re.sub(r"\D", "", ocr_text)
    return expected_aadhaar in digits or expected_aadhaar[-4:] in digits
