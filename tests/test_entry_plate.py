import pytest

from backend.app.errors import ApiError
from backend.app.routers.parking import resolve_plate
from backend.app.schemas import EntryRequest


def req(**kw):
    return EntryRequest(vehicleType="car", **kw)


def test_manual_plate_is_cleaned_up():
    assert resolve_plate(req(plate="ka 01 ab 1234")) == "KA01AB1234"


def test_good_image_is_read():
    assert resolve_plate(req(imageRef="cam1_KA01AB1234.jpg")) == "KA01AB1234"


def test_low_confidence_image_triggers_manual_fallback():
    with pytest.raises(ApiError) as e:
        resolve_plate(req(imageRef="cam1_KA01AB1234_lowconf.jpg"))
    assert (e.value.status_code, e.value.code) == (422, "LOW_CONFIDENCE")


def test_unreadable_image():
    with pytest.raises(ApiError) as e:
        resolve_plate(req(imageRef="blurry_unreadable.jpg"))
    assert (e.value.status_code, e.value.code) == (422, "UNREADABLE_IMAGE")


def test_invalid_plate_format():
    with pytest.raises(ApiError) as e:
        resolve_plate(req(plate="12345"))
    assert (e.value.status_code, e.value.code) == (422, "INVALID_PLATE")


def test_plate_or_image_required():
    with pytest.raises(ApiError) as e:
        resolve_plate(req())
    assert (e.value.status_code, e.value.code) == (422, "PLATE_REQUIRED")


def test_endpoint_returns_422_for_low_confidence(client):
    response = client.post("/api/v1/entries", json={"imageRef": "x_KA01AB1234_lowconf.jpg", "vehicleType": "car"})
    assert response.status_code == 422
    assert response.json()["code"] == "LOW_CONFIDENCE"
