"""AWS S3 client + helpers. Textract lives in agents/tools/document_tools.py.

Boto3 calls in this module are synchronous and blocking — call them from
async code via `asyncio.to_thread` so the event loop stays responsive.
"""
import uuid
from functools import lru_cache

import boto3
from botocore.client import BaseClient

from app.config import get_settings


@lru_cache
def s3_client() -> BaseClient:
    s = get_settings()
    return boto3.client(
        "s3",
        region_name=s.AWS_REGION,
        aws_access_key_id=s.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=s.AWS_SECRET_ACCESS_KEY,
    )


def s3_key_for(application_id: uuid.UUID, doc_type: str, ext: str) -> str:
    return f"applications/{application_id}/{doc_type}{ext}"


def upload_bytes(key: str, body: bytes, content_type: str) -> None:
    s3_client().put_object(
        Bucket=get_settings().AWS_S3_BUCKET,
        Key=key,
        Body=body,
        ContentType=content_type,
        ServerSideEncryption="AES256",
    )


def presigned_get(key: str, ttl_seconds: int) -> str:
    return s3_client().generate_presigned_url(
        "get_object",
        Params={"Bucket": get_settings().AWS_S3_BUCKET, "Key": key},
        ExpiresIn=ttl_seconds,
    )


def delete_s3_object(key: str) -> None:
    s3_client().delete_object(Bucket=get_settings().AWS_S3_BUCKET, Key=key)
