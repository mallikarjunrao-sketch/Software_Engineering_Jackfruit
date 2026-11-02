from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field


class EntryRequest(BaseModel):
    imageRef: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9_.-]+$"
    )
    plate: str | None = None
    vehicleType: Literal["car", "two_wheeler", "ev", "accessible"]


class EntryResponse(BaseModel):
    sessionId: int
    plate: str
    slotId: str
    entryTime: datetime
    ticketNo: str


class ExitRequest(BaseModel):
    imageRef: str | None = Field(
        default=None,
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9_.-]+$"
    )
    plate: str | None = None


class ExitResponse(BaseModel):
    sessionId: int
    amountDue: int
    status: str


class GateResponse(BaseModel):
    gate: Literal["OPEN", "CLOSED"]
    exitTime: datetime | None = None


class OverrideRequest(BaseModel):
    reason: str = Field(min_length=3)


class FeeResponse(BaseModel):
    sessionId: int
    durationMin: int
    amountDue: int
    breakdown: dict


class PaymentRequest(BaseModel):
    sessionId: int = Field(gt=0)
    mode: Literal["CASH", "CARD", "UPI"]
    amount: int = Field(gt=0, le=1_000_000)


class PaymentResponse(BaseModel):
    paymentId: int
    status: str
    txnRef: str | None = None
    receiptNo: str | None = None


class AvailabilityEntry(BaseModel):
    total: int
    free: int


class AvailabilityResponse(BaseModel):
    zone: str | None
    byType: dict[str, AvailabilityEntry]
    updatedAt: datetime


class AnprRequest(BaseModel):
    imageRef: str = Field(
        min_length=1,
        max_length=200,
        pattern=r"^[A-Za-z0-9_.-]+$"
    )


class AnprResponse(BaseModel):
    plate: str
    confidence: float


class GatewayRequest(BaseModel):
    sessionId: int = Field(gt=0)
    mode: Literal["CASH", "CARD", "UPI"]
    amount: int = Field(gt=0, le=1_000_000)
    simulate: Literal["success", "failure", "timeout"] = "success"


class GatewayResponse(BaseModel):
    status: str
    txnRef: str | None = None