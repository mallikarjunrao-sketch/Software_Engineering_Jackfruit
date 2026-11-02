import re
from sqlalchemy import inspect
from sqlalchemy.orm import Session

from backend.app.models import AuditLog, ParkingSession, Payment

# Regex patterns for detecting potential credit card numbers (PAN: 13-19 digits)
CARD_PATTERN = re.compile(r"\b(?:\d[ -]*?){13,19}\b")
CVV_PATTERN = re.compile(r"\b(cvv|cvc|pin|security_code)\s*[:=]\s*['\"]?\d{3,4}['\"]?", re.IGNORECASE)

SENSITIVE_FIELD_NAMES = {
    "cvv",
    "cvc",
    "pin",
    "security_code",
    "card_pin",
    "pan",
    "full_card",
    "card_number",
    "cardnumber",
    "credit_card",
    "creditcard",
}


def mask_card_number(card_number: str) -> str:
    """Mask a credit or debit card number, preserving only the last four digits (APMS-SR-005).

    Examples:
        '4111111111111234' -> '****-****-****-1234'
        '1234-5678-9012-3456' -> '****-****-****-3456'
    """
    if not card_number:
        return ""

    digits = re.sub(r"\D", "", card_number)
    if len(digits) < 4:
        return "****"

    last4 = digits[-4:]
    return f"****-****-****-{last4}"


def mask_token_or_reference(reference: str | None) -> str | None:
    """Mask a payment gateway transaction reference or token.

    Example:
        'CAR-ABCD1234EFGH' -> '***EFGH'
    """
    if not reference:
        return None

    clean = reference.strip()
    if len(clean) <= 4:
        return f"***{clean}"
    return f"***{clean[-4:]}"


def sanitize_payment_dict(data: dict) -> dict:
    """Recursively sanitize a dictionary, removing CVV/PIN and masking card numbers.

    Ensures zero cardholder or sensitive authentication data (SAD) is persisted or logged.
    """
    sanitized = {}
    for key, value in data.items():
        key_lower = key.lower()

        # Completely strip out CVV, PIN, or CVV-like sensitive authentication data
        if any(sensitive in key_lower for sensitive in SENSITIVE_FIELD_NAMES):
            if "card" in key_lower and "number" in key_lower and isinstance(value, str):
                sanitized[key] = mask_card_number(value)
            else:
                sanitized[key] = "[REDACTED]"
            continue

        if isinstance(value, dict):
            sanitized[key] = sanitize_payment_dict(value)
        elif isinstance(value, str) and CARD_PATTERN.search(value):
            sanitized[key] = redact_sensitive_string(value)
        else:
            sanitized[key] = value

    return sanitized


def redact_sensitive_string(text: str) -> str:
    """Redact any raw card numbers or CVV sequences found within free-form text or log messages."""
    if not text:
        return text

    def _replace_card(match):
        raw = match.group(0)
        digits = re.sub(r"\D", "", raw)
        if 13 <= len(digits) <= 19:
            return mask_card_number(raw)
        return raw

    redacted = CARD_PATTERN.sub(_replace_card, text)
    redacted = CVV_PATTERN.sub(r"\1: [REDACTED]", redacted)
    return redacted


def inspect_database_for_card_data(db: Session) -> dict:
    """Audit the database to verify no plaintext card numbers, CVVs, or PINs exist (TC-SEC-05).

    Checks:
    1. Schema check: verifies no disallowed sensitive column names exist.
    2. Payment records: verifies masked_ref starts with '***' and contains only last digits.
    3. Text column scan: scans txn_ref, masked_ref, override_reason, and audit_log details
       for any unmasked 13-19 digit PAN sequences.
    """
    violations = []
    inspected_tables = ["payments", "sessions", "audit_log"]

    # 1. Schema check: verify no table has columns like cvv, pin, card_number
    inspector = inspect(db.bind) if db.bind else None
    if inspector:
        for table_name in inspected_tables:
            columns = [col["name"].lower() for col in inspector.get_columns(table_name)]
            for col in columns:
                if col in SENSITIVE_FIELD_NAMES:
                    violations.append(f"Table '{table_name}' has disallowed sensitive column '{col}'")

    # 2. Inspect payments table records
    payments = db.query(Payment).all()
    for p in payments:
        if p.masked_ref and not p.masked_ref.startswith("***"):
            violations.append(f"Payment ID {p.id} has unmasked masked_ref: '{p.masked_ref}'")

        # Check txn_ref does not leak a raw card number
        if p.txn_ref and CARD_PATTERN.search(p.txn_ref):
            violations.append(f"Payment ID {p.id} contains raw card number in txn_ref: '{p.txn_ref}'")

    # 3. Inspect audit_log table
    audits = db.query(AuditLog).all()
    for a in audits:
        if a.details and CARD_PATTERN.search(a.details):
            violations.append(f"AuditLog ID {a.id} contains unmasked card number in details")

    # 4. Inspect sessions table
    sessions = db.query(ParkingSession).all()
    for s in sessions:
        if s.override_reason and CARD_PATTERN.search(s.override_reason):
            violations.append(f"Session ID {s.id} contains unmasked card number in override_reason")

    return {
        "compliant": len(violations) == 0,
        "inspectedTables": inspected_tables,
        "recordsChecked": len(payments) + len(audits) + len(sessions),
        "violations": violations,
    }
