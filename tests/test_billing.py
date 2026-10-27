from datetime import datetime, timedelta, timezone
import pytest

from backend.app.constants import CAR
from backend.app.models import ParkingSession, Vehicle
from backend.app.services.billing import calculate_fee


# ==============================================================================
# Unit Tests for TC-BIL-01 (APMS-F-010): Fee Computation Boundary Values
# ==============================================================================

# CAR Tariff from seed: grace=10 min, first_hour=30, extra_hour=20, daily_cap=200
CAR_TARIFF = {
    "grace_minutes": 10,
    "first_hour_fee": 30,
    "extra_hour_fee": 20,
    "daily_cap": 200,
}

TC_BIL_01_CASES = [
    # (duration_min, expected_fee, expected_billable_hours, expected_grace_applied, expected_cap_applied)
    (0, 0, 0, True, False),
    (9, 0, 0, True, False),
    (10, 0, 0, True, False),
    (11, 30, 1, False, False),
    (60, 30, 1, False, False),
    (61, 50, 2, False, False),
    (120, 50, 2, False, False),
    (121, 70, 3, False, False),
    (600, 200, 10, False, True),     # 10 hours: uncapped 210 -> capped at 200
    (1440, 200, 24, False, True),    # 24 hours: 1 full day cap 200
    (1500, 230, 25, False, True),    # 25 hours: 1 day cap (200) + 1st hour (30) = 230
    (2880, 400, 48, False, True),    # 48 hours: 2 day caps = 400
]


@pytest.mark.parametrize(
    "duration_min, expected_fee, expected_billable_hours, expected_grace, expected_cap",
    TC_BIL_01_CASES,
)
def test_tc_bil_01_car_boundary_values(
    duration_min,
    expected_fee,
    expected_billable_hours,
    expected_grace,
    expected_cap,
):
    fee, breakdown = calculate_fee(
        duration_minutes=duration_min,
        **CAR_TARIFF,
    )
    assert fee == expected_fee
    assert breakdown["billableHours"] == expected_billable_hours
    assert breakdown["graceApplied"] is expected_grace
    assert breakdown["capApplied"] is expected_cap


def test_two_wheeler_tariff_calculation():
    # TWO_WHEELER: grace=10, first_hour=10, extra_hour=5, daily_cap=60
    fee_grace, _ = calculate_fee(8, grace_minutes=10, first_hour_fee=10, extra_hour_fee=5, daily_cap=60)
    assert fee_grace == 0

    fee_1h, _ = calculate_fee(45, grace_minutes=10, first_hour_fee=10, extra_hour_fee=5, daily_cap=60)
    assert fee_1h == 10

    fee_2h, _ = calculate_fee(65, grace_minutes=10, first_hour_fee=10, extra_hour_fee=5, daily_cap=60)
    assert fee_2h == 15

    fee_cap, brk = calculate_fee(720, grace_minutes=10, first_hour_fee=10, extra_hour_fee=5, daily_cap=60)
    assert fee_cap == 60
    assert brk["capApplied"] is True


def test_ev_tariff_calculation():
    # EV: grace=10, first_hour=40, extra_hour=25, daily_cap=250
    fee_1h, _ = calculate_fee(30, grace_minutes=10, first_hour_fee=40, extra_hour_fee=25, daily_cap=250)
    assert fee_1h == 40

    fee_3h, _ = calculate_fee(130, grace_minutes=10, first_hour_fee=40, extra_hour_fee=25, daily_cap=250)
    assert fee_3h == 40 + 2 * 25  # 90


def test_accessible_tariff_calculation():
    # ACCESSIBLE: grace=10, first_hour=15, extra_hour=10, daily_cap=100
    fee_2h, _ = calculate_fee(75, grace_minutes=10, first_hour_fee=15, extra_hour_fee=10, daily_cap=100)
    assert fee_2h == 25


# ==============================================================================
# Integration Tests for GET /api/v1/sessions/{session_id}/fee
# ==============================================================================

def test_get_fee_session_not_found(client):
    response = client.get("/api/v1/sessions/999999/fee")
    assert response.status_code == 404
    data = response.json()
    assert data["code"] == "SESSION_NOT_FOUND"
    assert "requestId" in data


def test_get_fee_completed_session(client, db_session):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA01MJ1111", vehicle_type=CAR)
    db_session.add(vehicle)

    # 61 minutes duration -> 2 billable hours -> fee = 50
    session = ParkingSession(
        plate="KA01MJ1111",
        slot_id="C-001",
        entry_time=now - timedelta(minutes=61),
        exit_time=now,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    response = client.get(f"/api/v1/sessions/{session.id}/fee")
    assert response.status_code == 200
    data = response.json()

    assert data["sessionId"] == session.id
    assert data["durationMin"] == 61
    assert data["amountDue"] == 50
    assert data["breakdown"]["vehicleType"] == CAR
    assert data["breakdown"]["billableHours"] == 2
    assert data["breakdown"]["graceApplied"] is False


def test_get_fee_active_session_within_grace(client, db_session):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA01MJ2222", vehicle_type=CAR)
    db_session.add(vehicle)

    # Active session entered 5 minutes ago (within 10-minute grace)
    session = ParkingSession(
        plate="KA01MJ2222",
        slot_id="C-002",
        entry_time=now - timedelta(minutes=5),
        exit_time=None,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    response = client.get(f"/api/v1/sessions/{session.id}/fee")
    assert response.status_code == 200
    data = response.json()

    assert data["sessionId"] == session.id
    assert data["amountDue"] == 0
    assert data["breakdown"]["graceApplied"] is True
