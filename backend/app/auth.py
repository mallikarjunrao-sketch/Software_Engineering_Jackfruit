import os
from datetime import datetime, timedelta, timezone

import jwt
from fastapi import Depends, Header, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.constants import ROLE_ADMIN, ROLE_ATTENDANT
from backend.app.database import get_db
from backend.app.errors import ApiError
from backend.app.models import User
from backend.app.services import audit

ALGORITHM = "HS256"
TOKEN_MINUTES = 15
EXPIRES_IN_SECONDS = TOKEN_MINUTES * 60

# Development default only. It must never be used on staging or production.
DEV_SECRET = "dev-only-secret-never-use-on-staging-0123456789"


def get_secret() -> str:
    secret = os.getenv("JWT_SECRET")
    if secret:
        return secret
    if os.getenv("APP_ENV", "dev") == "dev":
        return DEV_SECRET
    raise RuntimeError("JWT_SECRET must be set when APP_ENV is not 'dev'")


def create_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    claims = {
        "sub": user.username,
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=TOKEN_MINUTES),
    }
    return jwt.encode(claims, get_secret(), algorithm=ALGORITHM)


def get_current_user(
    authorization: str | None = Header(default=None),
    db: Session = Depends(get_db),
) -> User:
    if not authorization or not authorization.startswith("Bearer "):
        raise ApiError(401, "UNAUTHORIZED", "Missing or malformed Authorization header")
    token = authorization.split(" ", 1)[1].strip()
    try:
        claims = jwt.decode(token, get_secret(), algorithms=[ALGORITHM])
    except jwt.ExpiredSignatureError:
        raise ApiError(401, "TOKEN_EXPIRED", "The token has expired") from None
    except jwt.InvalidTokenError:
        raise ApiError(401, "INVALID_TOKEN", "The token is not valid") from None
    user = db.scalar(select(User).where(User.username == claims.get("sub")))
    if user is None:
        raise ApiError(401, "INVALID_TOKEN", "The token is not valid")
    return user


def require_role(*roles: str):
    def checker(
        request: Request,
        user: User = Depends(get_current_user),
        db: Session = Depends(get_db),
    ) -> User:
        # The role is read from the database user, never from the token, so a
        # forged or stale "role" claim cannot grant access.
        if user.role not in roles:
            audit.record(
                db,
                audit.ACCESS_DENIED,
                user.id,
                f"{request.method} {request.url.path} role={user.role} needs={'/'.join(roles)}",
            )
            raise ApiError(403, "FORBIDDEN", "You do not have permission for this action")
        return user

    return checker


# Ready-made dependencies for other routers (APMS-SR-003).
require_admin = require_role(ROLE_ADMIN)
require_staff = require_role(ROLE_ADMIN, ROLE_ATTENDANT)