"""APMS-SR-007 (TC-SEC-07): 15 minute inactivity timeout and 5 minute login lockout."""
from datetime import timedelta

from sqlalchemy import select

from backend.app.auth import INACTIVITY_MINUTES
from backend.app.models import AuditLog, User, utcnow
from backend.app.routers.auth import LOCKOUT_MINUTES, MAX_FAILED_LOGINS
from backend.app.services import audit

LOGIN_URL = "/api/v1/auth/login"
ME_URL = "/api/v1/auth/me"
ADMIN = ("admin", "admin123")


def login(client, username, password):
    return client.post(LOGIN_URL, json={"username": username, "password": password})


def bearer(token):
    return {"Authorization": f"Bearer {token}"}


def get_admin(db_session):
    return db_session.scalar(select(User).where(User.username == "admin"))


def set_idle(db_session, minutes):
    """Pretend the admin's last request was `minutes` ago."""
    user = get_admin(db_session)
    user.last_activity = utcnow() - timedelta(minutes=minutes)
    db_session.commit()


def fail_login(client, times):
    return [login(client, "admin", "wrong-password-1") for _ in range(times)]


def audit_rows(db_session, action):
    return list(db_session.scalars(select(AuditLog).where(AuditLog.action == action)))


# ---- Session timeout -------------------------------------------------------

def test_policy_values_match_the_srs():
    assert INACTIVITY_MINUTES == 15
    assert MAX_FAILED_LOGINS == 5
    assert LOCKOUT_MINUTES == 5


def test_login_response_reports_the_inactivity_limit(client):
    assert login(client, *ADMIN).json()["expiresIn"] == 15 * 60


def test_login_records_last_activity(client, db_session):
    login(client, *ADMIN)
    assert get_admin(db_session).last_activity is not None


def test_session_idle_for_16_minutes_is_rejected(client, db_session):
    token = login(client, *ADMIN).json()["token"]
    set_idle(db_session, 16)
    response = client.get(ME_URL, headers=bearer(token))
    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_EXPIRED"


def test_session_idle_for_14_minutes_still_works(client, db_session):
    token = login(client, *ADMIN).json()["token"]
    set_idle(db_session, 14)
    assert client.get(ME_URL, headers=bearer(token)).status_code == 200


def test_each_request_restarts_the_15_minute_clock(client, db_session):
    token = login(client, *ADMIN).json()["token"]
    set_idle(db_session, 10)
    assert client.get(ME_URL, headers=bearer(token)).status_code == 200
    # The request above counted as activity, so the clock is back near zero.
    assert get_admin(db_session).last_activity > utcnow() - timedelta(minutes=1)
    set_idle(db_session, 10)
    assert client.get(ME_URL, headers=bearer(token)).status_code == 200


def test_expired_session_stays_expired_until_new_login(client, db_session):
    token = login(client, *ADMIN).json()["token"]
    set_idle(db_session, 20)
    assert client.get(ME_URL, headers=bearer(token)).status_code == 401
    # A second try with the same token must not revive the session.
    assert client.get(ME_URL, headers=bearer(token)).status_code == 401
    new_token = login(client, *ADMIN).json()["token"]
    assert client.get(ME_URL, headers=bearer(new_token)).status_code == 200


def test_staff_routes_also_enforce_the_timeout(client, db_session):
    token = login(client, *ADMIN).json()["token"]
    set_idle(db_session, 16)
    response = client.get("/api/v1/admin/ping", headers=bearer(token))
    assert response.status_code == 401
    assert response.json()["code"] == "SESSION_EXPIRED"


# ---- Login lockout ---------------------------------------------------------

def test_first_four_wrong_passwords_return_401_and_do_not_lock(client, db_session):
    responses = fail_login(client, 4)
    assert [r.status_code for r in responses] == [401, 401, 401, 401]
    assert get_admin(db_session).locked_until is None
    assert get_admin(db_session).failed_logins == 4


def test_fifth_wrong_password_locks_the_account(client, db_session):
    responses = fail_login(client, 5)
    assert responses[-1].status_code == 423
    assert responses[-1].json()["code"] == "ACCOUNT_LOCKED"
    user = get_admin(db_session)
    remaining = user.locked_until - utcnow()
    assert timedelta(minutes=4, seconds=50) < remaining <= timedelta(minutes=5)


def test_correct_password_is_refused_while_locked(client):
    fail_login(client, 5)
    response = login(client, *ADMIN)
    assert response.status_code == 423
    assert response.json()["code"] == "ACCOUNT_LOCKED"
    assert "token" not in response.json()


def test_wrong_password_while_locked_does_not_extend_the_lock(client, db_session):
    fail_login(client, 5)
    locked_until = get_admin(db_session).locked_until
    assert login(client, "admin", "still-wrong-1").status_code == 423
    assert get_admin(db_session).locked_until == locked_until


def test_login_works_again_after_the_5_minutes(client, db_session):
    fail_login(client, 5)
    user = get_admin(db_session)
    user.locked_until = utcnow() - timedelta(seconds=1)
    db_session.commit()
    response = login(client, *ADMIN)
    assert response.status_code == 200
    user = get_admin(db_session)
    assert user.locked_until is None
    assert user.failed_logins == 0


def test_lock_still_holds_just_before_5_minutes_are_over(client, db_session):
    fail_login(client, 5)
    user = get_admin(db_session)
    user.locked_until = utcnow() + timedelta(seconds=30)
    db_session.commit()
    assert login(client, *ADMIN).status_code == 423


def test_failure_count_starts_from_zero_after_a_lock_ends(client, db_session):
    fail_login(client, 5)
    user = get_admin(db_session)
    user.locked_until = utcnow() - timedelta(seconds=1)
    db_session.commit()
    responses = fail_login(client, 4)
    assert [r.status_code for r in responses] == [401, 401, 401, 401]
    assert fail_login(client, 1)[0].status_code == 423


def test_successful_login_resets_the_failure_count(client, db_session):
    fail_login(client, 4)
    assert login(client, *ADMIN).status_code == 200
    assert get_admin(db_session).failed_logins == 0
    responses = fail_login(client, 4)
    assert all(r.status_code == 401 for r in responses)


def test_lockout_is_per_account(client):
    fail_login(client, 5)
    response = login(client, "attendant", "attendant123")
    assert response.status_code == 200


def test_unknown_username_is_never_locked(client):
    responses = [login(client, "nobody", "wrong-password-1") for _ in range(8)]
    assert all(r.status_code == 401 for r in responses)


def test_lockout_is_written_to_the_audit_log(client, db_session):
    fail_login(client, 5)
    locked = audit_rows(db_session, audit.ACCOUNT_LOCKED)
    assert len(locked) == 1
    assert locked[0].user_id == get_admin(db_session).id
    assert len(audit_rows(db_session, audit.LOGIN_FAILED)) == 5


def test_attempt_while_locked_is_audited_without_the_password(client, db_session):
    fail_login(client, 5)
    login(client, "admin", "typed-while-locked-9")
    rows = audit_rows(db_session, audit.LOGIN_FAILED)
    assert len(rows) == 6
    assert all("typed-while-locked-9" not in row.details for row in rows)