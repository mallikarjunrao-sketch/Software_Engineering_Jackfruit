import pytest
from fastapi import FastAPI, WebSocket
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from backend.app.https_enforcement import (
    HSTS_VALUE,
    HTTPSEnforcementMiddleware,
    https_enforcement_enabled,
)
from backend.app.main import app as real_app


def make_app(enabled=True):
    app = FastAPI()
    app.add_middleware(HTTPSEnforcementMiddleware, enabled=enabled)
    app.state.posts = 0

    @app.get("/ping")
    def ping():
        return {"ok": True}

    @app.post("/data")
    def data():
        app.state.posts += 1
        return {"ok": True}

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_text("hello")
        await websocket.close()

    return app


def http_client(app):
    return TestClient(app, base_url="http://testserver", follow_redirects=False)


def https_client(app):
    return TestClient(app, base_url="https://testserver", follow_redirects=False)


# ---------- TC-SEC-01: plain HTTP is refused or redirected ----------

def test_plain_get_is_redirected_to_https():
    response = http_client(make_app()).get("/ping", params={"x": "1"})
    assert response.status_code == 308
    assert response.headers["location"] == "https://testserver/ping?x=1"


def test_plain_head_is_redirected_to_https():
    response = http_client(make_app()).head("/ping")
    assert response.status_code == 308
    assert response.headers["location"].startswith("https://")


def test_plain_post_is_refused_before_the_endpoint_runs():
    app = make_app()
    response = http_client(app).post("/data", json={"password": "secret"})
    assert response.status_code == 403
    assert response.json()["code"] == "HTTPS_REQUIRED"
    assert app.state.posts == 0


def test_https_request_is_served_with_hsts_header():
    response = https_client(make_app()).get("/ping")
    assert response.status_code == 200
    assert response.headers["strict-transport-security"] == HSTS_VALUE


def test_https_post_is_allowed():
    app = make_app()
    assert https_client(app).post("/data").status_code == 200
    assert app.state.posts == 1


def test_forwarded_proto_https_from_proxy_counts_as_secure():
    response = http_client(make_app()).get("/ping", headers={"X-Forwarded-Proto": "https"})
    assert response.status_code == 200
    assert "strict-transport-security" in response.headers


def test_forwarded_proto_http_from_proxy_is_not_secure():
    response = https_client(make_app()).get("/ping", headers={"X-Forwarded-Proto": "http"})
    assert response.status_code == 308


def test_plain_websocket_is_closed():
    with pytest.raises(WebSocketDisconnect) as error:
        with http_client(make_app()).websocket_connect("/ws"):
            pass
    assert error.value.code == 1008


def test_secure_websocket_works():
    # The test client always reports scheme "ws", so the proxy header marks it as wss.
    with http_client(make_app()).websocket_connect("/ws", headers={"X-Forwarded-Proto": "https"}) as websocket:
        assert websocket.receive_text() == "hello"


def test_enforcement_can_be_switched_off():
    response = http_client(make_app(enabled=False)).get("/ping")
    assert response.status_code == 200
    assert "strict-transport-security" not in response.headers


# ---------- Configuration ----------

@pytest.mark.parametrize(
    ("app_env", "force", "expected"),
    [
        (None, None, False),
        ("dev", None, False),
        ("staging", None, True),
        ("production", None, True),
        ("staging", "false", False),
        ("dev", "true", True),
        ("dev", "1", True),
        ("staging", "0", False),
    ],
)
def test_enforcement_default_follows_app_env(monkeypatch, app_env, force, expected):
    monkeypatch.delenv("APP_ENV", raising=False)
    monkeypatch.delenv("FORCE_HTTPS", raising=False)
    if app_env:
        monkeypatch.setenv("APP_ENV", app_env)
    if force:
        monkeypatch.setenv("FORCE_HTTPS", force)
    assert https_enforcement_enabled() is expected


def test_middleware_is_installed_on_the_real_app():
    assert any(m.cls is HTTPSEnforcementMiddleware for m in real_app.user_middleware)