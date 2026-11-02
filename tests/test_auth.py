
from datetime import datetime, timedelta, timezone

import jwt
import pytest

from backend.app.auth import (
    ALGORITHM,
    get_current_user,
    get_secret,
)
from backend.app.errors import ApiError
from backend.app.routers import auth as auth_router


TEST_SECRET = "test-secret-for-unit-testing-at-least-32-bytes"


def test_get_secret_uses_environment_variable(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)
    assert get_secret() == TEST_SECRET


def test_get_secret_rejects_missing_production_secret(monkeypatch):
    monkeypatch.delenv("JWT_SECRET", raising=False)
    monkeypatch.setenv("APP_ENV", "production")

    with pytest.raises(RuntimeError):
        get_secret()


@pytest.mark.parametrize(
    "authorization",
    [None, "Basic invalid-token", "Bearer"],
)
def test_get_current_user_rejects_malformed_header(
    authorization, db_session
):
    with pytest.raises(ApiError) as exc:
        get_current_user(authorization, db_session)

    assert exc.value.status_code == 401


def test_get_current_user_rejects_expired_token(
    monkeypatch, db_session
):
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)

    token = jwt.encode(
        {
            "sub": "admin",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        TEST_SECRET,
        algorithm=ALGORITHM,
    )

    with pytest.raises(ApiError) as exc:
        get_current_user(f"Bearer {token}", db_session)

    assert exc.value.code == "TOKEN_EXPIRED"


def test_get_current_user_rejects_invalid_token(
    monkeypatch, db_session
):
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)

    with pytest.raises(ApiError) as exc:
        get_current_user("Bearer invalid-token", db_session)

    assert exc.value.code == "INVALID_TOKEN"


def test_get_current_user_rejects_nonexistent_user(
    monkeypatch, db_session
):
    monkeypatch.setenv("JWT_SECRET", TEST_SECRET)

    token = jwt.encode(
        {
            "sub": "unknown-user",
            "exp": datetime.now(timezone.utc) + timedelta(minutes=5),
        },
        TEST_SECRET,
        algorithm=ALGORITHM,
    )

    with pytest.raises(ApiError) as exc:
        get_current_user(f"Bearer {token}", db_session)

    assert exc.value.code == "INVALID_TOKEN"


def test_login_unknown_user_returns_generic_error(
    client, monkeypatch
):
    monkeypatch.setattr(auth_router, "_dummy_hash", None)

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "unknown-user",
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_login_wrong_password_returns_generic_error(client):
    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "wrong-password",
        },
    )

    assert response.status_code == 401
    assert response.json()["code"] == "INVALID_CREDENTIALS"


def test_authenticated_user_can_access_me_endpoint(client):
    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "admin123",
        },
    )

    assert login.status_code == 200

    response = client.get(
        "/api/v1/auth/me",
        headers={
            "Authorization": f"Bearer {login.json()['token']}"
        },
    )

    assert response.status_code == 200
    assert response.json() == {
        "username": "admin",
        "role": "ADMIN",
    }
