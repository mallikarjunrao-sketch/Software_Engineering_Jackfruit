import math
from datetime import timedelta

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
from backend.app.models import User, utcnow
from backend.app.security import hash_password, verify_password
from backend.app.services import audit


router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

# APMS-SR-007: lock the account for 5 minutes after 5 failed logins in a row.
MAX_FAILED_LOGINS = 5
LOCKOUT_MINUTES = 5

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

    now = utcnow()

    if user is not None and user.locked_until is not None:
        if user.locked_until > now:
            # Refuse without checking the password, so a locked account cannot
            # be guessed at, and even the right password does not get in.
            minutes_left = math.ceil((user.locked_until - now).total_seconds() / 60)
            audit.record(
                db,
                audit.LOGIN_FAILED,
                user.id,
                "attempt while account locked"
            )
            raise ApiError(
                423,
                "ACCOUNT_LOCKED",
                f"Account is locked. Try again in {minutes_left} minute(s)."
            )

        # The lock has run out: start counting failures from zero again.
        user.locked_until = None
        user.failed_logins = 0

    password_hash = (
        user.password_hash if user else _dummy_password_hash()
    )

    password_ok = verify_password(
        payload.password,
        password_hash
    )

    if user is None or not password_ok:

        if user is None:
            audit.record(
                db,
                audit.LOGIN_FAILED,
                None,
                "unknown username"
            )
            raise ApiError(
                401,
                "INVALID_CREDENTIALS",
                "Invalid username or password"
            )

        user.failed_logins = (user.failed_logins or 0) + 1

        if user.failed_logins >= MAX_FAILED_LOGINS:
            user.locked_until = now + timedelta(minutes=LOCKOUT_MINUTES)
            user.failed_logins = 0
            # Both entries are saved together with the lock itself.
            audit.record(
                db,
                audit.LOGIN_FAILED,
                user.id,
                "wrong password",
                commit=False
            )
            audit.record(
                db,
                audit.ACCOUNT_LOCKED,
                user.id,
                f"{MAX_FAILED_LOGINS} failed logins, locked for {LOCKOUT_MINUTES} minutes"
            )
            raise ApiError(
                423,
                "ACCOUNT_LOCKED",
                f"Too many failed logins. Account is locked for {LOCKOUT_MINUTES} minutes."
            )

        # audit.record commits, which also saves the updated failed_logins.
        audit.record(
            db,
            audit.LOGIN_FAILED,
            user.id,
            "wrong password"
        )

        raise ApiError(
            401,
            "INVALID_CREDENTIALS",
            "Invalid username or password"
        )

    user.failed_logins = 0
    user.locked_until = None
    user.last_activity = now

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