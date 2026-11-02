from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.constants import (
    ROLE_ADMIN,
    SLOT_FREE,
    VEHICLE_TYPES,
)
from backend.app.errors import ApiError
from backend.app.models import AuditLog, Slot, Tariff, User, Zone


def update_tariff(
    db: Session,
    vehicle_type: str,
    grace_minutes: int,
    first_hour_fee: int,
    extra_hour_fee: int,
    daily_cap: int,
    user: User | None = None,
    user_id: int | None = None,
    user_role: str | None = None,
) -> dict:
    """Configure or update tariff pricing slabs for a vehicle type (APMS-F-011 / SAD Table 13).

    Rules:
    - Admin-only operation (APMS-SR-003). Attendant or unauthenticated callers are rejected.
    - vehicle_type must be valid ('car', 'two_wheeler', 'ev', 'accessible').
    - Non-negative fees and grace minutes required.
    - daily_cap cannot be less than first_hour_fee.
    - Appends an audit entry to the audit log (APMS-SR-004).
    - Changes take immediate effect for new sessions without restart (AC-F-011 / TC-BIL-02).
    """
    effective_user_id = user.id if user else user_id
    effective_role = user.role if user else user_role

    if effective_user_id is None or effective_role is None:
        raise ApiError(401, "UNAUTHORIZED", "Authentication required to configure tariffs")

    if effective_role != ROLE_ADMIN:
        db.add(
            AuditLog(
                user_id=effective_user_id,
                action="ACCESS_DENIED",
                details=f"update_tariff vehicle_type={vehicle_type} role={effective_role} needs=ADMIN",
            )
        )
        db.commit()
        raise ApiError(403, "FORBIDDEN", "Only administrators can configure tariffs")

    if vehicle_type not in VEHICLE_TYPES:
        raise ApiError(
            422,
            "INVALID_TARIFF",
            f"Invalid vehicle type '{vehicle_type}'. Must be one of {VEHICLE_TYPES}",
        )

    if grace_minutes < 0:
        raise ApiError(422, "INVALID_TARIFF", "Grace minutes cannot be negative")

    if first_hour_fee < 0 or extra_hour_fee < 0:
        raise ApiError(422, "INVALID_TARIFF", "Hourly fees cannot be negative")

    if daily_cap < first_hour_fee:
        raise ApiError(
            422,
            "INVALID_TARIFF",
            "Daily cap cannot be less than the first hour fee",
        )

    tariff = db.get(Tariff, vehicle_type)
    if tariff is None:
        tariff = Tariff(
            vehicle_type=vehicle_type,
            grace_minutes=grace_minutes,
            first_hour_fee=first_hour_fee,
            extra_hour_fee=extra_hour_fee,
            daily_cap=daily_cap,
        )
        db.add(tariff)
    else:
        tariff.grace_minutes = grace_minutes
        tariff.first_hour_fee = first_hour_fee
        tariff.extra_hour_fee = extra_hour_fee
        tariff.daily_cap = daily_cap

    # Append audit log entry (APMS-SR-004)
    audit = AuditLog(
        user_id=effective_user_id,
        action="TARIFF_UPDATE",
        details=(
            f"vehicle_type={vehicle_type} grace_minutes={grace_minutes} "
            f"first_hour={first_hour_fee} extra_hour={extra_hour_fee} daily_cap={daily_cap}"
        ),
    )
    db.add(audit)

    db.commit()
    db.refresh(tariff)

    return {
        "vehicleType": tariff.vehicle_type,
        "graceMinutes": tariff.grace_minutes,
        "firstHourFee": tariff.first_hour_fee,
        "extraHourFee": tariff.extra_hour_fee,
        "dailyCap": tariff.daily_cap,
    }


def get_tariff(db: Session, vehicle_type: str) -> dict:
    """Retrieve the current tariff configuration for a vehicle type."""
    tariff = db.get(Tariff, vehicle_type)
    if not tariff:
        raise ApiError(404, "TARIFF_NOT_FOUND", f"Tariff for vehicle type '{vehicle_type}' not found")

    return {
        "vehicleType": tariff.vehicle_type,
        "graceMinutes": tariff.grace_minutes,
        "firstHourFee": tariff.first_hour_fee,
        "extraHourFee": tariff.extra_hour_fee,
        "dailyCap": tariff.daily_cap,
    }


def list_tariffs(db: Session) -> list[dict]:
    """List all configured tariffs across vehicle types."""
    tariffs = db.scalars(select(Tariff).order_by(Tariff.vehicle_type)).all()
    return [
        {
            "vehicleType": t.vehicle_type,
            "graceMinutes": t.grace_minutes,
            "firstHourFee": t.first_hour_fee,
            "extraHourFee": t.extra_hour_fee,
            "dailyCap": t.daily_cap,
        }
        for t in tariffs
    ]


def configure_zone_slots(
    db: Session,
    zone_name: str,
    target_count: int,
    user: User | None = None,
    user_id: int | None = None,
    user_role: str | None = None,
) -> dict:
    """Configure slot capacity for a zone (APMS-F-011 / TC-BIL-02).

    Rules:
    - Admin-only operation.
    - zone must exist.
    - target_count must be non-negative.
    - Cannot shrink zone below the number of currently occupied slots.
    - Appends an audit entry and updates capacity immediately without restart.
    """
    effective_user_id = user.id if user else user_id
    effective_role = user.role if user else user_role

    if effective_user_id is None or effective_role is None:
        raise ApiError(401, "UNAUTHORIZED", "Authentication required to configure zone slots")

    if effective_role != ROLE_ADMIN:
        db.add(
            AuditLog(
                user_id=effective_user_id,
                action="ACCESS_DENIED",
                details=f"configure_zone_slots zone={zone_name} role={effective_role} needs=ADMIN",
            )
        )
        db.commit()
        raise ApiError(403, "FORBIDDEN", "Only administrators can configure zone slots")

    if target_count < 0:
        raise ApiError(422, "INVALID_SLOT_COUNT", "Slot count cannot be negative")

    zone = db.scalar(select(Zone).where(Zone.name == zone_name))
    if not zone:
        raise ApiError(404, "ZONE_NOT_FOUND", f"Zone '{zone_name}' not found")

    existing_slots = db.scalars(
        select(Slot).where(Slot.zone_id == zone.id).order_by(Slot.id)
    ).all()
    current_count = len(existing_slots)

    if target_count > current_count:
        prefix = existing_slots[0].id.split("-")[0] if existing_slots else zone.name[0].upper()
        for num in range(current_count + 1, target_count + 1):
            db.add(
                Slot(
                    id=f"{prefix}-{num:03d}",
                    zone_id=zone.id,
                    slot_type=zone.vehicle_type,
                    distance_from_gate=num * 5,
                    status=SLOT_FREE,
                )
            )
    elif target_count < current_count:
        occupied = [s for s in existing_slots if s.status != SLOT_FREE]
        if target_count < len(occupied):
            raise ApiError(
                409,
                "CANNOT_SHRINK_OCCUPIED_SLOTS",
                f"Cannot shrink zone '{zone_name}' to {target_count} slots because {len(occupied)} slots are currently occupied",
            )
        free_slots = [s for s in existing_slots if s.status == SLOT_FREE]
        remove_count = current_count - target_count
        to_delete = free_slots[-remove_count:]
        for s in to_delete:
            db.delete(s)

    audit = AuditLog(
        user_id=effective_user_id,
        action="ZONE_SLOTS_UPDATE",
        details=f"zone={zone_name} from={current_count} to={target_count}",
    )
    db.add(audit)

    db.commit()

    updated_slots = db.scalars(
        select(Slot).where(Slot.zone_id == zone.id)
    ).all()
    free_count = sum(1 for s in updated_slots if s.status == SLOT_FREE)

    return {
        "zone": zone.name,
        "vehicleType": zone.vehicle_type,
        "totalSlots": len(updated_slots),
        "freeSlots": free_count,
    }


def create_zone(
    db: Session,
    name: str,
    vehicle_type: str,
    user: User | None = None,
    user_id: int | None = None,
    user_role: str | None = None,
) -> dict:
    """Create a new parking zone."""
    effective_user_id = user.id if user else user_id
    effective_role = user.role if user else user_role

    if effective_user_id is None or effective_role is None:
        raise ApiError(401, "UNAUTHORIZED", "Authentication required to create zones")

    if effective_role != ROLE_ADMIN:
        db.add(
            AuditLog(
                user_id=effective_user_id,
                action="ACCESS_DENIED",
                details=f"create_zone name={name} role={effective_role} needs=ADMIN",
            )
        )
        db.commit()
        raise ApiError(403, "FORBIDDEN", "Only administrators can create zones")

    if not name or len(name.strip()) < 2:
        raise ApiError(422, "INVALID_ZONE", "Zone name must be at least 2 characters")

    if vehicle_type not in VEHICLE_TYPES:
        raise ApiError(422, "INVALID_ZONE", f"Vehicle type must be one of {VEHICLE_TYPES}")

    clean_name = name.strip()
    existing = db.scalar(select(Zone.id).where(Zone.name == clean_name))
    if existing:
        raise ApiError(409, "ZONE_ALREADY_EXISTS", f"Zone '{clean_name}' already exists")

    zone = Zone(name=clean_name, vehicle_type=vehicle_type)
    db.add(zone)

    audit = AuditLog(
        user_id=effective_user_id,
        action="ZONE_CREATE",
        details=f"zone={clean_name} vehicle_type={vehicle_type}",
    )
    db.add(audit)

    db.commit()
    db.refresh(zone)

    return {
        "id": zone.id,
        "name": zone.name,
        "vehicleType": zone.vehicle_type,
        "totalSlots": 0,
    }


def list_zones_overview(db: Session) -> list[dict]:
    """List all zones with total and free slot metrics."""
    zones = db.scalars(select(Zone).order_by(Zone.id)).all()
    overview = []
    for z in zones:
        slots = db.scalars(select(Slot).where(Slot.zone_id == z.id)).all()
        free_count = sum(1 for s in slots if s.status == SLOT_FREE)
        overview.append(
            {
                "id": z.id,
                "name": z.name,
                "vehicleType": z.vehicle_type,
                "totalSlots": len(slots),
                "freeSlots": free_count,
            }
        )
    return overview
