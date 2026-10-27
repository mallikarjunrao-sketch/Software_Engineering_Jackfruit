from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth import EXPIRES_IN_SECONDS, create_token, get_current_user
from backend.app.database import get_db
from backend.app.errors import ApiError
from backend.app.models import User
from backend.app.security import hash_password, verify_password

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])

_dummy_hash: str | None = None


def _dummy_password_hash() -> str:
    # Used when the username is unknown, so the response time matches a wrong password.
    global _dummy_hash
    if _dummy_hash is None:
        _dummy_hash = hash_password("not-a-real-password")
    return _dummy_hash


class LoginRequest(BaseModel):
    username: str
    password: str


class LoginResponse(BaseModel):
    token: str
    role: str
    expiresIn: int


class MeResponse(BaseModel):
    username: str
    role: str


@router.post("/login", response_model=LoginResponse)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    password_hash = user.password_hash if user else _dummy_password_hash()
    password_ok = verify_password(payload.password, password_hash)
    if user is None or not password_ok:
        # Same status and message for both cases, so attackers cannot tell which was wrong.
        raise ApiError(401, "INVALID_CREDENTIALS", "Invalid username or password")
    return LoginResponse(token=create_token(user), role=user.role, expiresIn=EXPIRES_IN_SECONDS)


@router.get("/me", response_model=MeResponse)
def me(user: User = Depends(get_current_user)):
    return MeResponse(username=user.username, role=user.role)