"""Fee boundary-value test suite (PARK-40).

Traceability:
- Requirement: APMS-F-010 (Compute parking fee)
- Acceptance Criteria: AC-F-010 (Fee matches tariff table for >= 10 boundary-value cases, including grace period)
- Test Plan: TC-BIL-01 (Fee computation boundary values, Section 4.4, Table 7 & Appendix B)

Equivalence partitions & boundary values covered:
1. Free Grace Period Boundary: negative, 0 min, grace - 1, grace, grace + 1
2. First Hour Slab Boundary: grace + 1, mid-hour, 59 min, 60 min, 61 min
3. Subsequent Hourly Slabs: 61 min, 119 min, 120 min, 121 min, 180 min, 181 min
4. Daily Cap Saturation Boundary: sub-cap hours, exact cap threshold, cap saturated
5. Multi-Day Rollover & Overnight: 23h59m, 24h, 24h01m, 25h, 48h, 48h01m, 7 days, 30 days
6. Cross-Vehicle Type Boundary Verification: CAR, TWO_WHEELER, EV, ACCESSIBLE
7. Dynamic & Extreme Tariff Rules: zero grace, zero extra-hour, low cap, high cap
8. Database Integration & Sub-Second Precision: Session record fee updates at boundary times
9. Exit Endpoint Integration: Zero-fee exit within grace vs billable exit past grace
"""

from datetime import datetime, timedelta, timezone
import pytest

from backend.app.constants import (
    CAR,
    SESSION_ACTIVE,
    TWO_WHEELER,
)
from backend.app.models import ParkingSession, Slot, Vehicle
from backend.app.services.billing import calculate_fee, compute_session_fee


# ==============================================================================
# 1. TC-BIL-01 Canonical Boundary-Value Cases (Test Plan Appendix B / Table 9)
# ==============================================================================

CAR_TARIFF = {
    "grace_minutes": 10,
    "first_hour_fee": 30,
    "extra_hour_fee": 20,
    "daily_cap": 200,
}

# (duration_min, expected_fee, expected_billable_hours, expected_grace, expected_cap, description)
TC_BIL_01_CANONICAL_CASES = [
    (0, 0, 0, True, False, "0 min: entry boundary, free grace period"),
    (9, 0, 0, True, False, "9 min: lower boundary of grace expiration (grace - 1)"),
    (10, 0, 0, True, False, "10 min: exact grace period boundary"),
    (11, 30, 1, False, False, "11 min: upper boundary of grace period (grace + 1, 1st hour starts)"),
    (60, 30, 1, False, False, "60 min: exact 1st hour boundary"),
    (61, 50, 2, False, False, "61 min: 2nd hour starts (1st hour + 1 extra hour)"),
    (120, 50, 2, False, False, "120 min: exact 2nd hour boundary"),
    (121, 70, 3, False, False, "121 min: 3rd hour starts"),
    (600, 200, 10, False, True, "10 hours: daily cap applied (uncapped 210 -> capped 200)"),
]


@pytest.mark.parametrize(
    "duration_min, expected_fee, expected_hours, expected_grace, expected_cap, desc",
    TC_BIL_01_CANONICAL_CASES,
)
def test_tc_bil_01_canonical_boundary_values(
    duration_min,
    expected_fee,
    expected_hours,
    expected_grace,
    expected_cap,
    desc,
):
    """TC-BIL-01: Verify canonical boundary values from Test Plan Appendix B Table 9."""
    fee, breakdown = calculate_fee(
        duration_minutes=duration_min,
        **CAR_TARIFF,
    )
    assert fee == expected_fee, f"Failed fee check for case: {desc}"
    assert breakdown["billableHours"] == expected_hours, f"Failed hours check for case: {desc}"
    assert breakdown["graceApplied"] is expected_grace, f"Failed grace check for case: {desc}"
    assert breakdown["capApplied"] is expected_cap, f"Failed cap check for case: {desc}"


# ==============================================================================
# 2. Daily Cap & Multi-Day Overnight Rollover Boundary Values
# ==============================================================================

OVERNIGHT_MULTI_DAY_CASES = [
    # Sub-cap progression
    (480, 170, 8, False, False, "8 hours: 30 + 7*20 = 170 (< 200 daily cap)"),
    (540, 190, 9, False, False, "9 hours: 30 + 8*20 = 190 (< 200 daily cap)"),
    (570, 200, 10, False, True, "9.5 hours: 10 billable hours uncapped 210 -> capped at 200"),
    (720, 200, 12, False, True, "12 hours (half day): capped at 200"),
    (1080, 200, 18, False, True, "18 hours: capped at 200"),
    # End of Day 1 boundaries
    (1439, 200, 24, False, True, "23 hours 59 min: last minute of Day 1 capped at 200"),
    (1440, 200, 24, False, True, "24 hours exact: 1 full cycle (1440 min) capped at 200"),
    # Day 2 rollover boundaries
    (1441, 230, 25, False, True, "24h 01m: Day 1 cap (200) + Day 2 1st hour (30) = 230"),
    (1500, 230, 25, False, True, "25 hours exact: Day 1 cap (200) + Day 2 1st hour (30) = 230"),
    (1501, 250, 26, False, True, "25h 01m: Day 1 cap (200) + Day 2 2nd hour (50) = 250"),
    (1560, 250, 26, False, True, "26 hours exact: Day 1 cap (200) + Day 2 2nd hour (50) = 250"),
    (2040, 400, 34, False, True, "34 hours: Day 1 cap (200) + Day 2 cap (200) = 400"),
    (2879, 400, 48, False, True, "47h 59m: Day 1 cap (200) + Day 2 cap (200) = 400"),
    (2880, 400, 48, False, True, "48 hours exact: 2 full days = 400"),
    # Day 3 rollover boundaries
    (2881, 430, 49, False, True, "48h 01m: 2 days cap (400) + Day 3 1st hour (30) = 430"),
    (4320, 600, 72, False, True, "72 hours exact: 3 full days = 600"),
    # Extended stays
    (10080, 1400, 168, False, True, "7 days (10080 min): 7 * 200 = 1400"),
    (43200, 6000, 720, False, True, "30 days (43200 min): 30 * 200 = 6000"),
]


@pytest.mark.parametrize(
    "duration_min, expected_fee, expected_hours, expected_grace, expected_cap, desc",
    OVERNIGHT_MULTI_DAY_CASES,
)
def test_overnight_and_multiday_boundary_values(
    duration_min,
    expected_fee,
    expected_hours,
    expected_grace,
    expected_cap,
    desc,
):
    """Verify daily cap transitions, 24-hour cycle boundaries, and multi-day rollovers."""
    fee, breakdown = calculate_fee(
        duration_minutes=duration_min,
        **CAR_TARIFF,
    )
    assert fee == expected_fee, f"Failed fee check for case: {desc}"
    assert breakdown["billableHours"] == expected_hours, f"Failed hours check for case: {desc}"
    assert breakdown["graceApplied"] is expected_grace, f"Failed grace check for case: {desc}"
    assert breakdown["capApplied"] is expected_cap, f"Failed cap check for case: {desc}"


# ==============================================================================
# 3. Cross-Vehicle Type Boundary Values
# ==============================================================================

TWO_WHEELER_TARIFF = {
    "grace_minutes": 10,
    "first_hour_fee": 10,
    "extra_hour_fee": 5,
    "daily_cap": 60,
}

EV_TARIFF = {
    "grace_minutes": 10,
    "first_hour_fee": 40,
    "extra_hour_fee": 25,
    "daily_cap": 250,
}

ACCESSIBLE_TARIFF = {
    "grace_minutes": 15,  # 15 minutes grace for accessible vehicles
    "first_hour_fee": 15,
    "extra_hour_fee": 10,
    "daily_cap": 100,
}


@pytest.mark.parametrize(
    "duration_min, expected_fee, expected_hours, expected_grace, expected_cap",
    [
        (0, 0, 0, True, False),
        (9, 0, 0, True, False),
        (10, 0, 0, True, False),
        (11, 10, 1, False, False),
        (60, 10, 1, False, False),
        (61, 15, 2, False, False),
        (120, 15, 2, False, False),
        (121, 20, 3, False, False),
        (660, 60, 11, False, False),  # 11 hours: 10 + 10*5 = 60 exactly equals daily_cap
        (720, 60, 12, False, True),   # 12 hours: uncapped 65 -> capped at 60
        (1440, 60, 24, False, True),  # 24 hours exact: 60
        (1441, 70, 25, False, True),  # 24h 01m: 60 + 10 = 70
        (2880, 120, 48, False, True), # 48 hours exact: 120
    ],
)
def test_two_wheeler_boundary_values(duration_min, expected_fee, expected_hours, expected_grace, expected_cap):
    """Verify boundary conditions for TWO_WHEELER tariff."""
    fee, brk = calculate_fee(duration_min, **TWO_WHEELER_TARIFF)
    assert fee == expected_fee
    assert brk["billableHours"] == expected_hours
    assert brk["graceApplied"] is expected_grace
    assert brk["capApplied"] is expected_cap


@pytest.mark.parametrize(
    "duration_min, expected_fee, expected_hours, expected_grace, expected_cap",
    [
        (0, 0, 0, True, False),
        (10, 0, 0, True, False),
        (11, 40, 1, False, False),
        (60, 40, 1, False, False),
        (61, 65, 2, False, False),
        (120, 65, 2, False, False),
        (121, 90, 3, False, False),
        (540, 240, 9, False, False),   # 9 hours: 40 + 8*25 = 240 (< 250 cap)
        (600, 250, 10, False, True),   # 10 hours: uncapped 265 -> capped at 250
        (1440, 250, 24, False, True),  # 24 hours: 250
        (1441, 290, 25, False, True),  # Day 2 rollover: 250 + 40 = 290
    ],
)
def test_ev_boundary_values(duration_min, expected_fee, expected_hours, expected_grace, expected_cap):
    """Verify boundary conditions for EV tariff."""
    fee, brk = calculate_fee(duration_min, **EV_TARIFF)
    assert fee == expected_fee
    assert brk["billableHours"] == expected_hours
    assert brk["graceApplied"] is expected_grace
    assert brk["capApplied"] is expected_cap


@pytest.mark.parametrize(
    "duration_min, expected_fee, expected_hours, expected_grace, expected_cap",
    [
        (0, 0, 0, True, False),
        (14, 0, 0, True, False),       # 14 min: within 15 min grace
        (15, 0, 0, True, False),       # 15 min: exact boundary of 15 min grace
        (16, 15, 1, False, False),      # 16 min: grace expired, 1st hour charged
        (60, 15, 1, False, False),
        (61, 25, 2, False, False),
        (120, 25, 2, False, False),
        (121, 35, 3, False, False),
        (540, 95, 9, False, False),    # 9 hours: 15 + 8*10 = 95 (< 100 cap)
        (600, 100, 10, False, True),   # 10 hours: uncapped 105 -> capped at 100
        (1440, 100, 24, False, True),
        (1441, 115, 25, False, True),  # Day 2 rollover: 100 + 15 = 115
    ],
)
def test_accessible_boundary_values(duration_min, expected_fee, expected_hours, expected_grace, expected_cap):
    """Verify boundary conditions for ACCESSIBLE tariff (with 15 min grace period)."""
    fee, brk = calculate_fee(duration_min, **ACCESSIBLE_TARIFF)
    assert fee == expected_fee
    assert brk["billableHours"] == expected_hours
    assert brk["graceApplied"] is expected_grace
    assert brk["capApplied"] is expected_cap


# ==============================================================================
# 4. Extreme & Equivalence Class Boundaries (Negative, Zero, Flat Rates)
# ==============================================================================

def test_negative_and_zero_duration_boundaries():
    """Verify system clamps negative durations to 0 and treats them as free grace period."""
    fee_neg, brk_neg = calculate_fee(-1, **CAR_TARIFF)
    assert fee_neg == 0
    assert brk_neg["graceApplied"] is True
    assert brk_neg["billableHours"] == 0

    fee_neg_large, brk_neg_large = calculate_fee(-1440, **CAR_TARIFF)
    assert fee_neg_large == 0
    assert brk_neg_large["graceApplied"] is True

    fee_zero, brk_zero = calculate_fee(0, **CAR_TARIFF)
    assert fee_zero == 0
    assert brk_zero["graceApplied"] is True


def test_zero_grace_period_boundary():
    """Verify behavior when grace_minutes is configured to 0."""
    zero_grace_tariff = {
        "grace_minutes": 0,
        "first_hour_fee": 30,
        "extra_hour_fee": 20,
        "daily_cap": 200,
    }
    # 0 min duration: still 0 fee
    fee_0, brk_0 = calculate_fee(0, **zero_grace_tariff)
    assert fee_0 == 0
    assert brk_0["graceApplied"] is True

    # 1 min duration: immediately charges 1st hour fee because grace is 0
    fee_1, brk_1 = calculate_fee(1, **zero_grace_tariff)
    assert fee_1 == 30
    assert brk_1["graceApplied"] is False
    assert brk_1["billableHours"] == 1


def test_zero_extra_hour_fee_flat_rate_boundary():
    """Verify flat rate fee structure where extra_hour_fee is 0."""
    flat_rate_tariff = {
        "grace_minutes": 10,
        "first_hour_fee": 50,
        "extra_hour_fee": 0,
        "daily_cap": 50,
    }
    # Within grace
    fee_grace, _ = calculate_fee(10, **flat_rate_tariff)
    assert fee_grace == 0

    # 1 hour
    fee_1h, brk_1h = calculate_fee(60, **flat_rate_tariff)
    assert fee_1h == 50
    assert brk_1h["billableHours"] == 1

    # 10 hours: remains 50
    fee_10h, brk_10h = calculate_fee(600, **flat_rate_tariff)
    assert fee_10h == 50
    assert brk_10h["billableHours"] == 10

    # Day 2: 24h01m -> 50 + 50 = 100
    fee_day2, _ = calculate_fee(1441, **flat_rate_tariff)
    assert fee_day2 == 100


def test_daily_cap_equal_to_first_hour_boundary():
    """Verify immediate capping when daily_cap equals first_hour_fee."""
    immediate_cap_tariff = {
        "grace_minutes": 10,
        "first_hour_fee": 50,
        "extra_hour_fee": 25,
        "daily_cap": 50,
    }
    fee_1h, brk_1h = calculate_fee(60, **immediate_cap_tariff)
    assert fee_1h == 50
    assert brk_1h["capApplied"] is False  # uncapped fee (50) did not exceed daily cap (50)

    fee_2h, brk_2h = calculate_fee(61, **immediate_cap_tariff)
    assert fee_2h == 50
    assert brk_2h["capApplied"] is True   # uncapped fee (75) capped at 50


# ==============================================================================
# 5. Database Integration & Session Duration Boundaries
# ==============================================================================

def test_compute_session_fee_database_boundary_exact_grace(db_session):
    """Verify compute_session_fee at exact grace period boundary (10 minutes) in DB."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA05BV0010", vehicle_type=CAR)
    db_session.merge(vehicle)

    session = ParkingSession(
        plate="KA05BV0010",
        slot_id="C-001",
        entry_time=now - timedelta(minutes=10),
        exit_time=now,
        status=SESSION_ACTIVE,
    )
    db_session.add(session)
    db_session.commit()

    duration_min, amount_due, breakdown = compute_session_fee(session.id, db_session)
    assert duration_min == 10
    assert amount_due == 0
    assert session.fee == 0
    assert breakdown["graceApplied"] is True


def test_compute_session_fee_database_boundary_grace_plus_one(db_session):
    """Verify compute_session_fee at grace + 1 minute (11 minutes) in DB."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA05BV0011", vehicle_type=CAR)
    db_session.merge(vehicle)

    session = ParkingSession(
        plate="KA05BV0011",
        slot_id="C-001",
        entry_time=now - timedelta(minutes=11),
        exit_time=now,
        status=SESSION_ACTIVE,
    )
    db_session.add(session)
    db_session.commit()

    duration_min, amount_due, breakdown = compute_session_fee(session.id, db_session)
    assert duration_min == 11
    assert amount_due == 30
    assert session.fee == 30
    assert breakdown["graceApplied"] is False
    assert breakdown["billableHours"] == 1


def test_compute_session_fee_database_boundary_hourly_transitions(db_session):
    """Verify compute_session_fee at 60 min vs 61 min boundaries in DB."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA05BV0060", vehicle_type=CAR)
    db_session.merge(vehicle)

    # 60 min
    s60 = ParkingSession(
        plate="KA05BV0060",
        slot_id="C-001",
        entry_time=now - timedelta(minutes=60),
        exit_time=now,
        status=SESSION_ACTIVE,
    )
    # 61 min
    s61 = ParkingSession(
        plate="KA05BV0060",
        slot_id="C-002",
        entry_time=now - timedelta(minutes=61),
        exit_time=now,
        status=SESSION_ACTIVE,
    )
    db_session.add(s60)
    db_session.add(s61)
    db_session.commit()

    d60, fee60, brk60 = compute_session_fee(s60.id, db_session)
    d61, fee61, brk61 = compute_session_fee(s61.id, db_session)

    assert d60 == 60
    assert fee60 == 30
    assert brk60["billableHours"] == 1

    assert d61 == 61
    assert fee61 == 50
    assert brk61["billableHours"] == 2


def test_compute_session_fee_subsecond_boundary_precision(db_session):
    """Verify duration seconds truncation (e.g. 10 minutes 59 seconds rounds to 10 min, grace applies)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA05BV1059", vehicle_type=CAR)
    db_session.merge(vehicle)

    # 10 minutes 59 seconds duration
    session = ParkingSession(
        plate="KA05BV1059",
        slot_id="C-001",
        entry_time=now - timedelta(minutes=10, seconds=59),
        exit_time=now,
        status=SESSION_ACTIVE,
    )
    db_session.add(session)
    db_session.commit()

    duration_min, amount_due, breakdown = compute_session_fee(session.id, db_session)
    assert duration_min == 10
    assert amount_due == 0
    assert breakdown["graceApplied"] is True


def test_compute_session_fee_database_slot_fallback_boundary(db_session):
    """Verify fallback to slot vehicle_type when vehicle is not pre-registered in Vehicle table."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    slot = db_session.get(Slot, "B-001")
    assert slot.slot_type == TWO_WHEELER

    # Plate NOT in Vehicle table; slot B-001 is two_wheeler (grace=10, 1st=10)
    session = ParkingSession(
        plate="KA99UNREG1",
        slot_id="B-001",
        entry_time=now - timedelta(minutes=11),
        exit_time=now,
        status=SESSION_ACTIVE,
    )
    db_session.add(session)
    db_session.commit()

    duration_min, amount_due, breakdown = compute_session_fee(session.id, db_session)
    assert duration_min == 11
    assert amount_due == 10
    assert breakdown["vehicleType"] == TWO_WHEELER


# ==============================================================================
# 6. Exit API Endpoint Boundary Testing
# ==============================================================================

def test_exit_endpoint_boundary_within_grace(client, db_session):
    """Verify Exit API reports amountDue = 0 when vehicle duration is within 10-minute grace."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA05EX0010", vehicle_type=CAR)
    db_session.merge(vehicle)

    session = ParkingSession(
        plate="KA05EX0010",
        slot_id="C-001",
        entry_time=now - timedelta(minutes=10),
        status=SESSION_ACTIVE,
    )
    db_session.add(session)
    db_session.commit()

    response = client.post("/api/v1/exits", json={"plate": "KA05EX0010"})
    assert response.status_code == 200
    data = response.json()
    assert data["sessionId"] == session.id
    assert data["amountDue"] == 0


def test_exit_endpoint_boundary_grace_expired(client, db_session):
    """Verify Exit API reports amountDue = 30 when vehicle duration exceeds grace (11 minutes)."""
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA05EX0011", vehicle_type=CAR)
    db_session.merge(vehicle)

    session = ParkingSession(
        plate="KA05EX0011",
        slot_id="C-002",
        entry_time=now - timedelta(minutes=11),
        status=SESSION_ACTIVE,
    )
    db_session.add(session)
    db_session.commit()

    response = client.post("/api/v1/exits", json={"plate": "KA05EX0011"})
    assert response.status_code == 200
    data = response.json()
    assert data["sessionId"] == session.id
    assert data["amountDue"] == 30
