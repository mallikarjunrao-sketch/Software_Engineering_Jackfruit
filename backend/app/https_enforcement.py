import os
import uuid

from starlette.datastructures import Headers, MutableHeaders, URL
from starlette.responses import JSONResponse, RedirectResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# One year, as recommended for HSTS.
HSTS_VALUE = "max-age=31536000; includeSubDomains"

WEBSOCKET_POLICY_VIOLATION = 1008


def https_enforcement_enabled() -> bool:
    """FORCE_HTTPS=true/false decides. If it is not set, HTTPS is enforced whenever APP_ENV is not 'dev'."""
    flag = os.getenv("FORCE_HTTPS")
    if flag is not None:
        return flag.strip().lower() in {"1", "true", "yes", "on"}
    return os.getenv("APP_ENV", "dev") != "dev"


def _is_secure(scope: Scope, headers: Headers) -> bool:
    # Behind a TLS-terminating proxy the app itself sees plain HTTP, so the proxy's header decides.
    forwarded = headers.get("x-forwarded-proto")
    if forwarded:
        return forwarded.split(",")[0].strip().lower() in {"https", "wss"}
    return scope.get("scheme") in {"https", "wss"}


class HTTPSEnforcementMiddleware:
    """APMS-SR-001: plain HTTP is redirected or refused, and HTTPS responses carry an HSTS header.

    - GET and HEAD over plain HTTP are redirected (308) to the https:// address.
    - Any other method over plain HTTP is refused with 403 before the endpoint runs, because a
      redirect would not stop the request body (for example a password) crossing the network.
    - WebSocket connections over plain ws:// are closed (policy violation).
    The TLS version itself (1.2 or higher) is set where TLS ends: see scripts/check_tls.py.
    """

    def __init__(self, app: ASGIApp, enabled: bool | None = None):
        self.app = app
        self.enabled = https_enforcement_enabled() if enabled is None else enabled

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if not self.enabled or scope["type"] not in {"http", "websocket"}:
            await self.app(scope, receive, send)
            return

        headers = Headers(scope=scope)
        if not _is_secure(scope, headers):
            await self._refuse(scope, receive, send)
            return

        if scope["type"] == "websocket":
            await self.app(scope, receive, send)
            return

        async def send_with_hsts(message: Message) -> None:
            if message["type"] == "http.response.start":
                MutableHeaders(scope=message)["Strict-Transport-Security"] = HSTS_VALUE
            await send(message)

        await self.app(scope, receive, send_with_hsts)

    async def _refuse(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "websocket":
            await receive()  # the connect event
            await send({"type": "websocket.close", "code": WEBSOCKET_POLICY_VIOLATION})
            return

        if scope["method"] in {"GET", "HEAD"}:
            url = URL(scope=scope)
            netloc = url.netloc[:-3] if url.netloc.endswith(":80") else url.netloc
            response = RedirectResponse(str(url.replace(scheme="https", netloc=netloc)), status_code=308)
        else:
            response = JSONResponse(
                status_code=403,
                content={
                    "code": "HTTPS_REQUIRED",
                    "message": "Use https:// for all requests",
                    "requestId": str(uuid.uuid4()),
                },
            )
        await response(scope, receive, send)