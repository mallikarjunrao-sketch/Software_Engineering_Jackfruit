import pytest
from sqlalchemy import select

from backend.app.auth import create_token
from backend.app.models import AuditLog, Tariff, User
from backend.app.routers.tariffs import TARIFF_UPDATED

NEW_CAR_TARIFF = {"graceMinutes": 0, "firstHourFee": 30, "extraHourFee": 20, "dailyCap": 200}


def headers_for(db, username):
    user = db.scalar(select(User).where(User.username == username))
    return {"Authorization": "Bearer " + create_token(user)}


@pytest.fixture
def admin(db_session):
    return headers_for(db_session, "admin")


@pytest.fixture
def attendant(db_session):
    return headers_for(db_session, "attendant")


def test_admin_can_list_all_tariffs(client, admin):
    response = client.get("/api/v1/admin/tariffs", headers=admin)
    assert response.status_code == 200
    by_type = {item["vehicleType"]: item for item in response.json()}
    assert set(by_type) == {"car", "two_wheeler", "ev", "accessible"}
    assert by_type["car"] == {"vehicleType": "car", "graceMinutes": 10, "firstHourFee": 30, "extraHourFee": 20, "dailyCap": 200}


def test_admin_can_update_a_tariff(client, admin, db_session):
    response = client.put("/api/v1/admin/tariffs/car", json=NEW_CAR_TARIFF, headers=admin)
    assert response.status_code == 200
    assert response.json() == {"vehicleType": "car", **NEW_CAR_TARIFF}
    db_session.expire_all()
    tariff = db_session.get(Tariff, "car")
    assert (tariff.grace_minutes, tariff.first_hour_fee, tariff.extra_hour_fee, tariff.daily_cap) == (0, 30, 20, 200)


def test_update_is_visible_to_the_next_read_without_restart(client, admin):
    client.put("/api/v1/admin/tariffs/ev", json={"graceMinutes": 5, "firstHourFee": 50, "extraHourFee": 30, "dailyCap": 300}, headers=admin)
    listed = {item["vehicleType"]: item for item in client.get("/api/v1/admin/tariffs", headers=admin).json()}
    assert listed["ev"]["graceMinutes"] == 5
    assert listed["ev"]["dailyCap"] == 300
    assert listed["car"]["graceMinutes"] == 10


def test_update_is_written_to_the_audit_log(client, admin, db_session):
    client.put("/api/v1/admin/tariffs/car", json=NEW_CAR_TARIFF, headers=admin)
    entry = db_session.scalars(select(AuditLog).where(AuditLog.action == TARIFF_UPDATED)).one()
    admin_user = db_session.scalar(select(User).where(User.username == "admin"))
    assert entry.user_id == admin_user.id
    assert "car" in entry.details and "grace 10" in entry.details and "grace 0" in entry.details


def test_attendant_cannot_change_or_read_tariffs(client, attendant, db_session):
    assert client.put("/api/v1/admin/tariffs/car", json=NEW_CAR_TARIFF, headers=attendant).status_code == 403
    assert client.get("/api/v1/admin/tariffs", headers=attendant).status_code == 403
    assert db_session.get(Tariff, "car").grace_minutes == 10


def test_anonymous_requests_are_rejected(client):
    assert client.put("/api/v1/admin/tariffs/car", json=NEW_CAR_TARIFF).status_code == 401
    assert client.get("/api/v1/admin/tariffs").status_code == 401


def test_unknown_vehicle_type_is_not_found(client, admin):
    response = client.put("/api/v1/admin/tariffs/bus", json=NEW_CAR_TARIFF, headers=admin)
    assert response.status_code == 404
    assert response.json()["code"] == "TARIFF_NOT_FOUND"


def test_cap_below_first_hour_fee_is_rejected_and_nothing_changes(client, admin, db_session):
    body = {**NEW_CAR_TARIFF, "firstHourFee": 100, "dailyCap": 50}
    response = client.put("/api/v1/admin/tariffs/car", json=body, headers=admin)
    assert response.status_code == 422
    assert response.json()["code"] == "INVALID_TARIFF"
    db_session.expire_all()
    assert db_session.get(Tariff, "car").first_hour_fee == 30


@pytest.mark.parametrize(
    "body",
    [
        {**NEW_CAR_TARIFF, "graceMinutes": -1},
        {**NEW_CAR_TARIFF, "firstHourFee": -5},
        {**NEW_CAR_TARIFF, "extraHourFee": "free"},
        {"graceMinutes": 0, "firstHourFee": 30},
    ],
)
def test_invalid_numbers_and_missing_fields_are_rejected(client, admin, body):
    assert client.put("/api/v1/admin/tariffs/car", json=body, headers=admin).status_code == 422
