from datetime import datetime, timezone

from sqlalchemy import DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from backend.app.constants import SESSION_ACTIVE, SLOT_FREE
from backend.app.database import Base


def utcnow():
    return datetime.now(timezone.utc).replace(tzinfo=None)


class Zone(Base):
    __tablename__ = "zones"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(40), unique=True)
    vehicle_type: Mapped[str] = mapped_column(String(20))

    slots: Mapped[list["Slot"]] = relationship(back_populates="zone")


class Slot(Base):
    __tablename__ = "slots"

    id: Mapped[str] = mapped_column(String(20), primary_key=True)
    zone_id: Mapped[int] = mapped_column(ForeignKey("zones.id"))
    slot_type: Mapped[str] = mapped_column(String(20))
    distance_from_gate: Mapped[int] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(10), default=SLOT_FREE)

    zone: Mapped[Zone] = relationship(back_populates="slots")


class Vehicle(Base):
    __tablename__ = "vehicles"

    plate: Mapped[str] = mapped_column(String(15), primary_key=True)
    vehicle_type: Mapped[str] = mapped_column(String(20))


class ParkingSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(primary_key=True)
    plate: Mapped[str] = mapped_column(ForeignKey("vehicles.plate"))
    slot_id: Mapped[str] = mapped_column(ForeignKey("slots.id"))
    entry_time: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
    exit_time: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(10), default=SESSION_ACTIVE)
    fee: Mapped[int | None] = mapped_column(Integer, nullable=True)
    override_reason: Mapped[str | None] = mapped_column(Text, nullable=True)

    payments: Mapped[list["Payment"]] = relationship(back_populates="session")


class Payment(Base):
    __tablename__ = "payments"

    id: Mapped[int] = mapped_column(primary_key=True)
    session_id: Mapped[int] = mapped_column(ForeignKey("sessions.id"))
    amount: Mapped[int] = mapped_column(Integer)
    mode: Mapped[str] = mapped_column(String(10))
    status: Mapped[str] = mapped_column(String(10))
    txn_ref: Mapped[str | None] = mapped_column(String(40), nullable=True)
    masked_ref: Mapped[str | None] = mapped_column(String(20), nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=utcnow)

    session: Mapped[ParkingSession] = relationship(back_populates="payments")


class Tariff(Base):
    __tablename__ = "tariffs"

    vehicle_type: Mapped[str] = mapped_column(String(20), primary_key=True)
    grace_minutes: Mapped[int] = mapped_column(Integer)
    first_hour_fee: Mapped[int] = mapped_column(Integer)
    extra_hour_fee: Mapped[int] = mapped_column(Integer)
    daily_cap: Mapped[int] = mapped_column(Integer)


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(40), unique=True)
    password_hash: Mapped[str] = mapped_column(String(100))
    role: Mapped[str] = mapped_column(String(10))
    failed_logins: Mapped[int] = mapped_column(Integer, default=0)
    locked_until: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"), nullable=True)
    action: Mapped[str] = mapped_column(String(40))
    details: Mapped[str] = mapped_column(Text, default="")
    timestamp: Mapped[datetime] = mapped_column(DateTime, default=utcnow)
