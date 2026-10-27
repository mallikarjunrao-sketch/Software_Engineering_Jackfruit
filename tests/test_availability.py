def test_availability_counts_all_types(client):
    response = client.get("/api/v1/availability")
    assert response.status_code == 200
    by_type = response.json()["byType"]
    assert by_type["car"] == {"total": 20, "free": 20}
    assert by_type["two_wheeler"] == {"total": 20, "free": 20}
    assert by_type["ev"] == {"total": 5, "free": 5}
    assert by_type["accessible"] == {"total": 5, "free": 5}


def test_availability_filters_by_zone(client):
    response = client.get("/api/v1/availability", params={"zone": "L1-EV"})
    assert response.status_code == 200
    assert list(response.json()["byType"]) == ["ev"]


def test_availability_unknown_zone(client):
    response = client.get("/api/v1/availability", params={"zone": "NOPE"})
    assert response.status_code == 404
    assert response.json()["code"] == "ZONE_NOT_FOUND"
