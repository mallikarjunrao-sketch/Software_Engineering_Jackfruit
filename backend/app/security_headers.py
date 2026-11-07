from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# CSP for API (JSON) responses: they never need to load anything. The HTML pages set their own,
# looser policy in backend/app/pages.py, and that one is kept.
API_CSP = "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'"

SECURITY_HEADERS = {
    "Content-Security-Policy": API_CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Embedder-Policy": "require-corp",
    "Cross-Origin-Resource-Policy": "same-origin",
    # Responses hold tickets, fees and staff data, so browsers and proxies must not store them.
    "Cache-Control": "no-store",
}


class SecurityHeadersMiddleware:
    """PARK-46: add the standard browser security headers to every HTTP response.

    A header the endpoint already set is left alone. skip_paths lets the development-only
    Swagger pages (/docs, /redoc) keep working, because they load scripts from a CDN.
    """

    def __init__(self, app: ASGIApp, skip_paths: tuple[str, ...] = ()):
        self.app = app
        self.skip_paths = skip_paths

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] in self.skip_paths:
            await self.app(scope, receive, send)
            return

        async def send_with_headers(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in SECURITY_HEADERS.items():
                    if name not in headers:
                        headers[name] = value
            await send(message)

        await self.app(scope, receive, send_with_headers)