from fastapi import APIRouter

from backend.app.errors import ApiError
from backend.app.schemas import AnprRequest, AnprResponse, GatewayRequest, GatewayResponse
from simulators import anpr, gateway

router = APIRouter(tags=["simulators"])


@router.post("/anpr/recognise", response_model=AnprResponse)
def recognise_plate(payload: AnprRequest):
    try:
        plate, confidence = anpr.recognise(payload.imageRef)
    except anpr.UnreadableImage:
        raise ApiError(422, "UNREADABLE_IMAGE", "The number plate could not be read") from None
    return AnprResponse(plate=plate, confidence=confidence)


@router.post("/gateway/pay", response_model=GatewayResponse)
def gateway_pay(payload: GatewayRequest):
    try:
        status, txn_ref = gateway.pay(payload.amount, payload.mode, payload.simulate)
    except gateway.GatewayTimeout:
        raise ApiError(504, "GATEWAY_TIMEOUT", "The payment gateway did not respond") from None
    return GatewayResponse(status=status, txnRef=txn_ref)
