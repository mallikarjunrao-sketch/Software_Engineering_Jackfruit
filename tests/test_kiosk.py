def test_kiosk_page_is_served(client):
    response = client.get("/kiosk")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    body = response.text
    assert "Vehicle entry" in body
    assert "Vehicle exit" in body
    assert "Gate" in body


def test_kiosk_entry_endpoint_used_by_ui(client):
    response = client.post(
        "/api/v1/entries", json={"plate": "KA01AB1234", "vehicleType": "car"}
    )
    assert response.status_code == 201
    assert response.json()["ticketNo"].startswith("TKT-")


def test_kiosk_duplicate_entry_is_denied(client):
    payload = {"plate": "KA01AB1234", "vehicleType": "car"}
    client.post("/api/v1/entries", json=payload)
    response = client.post("/api/v1/entries", json=payload)
    assert response.status_code == 409
    assert response.json()["code"] == "DUPLICATE_ACTIVE_ENTRY"


def test_kiosk_low_confidence_image_asks_for_manual_plate(client):
    response = client.post(
        "/api/v1/entries",
        json={"imageRef": "cam_KA01AB1234_lowconf.jpg", "vehicleType": "car"},
    )
    assert response.status_code == 422
    assert response.json()["code"] == "LOW_CONFIDENCE"


def test_kiosk_exit_returns_amount_due(client):
    client.post("/api/v1/entries", json={"plate": "KA01AB1234", "vehicleType": "car"})
    response = client.post("/api/v1/exits", json={"plate": "KA01AB1234"})
    assert response.status_code == 200
    body = response.json()
    assert {"sessionId", "amountDue", "status"} <= body.keys()


def test_kiosk_exit_unknown_vehicle_is_not_found(client):
    response = client.post("/api/v1/exits", json={"plate": "KA09ZZ9999"})
    assert response.status_code == 404
    assert response.json()["code"] == "SESSION_NOT_FOUND"
