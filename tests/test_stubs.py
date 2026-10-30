import pytest

CASES = [
    ("post", "/api/v1/exits/1/authorise", None),
    ("post", "/api/v1/exits/1/override", {"reason": "lost ticket"}),
    ("get", "/api/v1/sessions/1/fee", None),
    ("post", "/api/v1/payments", {"sessionId": 1, "mode": "UPI", "amount": 50}),
]


@pytest.mark.parametrize("method, url, body", CASES)
def test_unimplemented_endpoints_return_501(client, method, url, body):
    response = getattr(client, method)(url, json=body) if body is not None else getattr(client, method)(url)
    assert response.status_code == 501
    assert response.json()["code"] == "NOT_IMPLEMENTED"
