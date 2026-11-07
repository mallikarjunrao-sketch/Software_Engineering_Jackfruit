import base64
import hashlib
import re
from functools import lru_cache
from pathlib import Path

from fastapi.responses import HTMLResponse

# The three pages (kiosk, board, dashboard) each have one inline <script> and one inline <style>.
# Instead of allowing every inline script with 'unsafe-inline', the Content-Security-Policy lists
# the SHA-256 hash of each block, so a script injected into the page would be refused by the browser.
_INLINE_BLOCK = re.compile(r"<(script|style)(?:\s[^>]*)?>(.*?)</\1>", re.DOTALL | re.IGNORECASE)


def _hash(text: str) -> str:
    return "'sha256-" + base64.b64encode(hashlib.sha256(text.encode("utf-8")).digest()).decode() + "'"


def build_csp(html: str) -> str:
    scripts, styles = [], []
    for tag, body in _INLINE_BLOCK.findall(html):
        (scripts if tag.lower() == "script" else styles).append(_hash(body))
    return "; ".join(
        [
            "default-src 'none'",
            "script-src " + (" ".join(scripts) or "'none'"),
            "style-src " + (" ".join(styles) or "'none'"),
            "connect-src 'self'",
            "img-src 'self' data:",
            "base-uri 'none'",
            "form-action 'self'",
            "frame-ancestors 'none'",
            "object-src 'none'",
        ]
    )


@lru_cache(maxsize=16)
def _load(path: str, modified: int) -> tuple[str, str]:
    html = Path(path).read_text(encoding="utf-8")
    return html, build_csp(html)


def html_page(path: Path) -> HTMLResponse:
    """Serve one of the static HTML pages with a Content-Security-Policy that matches its inline code."""
    html, csp = _load(str(path), path.stat().st_mtime_ns)
    return HTMLResponse(html, headers={"Content-Security-Policy": csp})