"""Cognito client + helpers. Boto3 calls are sync — wrap in asyncio.to_thread
when calling from async code."""
import base64
import hashlib
import hmac
import secrets
import string
from functools import lru_cache

import boto3
from botocore.client import BaseClient

from app.config import get_settings


@lru_cache
def cognito_client() -> BaseClient:
    s = get_settings()
    return boto3.client(
        "cognito-idp",
        region_name=s.AWS_REGION,
        aws_access_key_id=s.AWS_ACCESS_KEY_ID,
        aws_secret_access_key=s.AWS_SECRET_ACCESS_KEY,
    )


def secret_hash(username: str) -> str:
    s = get_settings()
    msg = (username + s.COGNITO_CLIENT_ID).encode()
    key = s.COGNITO_CLIENT_SECRET.encode()
    digest = hmac.new(key, msg, hashlib.sha256).digest()
    return base64.b64encode(digest).decode()


def generate_password(length: int = 14) -> str:
    """Generate a password that satisfies Cognito's default policy:
    upper + lower + digit + symbol, 8+ chars."""
    lowers = string.ascii_lowercase
    uppers = string.ascii_uppercase
    digits = string.digits
    symbols = "!@#$%^&*?-_+="
    pools = [lowers, uppers, digits, symbols]
    pwd = [secrets.choice(p) for p in pools]
    all_chars = lowers + uppers + digits + symbols
    pwd += [secrets.choice(all_chars) for _ in range(length - len(pools))]
    secrets.SystemRandom().shuffle(pwd)
    return "".join(pwd)


def admin_create_user(
    email: str, name: str, phone_number: str, application_number: str
) -> tuple[str, str]:
    """Create a Cognito user. Pool sign-in identifier is Email, so Username must
    be the email. We generate the temp password locally so we can immediately
    promote it to permanent. Returns (cognito_sub, generated_password).
    Cognito sends the invitation email automatically — the {username} placeholder
    will be the email address."""
    s = get_settings()
    password = generate_password()
    resp = cognito_client().admin_create_user(
        UserPoolId=s.COGNITO_USER_POOL_ID,
        Username=email,
        TemporaryPassword=password,
        UserAttributes=[
            {"Name": "email", "Value": email},
            {"Name": "email_verified", "Value": "true"},
            {"Name": "name", "Value": name},
            {"Name": "phone_number", "Value": phone_number},
            {"Name": "phone_number_verified", "Value": "true"},
            {"Name": "custom:applicationNumber", "Value": application_number},
        ],
        DesiredDeliveryMediums=["EMAIL"],
    )
    for attr in resp["User"]["Attributes"]:
        if attr["Name"] == "sub":
            return attr["Value"], password
    raise RuntimeError("Cognito response missing sub attribute")


def admin_set_user_password_permanent(email: str, password: str) -> None:
    """Promote the temp password to permanent so the user skips
    FORCE_CHANGE_PASSWORD and logs in directly with the emailed password."""
    s = get_settings()
    cognito_client().admin_set_user_password(
        UserPoolId=s.COGNITO_USER_POOL_ID,
        Username=email,
        Password=password,
        Permanent=True,
    )


def admin_get_phone_number(username: str) -> str | None:
    """Read the phone_number attribute from Cognito. Returns None if the
    attribute is missing or the user can't be fetched."""
    s = get_settings()
    try:
        resp = cognito_client().admin_get_user(
            UserPoolId=s.COGNITO_USER_POOL_ID,
            Username=username,
        )
    except Exception:
        return None
    for attr in resp.get("UserAttributes", []):
        if attr.get("Name") == "phone_number":
            return attr.get("Value")
    return None


def admin_delete_user(username: str) -> None:
    s = get_settings()
    cognito_client().admin_delete_user(
        UserPoolId=s.COGNITO_USER_POOL_ID,
        Username=username,
    )


def admin_initiate_auth(email: str, password: str) -> dict:
    """Authenticate by email (the pool's sign-in alias). SECRET_HASH is computed
    against whatever string is passed as USERNAME — here, the email."""
    s = get_settings()
    return cognito_client().admin_initiate_auth(
        UserPoolId=s.COGNITO_USER_POOL_ID,
        ClientId=s.COGNITO_CLIENT_ID,
        AuthFlow="ADMIN_USER_PASSWORD_AUTH",
        AuthParameters={
            "USERNAME": email,
            "PASSWORD": password,
            "SECRET_HASH": secret_hash(email),
        },
    )
