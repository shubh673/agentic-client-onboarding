import asyncio
from datetime import datetime

from botocore.exceptions import ClientError
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models import Customer
from app.schemas import (
    CustomerMe,
    LoginRequest,
    SignupRequest,
    SignupResponse,
    TokenResponse,
)
from app.utils.cognito import (
    admin_create_user,
    admin_delete_user,
    admin_initiate_auth,
    admin_set_user_password_permanent,
)
from app.utils.jwt_auth import current_customer

router = APIRouter(prefix="/auth", tags=["auth"])


async def _next_application_number(db: AsyncSession) -> str:
    result = await db.execute(text("SELECT nextval('application_number_seq')"))
    seq = result.scalar_one()
    return f"APP-{datetime.utcnow().year}-{seq:06d}"


@router.post("/signup", response_model=SignupResponse, status_code=status.HTTP_201_CREATED)
async def signup(payload: SignupRequest, db: AsyncSession = Depends(get_db)) -> SignupResponse:
    existing = await db.execute(select(Customer).where(Customer.email == payload.email))
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already registered")

    application_number = await _next_application_number(db)

    try:
        cognito_sub, password = await asyncio.to_thread(
            admin_create_user,
            payload.email,
            payload.name,
            payload.phone_number,
            application_number,
        )
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "")
        if code == "UsernameExistsException":
            raise HTTPException(status.HTTP_409_CONFLICT, "Account already exists") from e
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Cognito {code}: {msg}") from e

    try:
        await asyncio.to_thread(
            admin_set_user_password_permanent, payload.email, password
        )
    except ClientError as e:
        # Best-effort rollback so the user can re-signup without UsernameExistsException.
        try:
            await asyncio.to_thread(admin_delete_user, payload.email)
        except ClientError:
            pass
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "")
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Cognito {code}: {msg}") from e

    customer = Customer(
        application_number=application_number,
        email=payload.email,
        name=payload.name,
        cognito_sub=cognito_sub,
    )
    db.add(customer)
    try:
        await db.commit()
    except IntegrityError as e:
        await db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "Customer already exists") from e

    return SignupResponse(application_number=application_number, email=payload.email)


@router.post("/login", response_model=TokenResponse)
async def login(payload: LoginRequest) -> TokenResponse:
    try:
        resp = await asyncio.to_thread(admin_initiate_auth, payload.username, payload.password)
    except ClientError as e:
        code = e.response.get("Error", {}).get("Code", "")
        msg = e.response.get("Error", {}).get("Message", "")
        if code in {"NotAuthorizedException", "UserNotFoundException"}:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid credentials") from e
        raise HTTPException(status.HTTP_502_BAD_GATEWAY, f"Cognito {code}: {msg}") from e

    auth = resp.get("AuthenticationResult")
    if auth is None:
        raise HTTPException(
            status.HTTP_502_BAD_GATEWAY,
            f"Unexpected Cognito response: {resp.get('ChallengeName')}",
        )

    return TokenResponse(
        access_token=auth["AccessToken"],
        id_token=auth["IdToken"],
        refresh_token=auth.get("RefreshToken"),
        expires_in=auth["ExpiresIn"],
    )


@router.get("/me", response_model=CustomerMe)
async def me(customer: Customer = Depends(current_customer)) -> CustomerMe:
    return CustomerMe.model_validate(customer)
