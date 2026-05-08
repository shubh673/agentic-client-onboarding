import uuid
from datetime import date, datetime

from pydantic import BaseModel, ConfigDict, EmailStr, Field, field_validator

PAN_REGEX = r"^[A-Z]{5}[0-9]{4}[A-Z]$"
AADHAAR_REGEX = r"^[0-9]{12}$"
MOBILE_REGEX = r"^[+]?[0-9 \-]{7,20}$"


class ApplicationCreate(BaseModel):
    full_name: str = Field(min_length=1, max_length=255)
    dob: date
    mobile: str = Field(pattern=MOBILE_REGEX)
    email: EmailStr
    address: str = Field(min_length=1)
    pan_number: str = Field(pattern=PAN_REGEX)
    aadhaar_number: str = Field(pattern=AADHAAR_REGEX)

    @field_validator("dob")
    @classmethod
    def dob_not_future(cls, v: date) -> date:
        if v > date.today():
            raise ValueError("DOB cannot be in the future")
        return v

    @field_validator("pan_number")
    @classmethod
    def pan_uppercase(cls, v: str) -> str:
        return v.upper()


class DocumentResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    doc_type: str
    original_filename: str
    mime_type: str
    size_bytes: int
    uploaded_at: datetime


class ApplicationResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    full_name: str
    dob: date
    mobile: str
    email: str
    address: str
    pan_number: str
    aadhaar_number: str
    current_stage: int
    status: str
    verification_reason: str | None = None
    created_at: datetime
    updated_at: datetime
    documents: list[DocumentResponse] = []


class LogEntryResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    application_id: uuid.UUID
    stage: int
    level: str
    message: str
    ts: datetime
