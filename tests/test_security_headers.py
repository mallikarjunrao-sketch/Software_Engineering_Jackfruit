"""PARK-46: security headers, hash-based CSP on the pages and no Swagger outside development."""
import re

from fastapi import FastAPI
from fastapi.testclient import TestClient

from backend.app.main import docs_settings
from backend.app.pages import build_csp, _hash
from backend.app.routers.availability import BOARD_PAGE
from backend.app.routers.dashboard import DASHBOARD_PAGE
from backend.app.routers.kiosk import KIOSK_PAGE
from backend.app.security_headers import API_CSP, SECURITY_HEADERS, SecurityHeadersMiddleware

PAGES = {"/kiosk": KIOSK_PAGE, "/board": BOARD_PAGE, "/dashboard": DASHBOARD_PAGE}


def assert_standard_headers(response):
    for name, value in SECURITY_HEADERS.items():
        if name != "Content-Security-Policy":
            assert response.headers[name] == value, name
    assert "content-security-policy" in response.headers


def test_json_endpoint_has_all_security_headers(client):
    response = client.get("/health")
    assert_standard_headers(response)
    assert response.headers["content-security-policy"] == API_CSP


def test_error_responses_have_the_headers_too(client):
    for response in (client.get("/no-such-page"), client.get("/api/v1/auth/me"), client.post("/api/v1/auth/login", json={})):
        assert response.status_code in {401, 404, 422}
        assert_standard_headers(response)


def test_api_responses_are_not_cacheable(client):
    assert client.get("/api/v1/availability").headers["cache-control"] == "no-store"


def test_endpoint_header_is_not_overwritten():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware)

    @app.get("/x")
    def x():
        from fastapi.responses import JSONResponse
        return JSONResponse({}, headers={"Cache-Control": "max-age=60"})

    assert TestClient(app).get("/x").headers["cache-control"] == "max-age=60"


def test_skip_paths_get_no_added_headers():
    app = FastAPI()
    app.add_middleware(SecurityHeadersMiddleware, skip_paths=("/docs-like",))

    @app.get("/docs-like")
    def docs_like():
        return {}

    response = TestClient(app).get("/docs-like")
    assert "content-security-policy" not in response.headers
    assert "x-frame-options" not in response.headers


def test_swagger_still_works_in_development(client):
    assert client.get("/docs").status_code == 200
    assert "content-security-policy" not in client.get("/docs").headers


def test_docs_are_switched_off_outside_development():
    assert docs_settings("dev") == {}
    assert docs_settings("staging") == {"docs_url": None, "redoc_url": None}
    assert docs_settings("production") == {"docs_url": None, "redoc_url": None}
    app = FastAPI(**docs_settings("staging"))
    assert TestClient(app).get("/docs").status_code == 404
    assert TestClient(app).get("/redoc").status_code == 404


def test_pages_have_a_hash_based_csp(client):
    for url, path in PAGES.items():
        response = client.get(url)
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/html")
        csp = response.headers["content-security-policy"]
        assert "unsafe-inline" not in csp and "unsafe-eval" not in csp
        assert "default-src 'none'" in csp and "frame-ancestors 'none'" in csp
        assert "'sha256-" in csp
        assert_standard_headers(response)


def test_every_inline_script_and_style_is_covered_by_the_csp(client):
    for url in PAGES:
        response = client.get(url)
        html = response.text
        csp = response.headers["content-security-policy"]
        for tag, body in re.findall(r"<(script|style)(?:\s[^>]*)?>(.*?)</\1>", html, re.S):
            assert _hash(body) in csp, f"{url}: inline <{tag}> is not allowed by the CSP"


def test_pages_have_no_inline_handlers_or_style_attributes():
    for path in PAGES.values():
        html = path.read_text(encoding="utf-8")
        assert not re.search(r"\son[a-z]+\s*=", html), f"{path.name} has an inline event handler"
        assert not re.search(r'\sstyle\s*=', html), f"{path.name} has an inline style attribute"
        assert "<script src" not in html and "<link rel=\"stylesheet\"" not in html


def test_csp_hash_changes_when_the_script_changes():
    assert build_csp("<script>a()</script>") != build_csp("<script>b()</script>")


def test_csp_without_inline_code_blocks_everything():
    csp = build_csp("<p>plain</p>")
    assert "script-src 'none'" in csp and "style-src 'none'" in csp


def test_kiosk_calls_the_api_on_its_own_server():
    html = KIOSK_PAGE.read_text(encoding="utf-8")
    assert 'location.protocol === "file:"' in html
    assert '"/api/v1"' in html