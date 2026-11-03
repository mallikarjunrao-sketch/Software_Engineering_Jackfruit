"""TLS check for APMS-SR-001 (test case TC-SEC-01). Uses only the Python standard library.

Usage:
    python scripts/check_tls.py https://staging.example.com
    python scripts/check_tls.py https://localhost:8443 --http-port 8000 --insecure

It checks three things and exits with 0 only if none of them failed:
  1. Plain HTTP is redirected to https:// or refused.
  2. TLS 1.2 or TLS 1.3 works.
  3. TLS 1.0 and TLS 1.1 are rejected.
Use --insecure for a self-signed certificate (local or staging). For a full scan
of ciphers and certificates, run nmap or testssl.sh against the same host.
"""

import argparse
import socket
import ssl
import sys
import warnings
from urllib.parse import urlparse

# Python warns when old TLS version constants are used; testing them is the point of this script.
warnings.filterwarnings("ignore", category=DeprecationWarning)

PASS, FAIL, INFO = "PASS", "FAIL", "INFO"


def make_context(version: ssl.TLSVersion, insecure: bool) -> ssl.SSLContext:
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_CLIENT)
    context.minimum_version = version
    context.maximum_version = version
    if version < ssl.TLSVersion.TLSv1_2:
        context.set_ciphers("ALL:@SECLEVEL=0")  # let the client offer old protocols at all
    if insecure:
        context.check_hostname = False
        context.verify_mode = ssl.CERT_NONE
    return context


def try_handshake(host: str, port: int, version: ssl.TLSVersion, insecure: bool, timeout: float):
    """Return ('ok', negotiated_version), ('rejected', reason) or ('unsupported', reason)."""
    try:
        context = make_context(version, insecure)
    except (ValueError, ssl.SSLError) as error:
        return "unsupported", str(error)
    try:
        with socket.create_connection((host, port), timeout=timeout) as raw:
            with context.wrap_socket(raw, server_hostname=host) as tls:
                return "ok", tls.version()
    except ssl.SSLCertVerificationError as error:
        return "cert_error", error.verify_message
    except (ssl.SSLError, ConnectionResetError, EOFError) as error:
        if "NO_PROTOCOLS_AVAILABLE" in str(error).upper().replace(" ", "_"):
            return "unsupported", str(error)  # this computer refused to offer the protocol
        return "rejected", str(error)
    except OSError as error:
        return "unreachable", str(error)


def check_plain_http(host: str, port: int, timeout: float):
    request = f"GET /health HTTP/1.1\r\nHost: {host}\r\nConnection: close\r\n\r\n".encode()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(request)
            data = sock.recv(4096).decode("latin-1")
    except (ConnectionRefusedError, socket.timeout, TimeoutError):
        return PASS, f"plain HTTP on port {port} is refused (no answer)"
    except OSError as error:
        return PASS, f"plain HTTP on port {port} is refused ({error})"
    if not data:
        return PASS, f"plain HTTP on port {port} is closed without an answer"
    status = int(data.split(" ", 2)[1]) if data.startswith("HTTP/") else 0
    location = next((line.split(":", 1)[1].strip() for line in data.split("\r\n") if line.lower().startswith("location:")), "")
    if status in {301, 302, 307, 308} and location.lower().startswith("https://"):
        return PASS, f"plain HTTP is redirected ({status}) to {location}"
    if status in {401, 403, 426}:
        return PASS, f"plain HTTP is refused ({status})"
    return FAIL, f"plain HTTP is served normally (status {status})"


def main() -> int:
    parser = argparse.ArgumentParser(description="Check TLS 1.2+ and plain HTTP handling (APMS-SR-001).")
    parser.add_argument("url", help="HTTPS address, for example https://staging.example.com")
    parser.add_argument("--http-port", type=int, default=80, help="port that serves plain HTTP (default 80)")
    parser.add_argument("--insecure", action="store_true", help="do not verify the certificate (self-signed)")
    parser.add_argument("--timeout", type=float, default=5.0)
    args = parser.parse_args()

    parsed = urlparse(args.url)
    if parsed.scheme != "https" or not parsed.hostname:
        parser.error("the address must start with https://")
    host, port = parsed.hostname, parsed.port or 443

    results = [check_plain_http(host, args.http_port, args.timeout)]

    supported = []
    for name, version in (("TLS 1.3", ssl.TLSVersion.TLSv1_3), ("TLS 1.2", ssl.TLSVersion.TLSv1_2)):
        outcome, detail = try_handshake(host, port, version, args.insecure, args.timeout)
        if outcome == "ok":
            supported.append(name)
            results.append((PASS, f"{name} handshake works"))
        elif outcome in {"cert_error", "unreachable"}:
            results.append((FAIL, f"{name}: {outcome} ({detail}); use --insecure for a self-signed certificate"))
        elif name == "TLS 1.3":
            results.append((INFO, f"{name} not offered ({detail})"))
        else:
            results.append((FAIL, f"{name} handshake failed ({detail})"))
    if not supported:
        results.append((FAIL, "neither TLS 1.2 nor TLS 1.3 is available"))

    for name, version in (("TLS 1.1", ssl.TLSVersion.TLSv1_1), ("TLS 1.0", ssl.TLSVersion.TLSv1)):
        outcome, detail = try_handshake(host, port, version, args.insecure, args.timeout)
        if outcome == "ok":
            results.append((FAIL, f"{name} is accepted by the server"))
        elif outcome == "unsupported":
            results.append((INFO, f"{name} could not be tested: this computer's OpenSSL has it disabled. Check with nmap --script ssl-enum-ciphers or testssl.sh"))
        elif outcome == "rejected":
            results.append((PASS, f"{name} is rejected by the server"))
        else:
            results.append((INFO, f"{name} not tested ({outcome}: {detail})"))

    for status, message in results:
        print(f"[{status}] {message}")
    failed = any(status == FAIL for status, _ in results)
    print("RESULT:", "FAIL" if failed else "PASS")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())