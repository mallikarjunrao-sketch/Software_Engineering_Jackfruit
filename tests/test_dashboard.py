import re

from backend.app.main import app
from backend.app.routers.dashboard import DASHBOARD_PAGE


def test_dashboard_page_is_served(client):
    response = client.get("/dashboard")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert "APMS Staff Dashboard" in response.text


def test_dashboard_has_login_and_role_sections(client):
    page = client.get("/dashboard").text
    for element_id in ("login-form", "entry-form", "exit-form", "tariff-form", "report-form", "tiles"):
        assert f'id="{element_id}"' in page


def test_dashboard_does_not_write_untrusted_data_as_html():
    script = DASHBOARD_PAGE.read_text(encoding="utf-8")
    assert "innerHTML" not in script
    assert "document.write" not in script
    assert "eval(" not in script


def test_dashboard_only_calls_endpoints_that_exist():
    script = DASHBOARD_PAGE.read_text(encoding="utf-8")
    called = set(re.findall(r'api\("(/[a-z/]+)', script))
    assert {"/entries", "/exits"} <= called
    paths = set(app.openapi()["paths"])
    for endpoint in ("/entries", "/exits"):
        assert "/api/v1" + endpoint in paths
