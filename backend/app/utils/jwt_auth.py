"""Verify Cognito-issued JWTs against the user pool's JWKS."""
from functools import lru_cache

import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.database import get_db
from app.models import Customer

bearer_scheme = HTTPBearer(auto_error=True)


@lru_cache
def _jwks_client() -> jwt.PyJWKClient:
    return jwt.PyJWKClient(get_settings().cognito_jwks_url)


def verify_token(token: str) -> dict:
    """Validate a Cognito JWT signature, issuer, and client. Raises HTTPException
    on failure (used inside both HTTP dependencies and WebSocket guards)."""
    s = get_settings()
    try:
        signing_key = _jwks_client().get_signing_key_from_jwt(token).key
        # Cognito access tokens have token_use=access; ID tokens have token_use=id.
        # Access tokens don't carry an `aud` claim, so disable that check and
        # validate token_use + client_id manually below.
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            issuer=s.cognito_issuer,
            options={"verify_aud": False},
        )
    except jwt.PyJWTError as e:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, f"Invalid token: {e}") from e

    if claims.get("token_use") not in {"access", "id"}:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong token_use")
    if claims.get("client_id") not in {s.COGNITO_CLIENT_ID, None} and claims.get("aud") != s.COGNITO_CLIENT_ID:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong client_id / aud")

    return claims


def current_claims(
    creds: HTTPAuthorizationCredentials = Depends(bearer_scheme),
) -> dict:
    return verify_token(creds.credentials)


async def current_customer(
    claims: dict = Depends(current_claims),
    db: AsyncSession = Depends(get_db),
) -> Customer:
    sub = claims.get("sub")
    if not sub:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Token missing sub")
    result = await db.execute(select(Customer).where(Customer.cognito_sub == sub))
    customer = result.scalar_one_or_none()
    if customer is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Customer not found")
    return customer
