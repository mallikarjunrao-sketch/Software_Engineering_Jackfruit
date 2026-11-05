import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, select

from backend.app.constants import CAR
from backend.app.database import Base, SessionLocal, engine
from backend.app.models import Slot, Zone
from backend.app.seed import seed_database


def main():
    parser = argparse.ArgumentParser(description="Add car slots so load tests do not run out of space")
    parser.add_argument("--car-slots", type=int, default=500, help="target number of car slots")
    args = parser.parse_args()
    Base.metadata.create_all(bind=engine)
    with SessionLocal() as db:
        seed_database(db)
        zone_id = db.scalar(select(Zone.id).where(Zone.vehicle_type == CAR))
        existing = db.scalar(select(func.count(Slot.id)).where(Slot.slot_type == CAR))
        for number in range(existing + 1, args.car_slots + 1):
            db.add(Slot(id=f"C-{number:03d}", zone_id=zone_id, slot_type=CAR, distance_from_gate=number * 5))
        db.commit()
        total = db.scalar(select(func.count(Slot.id)).where(Slot.slot_type == CAR))
    print(f"Car slots: {total}")


if __name__ == "__main__":
    main()
