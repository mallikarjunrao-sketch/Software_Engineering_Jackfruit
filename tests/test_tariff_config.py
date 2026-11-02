from datetime import datetime, timedelta, timezone
import pytest
from sqlalchemy import select

from backend.app.constants import (
    ACCESSIBLE,
    CAR,
    EV,
    ROLE_ADMIN,
    ROLE_ATTENDANT,
    SLOT_OCCUPIED,
    TWO_WHEELER,
)
from backend.app.errors import ApiError
from backend.app.models import AuditLog, ParkingSession, Slot, Tariff, User, Vehicle
from backend.app.services.availability import get_availability
from backend.app.services.billing import compute_session_fee
from backend.app.services.slots import allocate_slot, free_slot
from backend.app.services.tariff import (
    configure_zone_slots,
    create_zone,
    get_tariff,
    list_tariffs,
    list_zones_overview,
    update_tariff,
)


# ==============================================================================
# Helpers
# ==============================================================================

def get_user_by_role(db_session, role: str) -> User:
    user = db_session.scalar(select(User).where(User.role == role))
    assert user is not None, f"User with role {role} not found"
    return user


# ==============================================================================
# TC-BIL-02: Configure tariff, zones and slots (APMS-F-011)
# ==============================================================================

def test_tc_bil_02_tariff_and_zone_change_takes_effect_without_restart(db_session):
    """TC-BIL-02: Change a tariff and a zone size, then run a new entry and exit.

    Verifies that configuration changes take effect immediately for new sessions without restarting.
    """
    admin = get_user_by_role(db_session, ROLE_ADMIN)

    # 1. Verify baseline car tariff and availability
    baseline_tariff = get_tariff(db_session, CAR)
    assert baseline_tariff["graceMinutes"] == 10
    assert baseline_tariff["firstHourFee"] == 30
    assert get_availability(db_session, "L1-CAR").byType["car"].total == 20

    # 2. Admin changes car tariff: grace period 10 -> 15 min, first hour 30 -> 45, daily cap 200 -> 250
    updated_tariff = update_tariff(
        db=db_session,
        vehicle_type=CAR,
        grace_minutes=15,
        first_hour_fee=45,
        extra_hour_fee=25,
        daily_cap=250,
        user=admin,
    )
    assert updated_tariff["graceMinutes"] == 15
    assert updated_tariff["firstHourFee"] == 45

    # 3. Admin expands car zone from 20 to 25 slots
    zone_res = configure_zone_slots(
        db=db_session,
        zone_name="L1-CAR",
        target_count=25,
        user=admin,
    )
    assert zone_res["totalSlots"] == 25
    assert zone_res["freeSlots"] == 25

    # Live availability reflects the new 25 total slots immediately
    avail = get_availability(db_session, "L1-CAR").byType["car"]
    assert avail.total == 25
    assert avail.free == 25

    # 4. Run a new vehicle entry under the new configuration
    vehicle = Vehicle(plate="KA09TC0002", vehicle_type=CAR)
    db_session.add(vehicle)
    slot = allocate_slot(db_session, CAR)
    assert slot is not None

    now = datetime.now(timezone.utc).replace(tzinfo=None)
    session = ParkingSession(
        plate="KA09TC0002",
        slot_id=slot.id,
        entry_time=now - timedelta(minutes=14),  # Parked 14 minutes
        exit_time=None,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)

    # 5. Compute fee for the new session
    # Under old tariff (10m grace), 14 minutes would cost 30.
    # Under NEW tariff (15m grace), 14 minutes is inside grace period -> fee is 0!
    duration, amount_due, breakdown = compute_session_fee(session.id, db_session)
    assert duration == 14
    assert amount_due == 0
    assert breakdown["graceApplied"] is True

    # Under new tariff, 20 minutes should charge the new firstHourFee of 45 (old was 30)
    session.entry_time = now - timedelta(minutes=20)
    db_session.commit()
    duration_20, amount_20, breakdown_20 = compute_session_fee(session.id, db_session)
    assert duration_20 == 20
    assert amount_20 == 45
    assert breakdown_20["firstHourFee"] == 45

    # 6. Free the slot and verify availability count reflects the 25 capacity
    free_slot(db_session, slot.id)
    db_session.commit()
    assert get_availability(db_session, "L1-CAR").byType["car"].free == 25


# ==============================================================================
# RBAC Enforcement (APMS-SR-003)
# ==============================================================================

def test_attendant_forbidden_from_configuring_tariff(db_session):
    attendant = get_user_by_role(db_session, ROLE_ATTENDANT)

    with pytest.raises(ApiError) as exc_info:
        update_tariff(
            db=db_session,
            vehicle_type=CAR,
            grace_minutes=15,
            first_hour_fee=40,
            extra_hour_fee=20,
            daily_cap=200,
            user=attendant,
        )
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "FORBIDDEN"

    # Verify ACCESS_DENIED is logged
    denied = db_session.scalar(
        select(AuditLog).where(AuditLog.action == "ACCESS_DENIED").order_by(AuditLog.id.desc())
    )
    assert denied is not None
    assert denied.user_id == attendant.id
    assert "update_tariff" in denied.details


def test_unauthenticated_caller_rejected_for_tariff_and_zones(db_session):
    with pytest.raises(ApiError) as exc1:
        update_tariff(db_session, CAR, 10, 30, 20, 200, user=None)
    assert exc1.value.status_code == 401

    with pytest.raises(ApiError) as exc2:
        configure_zone_slots(db_session, "L1-CAR", 25, user=None)
    assert exc2.value.status_code == 401

    with pytest.raises(ApiError) as exc3:
        create_zone(db_session, "L2-CAR", CAR, user=None)
    assert exc3.value.status_code == 401


def test_attendant_forbidden_from_configuring_zone_slots(db_session):
    attendant = get_user_by_role(db_session, ROLE_ATTENDANT)

    with pytest.raises(ApiError) as exc_info:
        configure_zone_slots(db_session, "L1-CAR", 30, user=attendant)
    assert exc_info.value.status_code == 403


def test_attendant_forbidden_from_creating_zones(db_session):
    attendant = get_user_by_role(db_session, ROLE_ATTENDANT)

    with pytest.raises(ApiError) as exc_info:
        create_zone(db_session, name="L2-TEST", vehicle_type=CAR, user=attendant)
    assert exc_info.value.status_code == 403
    assert exc_info.value.code == "FORBIDDEN"


# ==============================================================================
# Tariff Validation Tests
# ==============================================================================

def test_tariff_input_validations(db_session):
    admin = get_user_by_role(db_session, ROLE_ADMIN)

    # Invalid vehicle type
    with pytest.raises(ApiError) as exc1:
        update_tariff(db_session, "airplane", 10, 30, 20, 200, user=admin)
    assert exc1.value.status_code == 422
    assert exc1.value.code == "INVALID_TARIFF"

    # Negative grace minutes
    with pytest.raises(ApiError) as exc2:
        update_tariff(db_session, CAR, -5, 30, 20, 200, user=admin)
    assert exc2.value.status_code == 422

    # Negative hourly fee
    with pytest.raises(ApiError) as exc3:
        update_tariff(db_session, CAR, 10, -10, 20, 200, user=admin)
    assert exc3.value.status_code == 422

    # Daily cap less than first hour fee
    with pytest.raises(ApiError) as exc4:
        update_tariff(db_session, CAR, 10, 50, 20, 30, user=admin)
    assert exc4.value.status_code == 422


def test_create_new_tariff_record(db_session):
    admin = get_user_by_role(db_session, ROLE_ADMIN)

    # Delete ACCESSIBLE tariff so we can test inserting a brand new tariff record
    existing = db_session.get(Tariff, ACCESSIBLE)
    if existing:
        db_session.delete(existing)
        db_session.commit()

    created = update_tariff(
        db=db_session,
        vehicle_type=ACCESSIBLE,
        grace_minutes=12,
        first_hour_fee=18,
        extra_hour_fee=12,
        daily_cap=120,
        user=admin,
    )
    assert created["vehicleType"] == ACCESSIBLE
    assert created["graceMinutes"] == 12


# ==============================================================================
# Zone and Slot Capacity Configuration Tests
# ==============================================================================

def test_shrink_zone_slots_and_occupied_protection(db_session):
    admin = get_user_by_role(db_session, ROLE_ADMIN)

    # Shrink EV zone from 5 to 4
    res = configure_zone_slots(db_session, "L1-EV", 4, user=admin)
    assert res["totalSlots"] == 4
    assert res["freeSlots"] == 4

    # Occupy 2 slots in EV zone
    slot1 = db_session.get(Slot, "E-001")
    slot2 = db_session.get(Slot, "E-002")
    slot1.status = SLOT_OCCUPIED
    slot2.status = SLOT_OCCUPIED
    db_session.commit()

    # Attempt to shrink zone to 1 (which is less than the 2 occupied slots) -> 409 Conflict
    with pytest.raises(ApiError) as exc_info:
        configure_zone_slots(db_session, "L1-EV", 1, user=admin)
    assert exc_info.value.status_code == 409
    assert exc_info.value.code == "CANNOT_SHRINK_OCCUPIED_SLOTS"

    # Clean up slot status
    slot1.status = "FREE"
    slot2.status = "FREE"
    db_session.commit()


def test_configure_zone_slots_errors(db_session):
    admin = get_user_by_role(db_session, ROLE_ADMIN)

    # Non-existent zone
    with pytest.raises(ApiError) as exc1:
        configure_zone_slots(db_session, "ZONE_UNKNOWN", 10, user=admin)
    assert exc1.value.status_code == 404
    assert exc1.value.code == "ZONE_NOT_FOUND"

    # Negative slot count
    with pytest.raises(ApiError) as exc2:
        configure_zone_slots(db_session, "L1-CAR", -5, user=admin)
    assert exc2.value.status_code == 422


def test_create_zone_and_list_overview(db_session):
    admin = get_user_by_role(db_session, ROLE_ADMIN)

    # 1. Create a new zone
    new_zone = create_zone(db_session, name="L2-EV-FAST", vehicle_type=EV, user=admin)
    assert new_zone["name"] == "L2-EV-FAST"
    assert new_zone["vehicleType"] == EV

    # 2. Add slots to the new zone
    slots_res = configure_zone_slots(db_session, "L2-EV-FAST", 8, user=admin)
    assert slots_res["totalSlots"] == 8
    assert slots_res["freeSlots"] == 8

    # 3. Duplicate zone name rejected
    with pytest.raises(ApiError) as exc_dup:
        create_zone(db_session, name="L2-EV-FAST", vehicle_type=EV, user=admin)
    assert exc_dup.value.status_code == 409
    assert exc_dup.value.code == "ZONE_ALREADY_EXISTS"

    # 4. Invalid zone validations (name too short, invalid type)
    with pytest.raises(ApiError) as exc_name:
        create_zone(db_session, name="x", vehicle_type=EV, user=admin)
    assert exc_name.value.status_code == 422

    with pytest.raises(ApiError) as exc_type:
        create_zone(db_session, name="L2-ROCKET", vehicle_type="rocket", user=admin)
    assert exc_type.value.status_code == 422

    # 5. List zones overview
    overview = list_zones_overview(db_session)
    zone_names = [z["name"] for z in overview]
    assert "L2-EV-FAST" in zone_names


def test_list_and_get_tariffs(db_session):
    all_tariffs = list_tariffs(db_session)
    types = [t["vehicleType"] for t in all_tariffs]
    assert CAR in types
    assert TWO_WHEELER in types
    assert EV in types

    # Non-existent tariff
    with pytest.raises(ApiError) as exc:
        get_tariff(db_session, "submarine")
    assert exc.value.status_code == 404
