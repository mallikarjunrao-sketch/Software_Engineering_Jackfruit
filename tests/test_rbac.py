from datetime import datetime, timedelta, timezone

import jwt
from sqlalchemy import select

from backend.app.auth import ALGORITHM, DEV_SECRET, require_admin
from backend.app.models import AuditLog
from backend.app.routers import admin

ADMIN = ("admin", "admin123")
ATTENDANT = ("attendant", "attendant123")
ADMIN_URL = "/api/v1/admin/ping"


def token_for(client, creds):
    response = client.post("/api/v1/auth/login", json={"username": creds[0], "password": creds[1]})
    return response.json()["token"]


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def denied_entries(db_session):
    return list(db_session.scalars(select(AuditLog).where(AuditLog.action == "ACCESS_DENIED")))


def test_attendant_gets_403_on_admin_endpoint(client):
    response = client.get(ADMIN_URL, headers=bearer(token_for(client, ATTENDANT)))
    assert response.status_code == 403
    assert response.json()["code"] == "FORBIDDEN"


def test_no_token_gets_401_on_admin_endpoint(client):
    response = client.get(ADMIN_URL)
    assert response.status_code == 401


def test_admin_can_use_admin_endpoint(client):
    response = client.get(ADMIN_URL, headers=bearer(token_for(client, ADMIN)))
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_denied_attempt_is_written_to_audit_log(client, db_session):
    client.get(ADMIN_URL, headers=bearer(token_for(client, ATTENDANT)))
    entries = denied_entries(db_session)
    assert len(entries) == 1
    assert entries[0].user_id is not None
    assert ADMIN_URL in entries[0].details
    assert "role=ATTENDANT" in entries[0].details


def test_allowed_request_creates_no_denied_entry(client, db_session):
    client.get(ADMIN_URL, headers=bearer(token_for(client, ADMIN)))
    assert denied_entries(db_session) == []


def test_forged_admin_role_claim_does_not_help(client, db_session):
    future = datetime.now(timezone.utc) + timedelta(minutes=5)
    forged = jwt.encode(
        {"sub": "attendant", "role": "ADMIN", "exp": future}, DEV_SECRET, algorithm=ALGORITHM
    )
    response = client.get(ADMIN_URL, headers=bearer(forged))
    assert response.status_code == 403
    assert len(denied_entries(db_session)) == 1


def test_admin_router_requires_admin_for_every_route():
    assert admin.router.routes
    assert any(dep.dependency is require_admin for dep in admin.router.dependencies)