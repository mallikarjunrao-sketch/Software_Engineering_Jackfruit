from sqlalchemy import func, select

from backend.app.models import Slot, Tariff, User, Zone
from backend.app.security import hash_password, verify_password
from backend.app.seed import seed_database


def test_seed_creates_zones_slots_tariffs_and_users(db_session):
    assert db_session.scalar(select(func.count(Zone.id))) == 4
    assert db_session.scalar(select(func.count(Slot.id))) == 50
    assert db_session.scalar(select(func.count(Tariff.vehicle_type))) == 4
    roles = set(db_session.scalars(select(User.role)))
    assert roles == {"ADMIN", "ATTENDANT"}


def test_seed_is_idempotent(db_session):
    seed_database(db_session)
    assert db_session.scalar(select(func.count(Slot.id))) == 50


def test_password_hash_is_salted_and_verifiable():
    first = hash_password("secret")
    second = hash_password("secret")
    assert first != second
    assert verify_password("secret", first)
    assert not verify_password("other", first)
