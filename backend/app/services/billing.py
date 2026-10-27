import math
from sqlalchemy.orm import Session

from backend.app.constants import CAR
from backend.app.errors import ApiError
from backend.app.models import ParkingSession, Slot, Tariff, Vehicle, utcnow


def calculate_fee(
    duration_minutes: int,
    grace_minutes: int,
    first_hour_fee: int,
    extra_hour_fee: int,
    daily_cap: int,
) -> tuple[int, dict]:
    """Calculate parking fee based on duration and tariff rules (APMS-F-010 / TC-BIL-01).

    Rules:
    - If total duration <= grace_minutes, fee is 0 (free grace period).
    - Duration is billed in full-day cycles (1440 minutes) capped at daily_cap.
    - Within a cycle, billable hours = ceil(minutes / 60).
    - First hour costs first_hour_fee; each additional started hour costs extra_hour_fee.
    - Each single 24-hour cycle cannot exceed daily_cap.
    """
    if duration_minutes < 0:
        duration_minutes = 0

    # Within initial grace period: free
    if duration_minutes <= grace_minutes:
        return 0, {
            "graceApplied": True,
            "graceMinutes": grace_minutes,
            "billableHours": 0,
            "firstHourFee": first_hour_fee,
            "extraHourFee": extra_hour_fee,
            "dailyCap": daily_cap,
            "uncappedFee": 0,
            "capApplied": False,
        }

    full_days = duration_minutes // 1440
    rem_minutes = duration_minutes % 1440

    days_fee = full_days * daily_cap

    if rem_minutes == 0:
        rem_fee = 0
        rem_hours = 0
        rem_uncapped = 0
        rem_capped = False
    else:
        rem_hours = math.ceil(rem_minutes / 60)
        rem_uncapped = first_hour_fee + max(0, rem_hours - 1) * extra_hour_fee
        rem_fee = min(rem_uncapped, daily_cap)
        rem_capped = rem_uncapped > daily_cap

    total_fee = days_fee + rem_fee
    total_billable_hours = (full_days * 24) + rem_hours
    uncapped_total = (full_days * (first_hour_fee + 23 * extra_hour_fee)) + rem_uncapped
    cap_applied = (total_fee < uncapped_total) or rem_capped

    breakdown = {
        "graceApplied": False,
        "graceMinutes": grace_minutes,
        "fullDays": full_days,
        "billableHours": total_billable_hours,
        "firstHourFee": first_hour_fee,
        "extraHourFee": extra_hour_fee,
        "dailyCap": daily_cap,
        "uncappedFee": uncapped_total,
        "capApplied": cap_applied,
    }
    return total_fee, breakdown


def compute_session_fee(session_id: int, db: Session) -> tuple[int, int, dict]:
    """Look up a parking session, determine duration & vehicle tariff, and compute fee.

    Updates the session record with the calculated fee and returns:
    (duration_minutes, amount_due, breakdown)
    """
    session = db.get(ParkingSession, session_id)
    if not session:
        raise ApiError(404, "SESSION_NOT_FOUND", f"Parking session {session_id} not found")

    # Determine vehicle type from Vehicle table or Slot table fallback
    vehicle = db.get(Vehicle, session.plate) if session.plate else None
    if vehicle and vehicle.vehicle_type:
        vehicle_type = vehicle.vehicle_type
    else:
        slot = db.get(Slot, session.slot_id) if session.slot_id else None
        vehicle_type = slot.slot_type if slot else CAR

    tariff = db.get(Tariff, vehicle_type)
    if not tariff:
        raise ApiError(404, "TARIFF_NOT_FOUND", f"Tariff for vehicle type '{vehicle_type}' not found")

    end_time = session.exit_time if session.exit_time is not None else utcnow()
    duration_seconds = max(0, int((end_time - session.entry_time).total_seconds()))
    duration_minutes = duration_seconds // 60

    amount_due, breakdown = calculate_fee(
        duration_minutes=duration_minutes,
        grace_minutes=tariff.grace_minutes,
        first_hour_fee=tariff.first_hour_fee,
        extra_hour_fee=tariff.extra_hour_fee,
        daily_cap=tariff.daily_cap,
    )
    breakdown["vehicleType"] = vehicle_type

    session.fee = amount_due
    db.commit()

    return duration_minutes, amount_due, breakdown
