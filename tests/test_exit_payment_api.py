from datetime import timedelta

from backend.app.constants import SESSION_CLOSED, SESSION_PAID, SLOT_FREE
from backend.app.models import ParkingSession, Slot, utcnow


def _entry(client, plate="KA01AB1234"):
    response = client.post("/api/v1/entries", json={"plate": plate, "vehicleType": "car"})
    assert response.status_code == 201
    return response.json()


def _make_fee_due(db_session, session_id, minutes=61):
    session = db_session.get(ParkingSession, session_id)
    session.entry_time = utcnow() - timedelta(minutes=minutes)
    session.fee = None
    db_session.commit()
    return session


def test_fee_endpoint_returns_duration_and_breakdown(client, db_session):
    entry = _entry(client)
    _make_fee_due(db_session, entry["sessionId"])

    response = client.get(f"/api/v1/sessions/{entry['sessionId']}/fee")

    assert response.status_code == 200
    body = response.json()
    assert body["sessionId"] == entry["sessionId"]
    assert body["amountDue"] == 50
    assert body["durationMin"] >= 61
    assert body["breakdown"]["vehicleType"] == "car"


def test_payment_endpoint_records_success_and_marks_session_paid(client, db_session):
    entry = _entry(client)
    session = _make_fee_due(db_session, entry["sessionId"])
    response = client.post("/api/v1/payments", json={
        "sessionId": session.id, "mode": "UPI", "amount": 50
    })

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "SUCCESS"
    assert body["receiptNo"].startswith(f"REC-{session.id}-")
    db_session.refresh(session)
    assert session.status == SESSION_PAID
    assert len(session.payments) == 1


def test_exit_authorisation_rejects_unpaid_session_and_keeps_slot_occupied(client, db_session):
    entry = _entry(client)
    session = _make_fee_due(db_session, entry["sessionId"])
    response = client.post(f"/api/v1/exits/{session.id}/authorise")

    assert response.status_code == 402
    assert response.json()["code"] == "PAYMENT_REQUIRED"
    db_session.refresh(session)
    assert session.status == "ACTIVE"
    assert db_session.get(Slot, session.slot_id).status != SLOT_FREE


def test_paid_exit_authorisation_closes_session_and_releases_slot(client, db_session):
    entry = _entry(client)
    session = _make_fee_due(db_session, entry["sessionId"])
    payment = client.post("/api/v1/payments", json={
        "sessionId": session.id, "mode": "UPI", "amount": 50
    })
    assert payment.status_code == 200

    response = client.post(f"/api/v1/exits/{session.id}/authorise")

    assert response.status_code == 200
    assert response.json()["gate"] == "OPEN"
    db_session.refresh(session)
    assert session.status == SESSION_CLOSED
    assert session.exit_time is not None
    assert db_session.get(Slot, session.slot_id).status == SLOT_FREE


def test_grace_period_exit_skips_payment_and_opens_gate(client, db_session):
    entry = _entry(client)
    session = _make_fee_due(db_session, entry["sessionId"], minutes=5)
    fee = client.get(f"/api/v1/sessions/{session.id}/fee")
    assert fee.status_code == 200
    assert fee.json()["amountDue"] == 0

    response = client.post(f"/api/v1/exits/{session.id}/authorise")

    assert response.status_code == 200
    assert response.json()["gate"] == "OPEN"
    db_session.refresh(session)
    assert session.status == SESSION_CLOSED


def test_payment_failure_is_recorded_and_session_remains_active(client, db_session):
    entry = _entry(client)
    session = _make_fee_due(db_session, entry["sessionId"])
    response = client.post("/api/v1/payments", json={
        "sessionId": session.id, "mode": "CARD", "amount": 50, "simulate": "failure"
    })

    assert response.status_code == 402
    assert response.json()["code"] == "PAYMENT_FAILED"
    db_session.refresh(session)
    assert session.status == "ACTIVE"
    assert len(session.payments) == 1
    assert session.payments[0].status == "FAILED"


def test_payment_timeout_is_recorded_and_session_remains_active(client, db_session):
    entry = _entry(client)
    session = _make_fee_due(db_session, entry["sessionId"])
    response = client.post("/api/v1/payments", json={
        "sessionId": session.id, "mode": "UPI", "amount": 50, "simulate": "timeout"
    })

    assert response.status_code == 504
    assert response.json()["code"] == "GATEWAY_TIMEOUT"
    db_session.refresh(session)
    assert session.status == "ACTIVE"
    assert len(session.payments) == 1
    assert session.payments[0].status == "TIMEOUT"


def test_override_endpoint_requires_staff_authentication(client):
    response = client.post("/api/v1/exits/1/override", json={"reason": "lost ticket"})
    assert response.status_code == 401
    assert response.json()["code"] == "UNAUTHORIZED"


def test_attendant_can_override_exit_through_api(client, db_session):
    entry = _entry(client)
    session = db_session.get(ParkingSession, entry["sessionId"])
    login = client.post("/api/v1/auth/login", json={
        "username": "attendant", "password": "attendant123"
    })
    assert login.status_code == 200
    token = login.json()["token"]

    response = client.post(
        f"/api/v1/exits/{session.id}/override",
        json={"reason": "Lost ticket verified"},
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json()["gate"] == "OPEN"
    db_session.refresh(session)
    assert session.status == SESSION_CLOSED
    assert session.override_reason == "Lost ticket verified"
    assert db_session.get(Slot, session.slot_id).status == SLOT_FREE
