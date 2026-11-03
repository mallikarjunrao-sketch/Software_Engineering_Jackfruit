import pytest
from backend.app.schemas import PaymentRequest


@pytest.mark.parametrize(
    "plate",
    [
        "KA01AB1234 OR 1=1",
        "KA01AB1234; DROP TABLE users",
        "' OR '1'='1",
        "<script>alert(1)</script>",
    ],
)
def test_entry_rejects_malformed_or_injection_plate(
    client,
    plate
):

    response = client.post(
        "/api/v1/entries",
        json={
            "plate": plate,
            "vehicleType": "car"
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "amount",
    [
        0,
        -1,
        1_000_001,
        "1 OR 1=1",
        "NaN"
    ]
)
def test_payment_amount_is_validated(
    client,
    amount
):

    response = client.post(
        "/api/v1/payments",
        json={
            "sessionId": 1,
            "mode": "UPI",
            "amount": amount
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "username",
    [
        "admin' OR '1'='1",
        "admin;DROP",
        "<script>",
        "a" * 41,
    ]
)
def test_login_rejects_malformed_username(
    client,
    username
):

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": username,
            "password": "admin123"
        },
    )

    assert response.status_code == 422


def test_login_rejects_unexpected_fields(client):

    response = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "admin123",
            "role": "ADMIN"
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "image_ref",
    [
        "",
        "../KA01AB1234.jpg",
        "x; DROP TABLE users",
        "a" * 201,
    ]
)
def test_anpr_rejects_unsafe_image_reference(
    client,
    image_ref
):

    response = client.post(
        "/anpr/recognise",
        json={
            "imageRef": image_ref
        },
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "zone",
    [
        "L1-EV' OR '1'='1",
        "L1-EV;DROP",
        "x" * 41
    ]
)
def test_availability_rejects_unsafe_zone_filter(
    client,
    zone
):

    response = client.get(
        "/api/v1/availability",
        params={
            "zone": zone
        }
    )

    assert response.status_code == 422


@pytest.mark.parametrize(
    "action",
    [
        "LOGIN_SUCCESS OR 1=1",
        "LOGIN_SUCCESS;DROP",
        "x" * 41
    ]
)
def test_audit_search_rejects_unsafe_action_filter(
    client,
    action
):

    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "admin123"
        }
    )

    response = client.get(
        "/api/v1/admin/audit",
        params={
            "action": action
        },
        headers={
            "Authorization": f"Bearer {login.json()['token']}"
        },
    )

    assert response.status_code == 422


def test_report_date_rejects_injection_string(client):

    login = client.post(
        "/api/v1/auth/login",
        json={
            "username": "admin",
            "password": "admin123"
        }
    )

    response = client.get(
        "/api/v1/reports/revenue",
        params={
            "from": "2026-01-01' OR 1=1 --"
        },
        headers={
            "Authorization": f"Bearer {login.json()['token']}"
        },
    )

    assert response.status_code == 422




def test_valid_payment_boundary_is_accepted_by_schema():
    payload = PaymentRequest(
        sessionId=1,
        mode="UPI",
        amount=1_000_000,
    )

    assert payload.amount == 1_000_000