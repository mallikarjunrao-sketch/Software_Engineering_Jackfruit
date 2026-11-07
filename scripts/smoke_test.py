"""Smoke test for a deployed APMS instance (PARK-45). Uses only the Python standard library.

Usage:
    python scripts/smoke_test.py --base-url https://staging.example.com --http-url http://staging.example.com
    python scripts/smoke_test.py --base-url https://localhost:8443 --http-url http://localhost:8080 --insecure --wait 60

The demo passwords come from --admin-password / --attendant-password or from the
SMOKE_ADMIN_PASSWORD / SMOKE_ATTENDANT_PASSWORD environment variables. They are never printed.
It exits with 0 only if every check passed.
"""

import argparse
import http.client
import json
import os
import ssl
import sys
import time
from dataclasses import dataclass
from urllib.parse import urlparse

PASS, FAIL = "PASS", "FAIL"

# PARK-46: headers that the ZAP baseline scan also looks for.
SECURITY_HEADER_NAMES = (
    "content-security-policy",
    "x-content-type-options",
    "x-frame-options",
    "referrer-policy",
    "permissions-policy",
    "cross-origin-opener-policy",
    "cache-control",
)


@dataclass
class Reply:
    status: int
    headers: dict
    data: object
    text: str


def call(base_url, method, path, *, body=None, token=None, insecure=False, timeout=10.0, headers=None):
    parts = urlparse(base_url)
    if parts.scheme == "https":
        context = ssl.create_default_context()
        if insecure:
            context.check_hostname = False
            context.verify_mode = ssl.CERT_NONE
        connection = http.client.HTTPSConnection(parts.hostname, parts.port or 443, context=context, timeout=timeout)
    else:
        connection = http.client.HTTPConnection(parts.hostname, parts.port or 80, timeout=timeout)
    request_headers = {"Accept": "application/json", **(headers or {})}
    payload = None
    if body is not None:
        payload = json.dumps(body)
        request_headers["Content-Type"] = "application/json"
    if token:
        request_headers["Authorization"] = f"Bearer {token}"
    try:
        connection.request(method, path, payload, request_headers)
        response = connection.getresponse()
        text = response.read().decode("utf-8", errors="replace")
        try:
            data = json.loads(text) if text else None
        except ValueError:
            data = None
        return Reply(response.status, {k.lower(): v for k, v in response.getheaders()}, data, text)
    finally:
        connection.close()


def wait_until_healthy(base_url, insecure, seconds):
    deadline = time.monotonic() + seconds
    last_error = "no answer"
    while time.monotonic() < deadline:
        try:
            reply = call(base_url, "GET", "/health", insecure=insecure, timeout=5)
            if reply.status == 200:
                return True, "healthy"
            last_error = f"status {reply.status}"
        except (OSError, http.client.HTTPException) as error:
            last_error = str(error)
        time.sleep(2)
    return False, f"not healthy after {seconds} seconds ({last_error})"


class Smoke:
    def __init__(self, args):
        self.base = args.base_url.rstrip("/")
        self.http_url = args.http_url.rstrip("/") if args.http_url else None
        self.insecure = args.insecure
        self.admin_password = args.admin_password
        self.attendant_password = args.attendant_password
        self.tokens = {}
        self.results = []

    def get(self, method, path, **kwargs):
        return call(self.base, method, path, insecure=self.insecure, **kwargs)

    def check(self, name, function):
        try:
            problem = function()
        except (OSError, http.client.HTTPException, KeyError, TypeError, ValueError) as error:
            problem = f"{type(error).__name__}: {error}"
        self.results.append((FAIL if problem else PASS, name + (f" ({problem})" if problem else "")))

    # ---- checks: each returns None when fine, or a short description of the problem ----

    def health(self):
        reply = self.get("GET", "/health")
        if reply.status != 200 or (reply.data or {}).get("status") != "ok":
            return f"status {reply.status}"

    def hsts_header(self):
        if urlparse(self.base).scheme != "https":
            return "the base URL is not https"
        if "strict-transport-security" not in self.get("GET", "/health").headers:
            return "Strict-Transport-Security header is missing"

    def security_headers(self):
        headers = self.get("GET", "/health").headers
        missing = [name for name in SECURITY_HEADER_NAMES if name not in headers]
        if missing:
            return "missing: " + ", ".join(missing)

    def page_has_csp(self, path):
        reply = self.get("GET", path)
        csp = reply.headers.get("content-security-policy", "")
        if reply.status != 200 or "'sha256-" not in csp or "unsafe-inline" in csp:
            return f"status {reply.status}, CSP: {csp or 'missing'}"

    def docs_not_exposed(self):
        statuses = {path: self.get("GET", path).status for path in ("/docs", "/redoc")}
        open_pages = [path for path, status in statuses.items() if status == 200]
        if open_pages:
            return "still served: " + ", ".join(open_pages)

    def login(self, username, password, role):
        reply = self.get("POST", "/api/v1/auth/login", body={"username": username, "password": password})
        if reply.status != 200:
            return f"status {reply.status}"
        data = reply.data or {}
        if data.get("role") != role or not data.get("token") or not isinstance(data.get("expiresIn"), int):
            return "unexpected login response"
        self.tokens[username] = data["token"]

    def wrong_password_rejected(self):
        reply = self.get("POST", "/api/v1/auth/login", body={"username": "admin", "password": "definitely-wrong"})
        if reply.status != 401 or (reply.data or {}).get("code") != "INVALID_CREDENTIALS":
            return f"status {reply.status}"

    def me_requires_token(self):
        reply = self.get("GET", "/api/v1/auth/me")
        if reply.status != 401:
            return f"status {reply.status}"

    def me_with_token(self):
        token = self.tokens.get("admin")
        if not token:
            return "no admin token (admin login failed)"
        reply = self.get("GET", "/api/v1/auth/me", token=token)
        if reply.status != 200 or (reply.data or {}).get("username") != "admin":
            return f"status {reply.status}"

    def availability(self):
        reply = self.get("GET", "/api/v1/availability", token=self.tokens.get("admin"))
        if reply.status != 200 or reply.data is None:
            return f"status {reply.status}"

    def admin_route(self, username, expected_status, path="/api/v1/admin/ping"):
        token = self.tokens.get(username)
        if not token:
            return f"no {username} token (login failed)"
        reply = self.get("GET", path, token=token)
        if reply.status != expected_status:
            return f"status {reply.status}, expected {expected_status}"

    def revenue_report(self):
        token = self.tokens.get("admin")
        if not token:
            return "no admin token (admin login failed)"
        reply = self.get("GET", "/api/v1/reports/revenue", token=token)
        data = reply.data or {}
        if reply.status != 200 or "totals" not in data or not isinstance(data.get("rows"), list):
            return f"status {reply.status}"

    def plain_http_redirected(self):
        reply = call(self.http_url, "GET", "/health", timeout=10)
        location = reply.headers.get("location", "")
        if reply.status in {301, 302, 307, 308} and location.lower().startswith("https://"):
            return None
        if reply.status in {401, 403, 426}:
            return None
        return f"plain HTTP GET was answered with status {reply.status}"

    def plain_http_post_refused(self):
        reply = call(
            self.http_url, "POST", "/api/v1/auth/login",
            body={"username": "admin", "password": "not-sent-for-real"}, timeout=10,
        )
        if reply.status not in {301, 302, 307, 308, 403, 426}:
            return f"plain HTTP login was processed (status {reply.status})"

    def run(self):
        self.check("health endpoint answers", self.health)
        self.check("HTTPS response has the HSTS header", self.hsts_header)
        self.check("API responses carry the security headers", self.security_headers)
        for page in ("/kiosk", "/board", "/dashboard"):
            self.check(f"{page} page has a hash-based CSP", lambda page=page: self.page_has_csp(page))
        self.check("Swagger and ReDoc pages are not exposed", self.docs_not_exposed)
        self.check("admin can log in", lambda: self.login("admin", self.admin_password, "ADMIN"))
        self.check("attendant can log in", lambda: self.login("attendant", self.attendant_password, "ATTENDANT"))
        self.check("wrong password is rejected (401)", self.wrong_password_rejected)
        self.check("/auth/me without a token is rejected (401)", self.me_requires_token)
        self.check("/auth/me with a token works", self.me_with_token)
        self.check("availability endpoint works", self.availability)
        self.check("admin can use an admin route (200)", lambda: self.admin_route("admin", 200))
        self.check("attendant is blocked from an admin route (403)", lambda: self.admin_route("attendant", 403))
        self.check("admin can read the revenue report", self.revenue_report)
        self.check("attendant is blocked from reports (403)", lambda: self.admin_route("attendant", 403, "/api/v1/reports/revenue"))
        if self.http_url:
            self.check("plain HTTP GET is redirected or refused", self.plain_http_redirected)
            self.check("plain HTTP POST is refused", self.plain_http_post_refused)
        return self.results


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test for a deployed APMS instance.")
    parser.add_argument("--base-url", required=True, help="https address of the instance")
    parser.add_argument("--http-url", help="plain http address of the same instance (checks the redirect)")
    parser.add_argument("--admin-password", default=os.getenv("SMOKE_ADMIN_PASSWORD"))
    parser.add_argument("--attendant-password", default=os.getenv("SMOKE_ATTENDANT_PASSWORD"))
    parser.add_argument("--insecure", action="store_true", help="do not verify the certificate (self-signed)")
    parser.add_argument("--wait", type=int, default=60, help="seconds to wait for /health (default 60)")
    args = parser.parse_args()
    if not args.admin_password or not args.attendant_password:
        parser.error("give both passwords with --admin-password/--attendant-password or SMOKE_*_PASSWORD")

    healthy, detail = wait_until_healthy(args.base_url.rstrip("/"), args.insecure, args.wait)
    if not healthy:
        print(f"[{FAIL}] {detail}")
        print("RESULT: FAIL")
        return 1

    results = Smoke(args).run()
    for status, message in results:
        print(f"[{status}] {message}")
    failed = sum(1 for status, _ in results if status == FAIL)
    print(f"RESULT: {'FAIL' if failed else 'PASS'} ({len(results) - failed} passed, {failed} failed)")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())