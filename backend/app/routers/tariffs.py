from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.orm import Session

from backend.app.auth import require_admin
from backend.app.database import get_db
from backend.app.errors import ApiError
from backend.app.models import Tariff, User
from backend.app.services import audit

TARIFF_UPDATED = "TARIFF_UPDATED"

router = APIRouter(prefix="/api/v1/admin/tariffs", tags=["admin"])


class TariffBody(BaseModel):
    graceMinutes: int = Field(ge=0, le=1440)
    firstHourFee: int = Field(ge=0, le=100000)
    extraHourFee: int = Field(ge=0, le=100000)
    dailyCap: int = Field(ge=0, le=1000000)


class TariffResponse(TariffBody):
    vehicleType: str


def to_response(tariff: Tariff):
    return TariffResponse(
        vehicleType=tariff.vehicle_type,
        graceMinutes=tariff.grace_minutes,
        firstHourFee=tariff.first_hour_fee,
        extraHourFee=tariff.extra_hour_fee,
        dailyCap=tariff.daily_cap,
    )


def describe(tariff: Tariff):
    return f"grace {tariff.grace_minutes}, first {tariff.first_hour_fee}, extra {tariff.extra_hour_fee}, cap {tariff.daily_cap}"


@router.get("", response_model=list[TariffResponse])
def list_tariffs(db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    return [to_response(tariff) for tariff in db.scalars(select(Tariff).order_by(Tariff.vehicle_type))]


@router.put("/{vehicle_type}", response_model=TariffResponse)
def update_tariff(vehicle_type: str, payload: TariffBody, db: Session = Depends(get_db), admin: User = Depends(require_admin)):
    tariff = db.get(Tariff, vehicle_type)
    if tariff is None:
        raise ApiError(404, "TARIFF_NOT_FOUND", "No tariff exists for this vehicle type")
    if payload.dailyCap < payload.firstHourFee:
        raise ApiError(422, "INVALID_TARIFF", "The daily cap cannot be lower than the first hour fee")
    before = describe(tariff)
    tariff.grace_minutes = payload.graceMinutes
    tariff.first_hour_fee = payload.firstHourFee
    tariff.extra_hour_fee = payload.extraHourFee
    tariff.daily_cap = payload.dailyCap
    db.commit()
    audit.record(db, TARIFF_UPDATED, admin.id, f"{vehicle_type}: {before} -> {describe(tariff)}")
    return to_response(tariff)
