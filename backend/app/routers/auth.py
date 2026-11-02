from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth import (
    EXPIRES_IN_SECONDS,
    create_token,
    get_current_user
)
from backend.app.database import get_db
from backend.app.errors import ApiError
from backend.app.models import User
from backend.app.security import hash_password, verify_password
from backend.app.services import audit


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_dummy_hash: str | None = None


def _dummy_password_hash() -> str:
    global _dummy_hash

    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-password")

    return _dummy_hash


class LoginRequest(BaseModel):

    model_config = ConfigDict(extra="forbid")

    username: str = Field(
        min_length=1,
        max_length=40,
        pattern=r"^[A-Za-z0-9_.-]+$"
    )

    password: str = Field(
        min_length=1,
        max_length=72
    )

    @field_validator("password")
    @classmethod
    def password_must_not_contain_control_characters(cls, value: str) -> str:

        if any(ord(char) < 32 or ord(char) == 127 for char in value):
            raise ValueError(
                "Password must not contain control characters"
            )

        if len(value.encode("utf-8")) > 72:
            raise ValueError(
                "Password must not exceed 72 UTF-8 bytes"
            )

        return value


class LoginResponse(BaseModel):
    token: str
    role: str
    expiresIn: int


class MeResponse(BaseModel):
    username: str
    role: str


@router.post("/login", response_model=LoginResponse)
def login(
    payload: LoginRequest,
    db: Session = Depends(get_db)
):

    user = db.scalar(
        select(User).where(User.username == payload.username)
    )

    password_hash = (
        user.password_hash if user else _dummy_password_hash()
    )

    password_ok = verify_password(
        payload.password,
        password_hash
    )

    if user is None or not password_ok:

        reason = (
            "unknown username"
            if user is None
            else "wrong password"
        )

        audit.record(
            db,
            audit.LOGIN_FAILED,
            user.id if user else None,
            reason
        )

        raise ApiError(
            401,
            "INVALID_CREDENTIALS",
            "Invalid username or password"
        )

    audit.record(
        db,
        audit.LOGIN_SUCCESS,
        user.id,
        "login"
    )

    return LoginResponse(
        token=create_token(user),
        role=user.role,
        expiresIn=EXPIRES_IN_SECONDS
    )


@router.get("/me", response_model=MeResponse)
def me(
    user: User = Depends(get_current_user)
):

    return MeResponse(
        username=user.username,
        role=user.role
    )