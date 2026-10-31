from datetime import datetime, timedelta, timezone
import pytest

from backend.app.constants import CAR, TWO_WHEELER
from backend.app.errors import ApiError
from backend.app.models import ParkingSession, Vehicle
from backend.app.services.billing import calculate_fee, compute_session_fee


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
    fee_grace, brk_grace = calculate_fee(8, grace_minutes=10, first_hour_fee=10, extra_hour_fee=5, daily_cap=60)
    assert fee_grace == 0
    assert brk_grace["graceApplied"] is True

    fee_1h, _ = calculate_fee(45, grace_minutes=10, first_hour_fee=10, extra_hour_fee=5, daily_cap=60)
    assert fee_1h == 10

    fee_2h, _ = calculate_fee(65, grace_minutes=10, first_hour_fee=10, extra_hour_fee=5, daily_cap=60)
    assert fee_2h == 15

    fee_cap, brk_cap = calculate_fee(720, grace_minutes=10, first_hour_fee=10, extra_hour_fee=5, daily_cap=60)
    assert fee_cap == 60
    assert brk_cap["capApplied"] is True


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


def test_negative_duration_handled():
    fee, breakdown = calculate_fee(
        duration_minutes=-15,
        **CAR_TARIFF,
    )
    assert fee == 0
    assert breakdown["graceApplied"] is True


# ==============================================================================
# Service Tests for compute_session_fee
# ==============================================================================

def test_compute_session_fee_session_not_found(db_session):
    with pytest.raises(ApiError) as exc_info:
        compute_session_fee(999999, db_session)
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "SESSION_NOT_FOUND"


def test_compute_session_fee_tariff_not_found(db_session):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="UNKNOWN01", vehicle_type="rocket")
    db_session.add(vehicle)
    session = ParkingSession(
        plate="UNKNOWN01",
        slot_id="C-001",
        entry_time=now - timedelta(minutes=30),
    )
    db_session.add(session)
    db_session.commit()

    with pytest.raises(ApiError) as exc_info:
        compute_session_fee(session.id, db_session)
    assert exc_info.value.status_code == 404
    assert exc_info.value.code == "TARIFF_NOT_FOUND"


def test_compute_session_fee_completed_session(db_session):
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

    duration_min, amount_due, breakdown = compute_session_fee(session.id, db_session)

    assert duration_min == 61
    assert amount_due == 50
    assert session.fee == 50
    assert breakdown["vehicleType"] == CAR
    assert breakdown["billableHours"] == 2
    assert breakdown["graceApplied"] is False


def test_compute_session_fee_active_session_within_grace(db_session):
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

    duration_min, amount_due, breakdown = compute_session_fee(session.id, db_session)

    assert duration_min <= 6
    assert amount_due == 0
    assert session.fee == 0
    assert breakdown["graceApplied"] is True


def test_compute_session_fee_slot_fallback(db_session):
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    # Vehicle not in vehicles table; slot B-001 is TWO_WHEELER
    session = ParkingSession(
        plate="KA05BK9999",
        slot_id="B-001",
        entry_time=now - timedelta(minutes=45),
        exit_time=now,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    duration_min, amount_due, breakdown = compute_session_fee(session.id, db_session)

    assert duration_min == 45
    assert amount_due == 10  # TWO_WHEELER 1st hour fee = 10
    assert breakdown["vehicleType"] == TWO_WHEELER
    assert session.fee == 10
