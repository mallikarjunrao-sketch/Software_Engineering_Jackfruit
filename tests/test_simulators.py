import pytest

from simulators import anpr, gateway


@pytest.mark.parametrize(
    "image_ref, plate, confidence",
    [
        ("KA01AB1234.jpg", "KA01AB1234", 0.97),
        ("ka05cd5678_lowconf.png", "KA05CD5678", 0.6),
    ],
)
def test_anpr_reads_plate(image_ref, plate, confidence):
    assert anpr.recognise(image_ref) == (plate, confidence)


@pytest.mark.parametrize("image_ref", ["unreadable_01.jpg", "blurry.jpg"])
def test_anpr_rejects_unreadable_images(image_ref):
    with pytest.raises(anpr.UnreadableImage):
        anpr.recognise(image_ref)


def test_gateway_outcomes():
    status, txn_ref = gateway.pay(100, "UPI")
    assert status == gateway.SUCCESS and txn_ref.startswith("UPI-")
    assert gateway.pay(100, "CARD", "failure") == (gateway.FAILED, None)
    with pytest.raises(gateway.GatewayTimeout):
        gateway.pay(100, "CASH", "timeout")


def test_anpr_endpoint(client):
    ok = client.post("/anpr/recognise", json={"imageRef": "KA01AB1234.jpg"})
    assert ok.status_code == 200
    assert ok.json() == {"plate": "KA01AB1234", "confidence": 0.97}
    bad = client.post("/anpr/recognise", json={"imageRef": "unreadable.jpg"})
    assert bad.status_code == 422
    assert bad.json()["code"] == "UNREADABLE_IMAGE"


def test_gateway_endpoint(client):
    body = {"sessionId": 1, "mode": "UPI", "amount": 50}
    assert client.post("/gateway/pay", json=body).json()["status"] == "SUCCESS"
    assert client.post("/gateway/pay", json={**body, "simulate": "failure"}).json()["status"] == "FAILED"
    timeout = client.post("/gateway/pay", json={**body, "simulate": "timeout"})
    assert timeout.status_code == 504
    assert timeout.json()["code"] == "GATEWAY_TIMEOUT"
