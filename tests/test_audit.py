import pytest
from sqlalchemy import select, text
from sqlalchemy.exc import DatabaseError

from backend.app.models import AuditLog, User
from backend.app.services import audit

ADMIN = ("admin", "admin123")
ATTENDANT = ("attendant", "attendant123")
AUDIT_URL = "/api/v1/admin/audit"


def login(client, username, password):
    return client.post("/api/v1/auth/login", json={"username": username, "password": password})


def bearer(client, creds):
    return {"Authorization": f"Bearer {login(client, *creds).json()['token']}"}


def entries(db_session, action=None):
    query = select(AuditLog).order_by(AuditLog.id)
    if action:
        query = query.where(AuditLog.action == action)
    return list(db_session.scalars(query))


def test_record_stores_action_user_and_timestamp(db_session):
    entry = audit.record(db_session, audit.OVERRIDE, 1, "lost ticket")
    assert entry.id is not None
    assert entry.user_id == 1
    assert entry.action == "OVERRIDE"
    assert entry.details == "lost ticket"
    assert entry.timestamp is not None


def test_record_without_commit_joins_callers_transaction(db_session):
    audit.record(db_session, audit.TARIFF_CHANGE, 1, "car first hour 30 to 35", commit=False)
    db_session.rollback()
    assert entries(db_session, audit.TARIFF_CHANGE) == []


def test_successful_login_is_audited(client, db_session):
    login(client, *ADMIN)
    rows = entries(db_session, audit.LOGIN_SUCCESS)
    assert len(rows) == 1
    admin_id = db_session.scalar(select(User.id).where(User.username == "admin"))
    assert rows[0].user_id == admin_id


def test_failed_login_for_known_user_is_audited(client, db_session):
    login(client, "admin", "wrong-password-123")
    rows = entries(db_session, audit.LOGIN_FAILED)
    assert len(rows) == 1
    assert rows[0].user_id is not None
    assert "wrong-password-123" not in rows[0].details


def test_failed_login_for_unknown_user_does_not_log_what_was_typed(client, db_session):
    login(client, "typed-secret-in-username-box", "another-secret")
    rows = entries(db_session, audit.LOGIN_FAILED)
    assert len(rows) == 1
    assert rows[0].user_id is None
    assert "typed-secret" not in rows[0].details
    assert "another-secret" not in rows[0].details


def test_audit_entries_cannot_be_updated(db_session):
    entry = audit.record(db_session, audit.OVERRIDE, 1, "original")
    with pytest.raises(DatabaseError):
        db_session.execute(text("UPDATE audit_log SET details = 'edited'"))
    db_session.rollback()
    entry.details = "edited via ORM"
    with pytest.raises(DatabaseError):
        db_session.commit()
    db_session.rollback()
    assert entries(db_session)[0].details == "original"


def test_audit_entries_cannot_be_deleted(db_session):
    entry = audit.record(db_session, audit.OVERRIDE, 1, "keep me")
    with pytest.raises(DatabaseError):
        db_session.execute(text("DELETE FROM audit_log"))
    db_session.rollback()
    db_session.delete(entry)
    with pytest.raises(DatabaseError):
        db_session.commit()
    db_session.rollback()
    assert len(entries(db_session)) == 1


def test_admin_can_list_audit_newest_first(client, db_session):
    login(client, "admin", "wrong")
    headers = bearer(client, ADMIN)
    response = client.get(AUDIT_URL, headers=headers)
    assert response.status_code == 200
    body = response.json()
    assert [e["action"] for e in body][:2] == ["LOGIN_SUCCESS", "LOGIN_FAILED"]
    assert {"id", "userId", "action", "details", "timestamp"} <= set(body[0])


def test_audit_list_can_filter_by_action(client):
    login(client, "admin", "wrong")
    headers = bearer(client, ADMIN)
    body = client.get(AUDIT_URL, params={"action": "LOGIN_FAILED"}, headers=headers).json()
    assert body and all(e["action"] == "LOGIN_FAILED" for e in body)


def test_audit_list_limit_is_validated(client):
    headers = bearer(client, ADMIN)
    assert client.get(AUDIT_URL, params={"limit": 0}, headers=headers).status_code == 422
    assert client.get(AUDIT_URL, params={"limit": 501}, headers=headers).status_code == 422


def test_attendant_cannot_read_audit(client):
    response = client.get(AUDIT_URL, headers=bearer(client, ATTENDANT))
    assert response.status_code == 403


def test_no_token_cannot_read_audit(client):
    assert client.get(AUDIT_URL).status_code == 401


@pytest.mark.parametrize("method", ["post", "put", "patch", "delete"])
def test_audit_has_no_write_routes(client, method):
    response = getattr(client, method)(AUDIT_URL, headers=bearer(client, ADMIN))
    assert response.status_code == 405