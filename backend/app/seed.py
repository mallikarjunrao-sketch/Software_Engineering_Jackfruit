import os

from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.constants import ACCESSIBLE, CAR, EV, ROLE_ADMIN, ROLE_ATTENDANT, TWO_WHEELER
from backend.app.models import Slot, Tariff, User, Zone
from backend.app.security import hash_password

ZONES = [
    ("L1-CAR", CAR, "C", 20),
    ("L1-BIKE", TWO_WHEELER, "B", 20),
    ("L1-EV", EV, "E", 5),
    ("L1-ACC", ACCESSIBLE, "A", 5),
]

TARIFFS = [
    (CAR, 10, 30, 20, 200),
    (TWO_WHEELER, 10, 10, 5, 60),
    (EV, 10, 40, 25, 250),
    (ACCESSIBLE, 10, 15, 10, 100),
]


def seed_database(db: Session):
    if db.scalar(select(Zone.id).limit(1)) is not None:
        return
    for name, vehicle_type, prefix, count in ZONES:
        zone = Zone(name=name, vehicle_type=vehicle_type)
        db.add(zone)
        db.flush()
        for number in range(1, count + 1):
            db.add(Slot(id=f"{prefix}-{number:03d}", zone_id=zone.id, slot_type=vehicle_type, distance_from_gate=number * 5))
    for vehicle_type, grace, first_hour, extra_hour, cap in TARIFFS:
        db.add(Tariff(vehicle_type=vehicle_type, grace_minutes=grace, first_hour_fee=first_hour, extra_hour_fee=extra_hour, daily_cap=cap))
    db.add(User(username="admin", password_hash=hash_password(os.getenv("SEED_ADMIN_PASSWORD", "admin123")), role=ROLE_ADMIN))
    db.add(User(username="attendant", password_hash=hash_password(os.getenv("SEED_ATTENDANT_PASSWORD", "attendant123")), role=ROLE_ATTENDANT))
    db.commit()
