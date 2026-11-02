from datetime import datetime, timedelta, timezone

from backend.app.constants import (
    CAR,
    PAYMENT_SUCCESS,
    SESSION_ACTIVE,
    SESSION_PAID,
)
from backend.app.models import ParkingSession, Payment, Vehicle
from backend.app.services.card_security import (
    inspect_database_for_card_data,
    mask_card_number,
    mask_token_or_reference,
    redact_sensitive_string,
    sanitize_payment_dict,
)
from backend.app.services.payment import process_payment
from backend.app.services.receipt import build_receipt_dict


# ==============================================================================
# Helpers
# ==============================================================================

def create_card_session(db_session, fee: int = 50) -> ParkingSession:
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    vehicle = Vehicle(plate="KA05CD1122", vehicle_type=CAR)
    db_session.merge(vehicle)

    session = ParkingSession(
        plate="KA05CD1122",
        slot_id="C-001",
        entry_time=now - timedelta(minutes=61),
        exit_time=None,
        status=SESSION_ACTIVE,
        fee=fee,
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


# ==============================================================================
# TC-SEC-05: No card data stored (APMS-SR-005)
# ==============================================================================

def test_tc_sec_05_pay_by_card_and_inspect_stored_values(db_session):
    """TC-SEC-05: Pay by card with test data and inspect stored values.

    Database inspection shows only masked values (e.g. last four digits)
    and zero full card numbers, CVVs or PINs.
    """
    session = create_card_session(db_session, fee=50)

    # 1. Simulate card payment
    result = process_payment(
        db=db_session,
        session_id=session.id,
        mode="CARD",
        amount=50,
        simulate="success",
    )
    assert result["status"] == PAYMENT_SUCCESS

    # 2. Inspect the stored payment record in DB
    payment = db_session.get(Payment, result["paymentId"])
    assert payment is not None
    assert payment.mode == "CARD"

    # Verify masked_ref is stored and contains only masked last 4 digits
    assert payment.masked_ref is not None
    assert payment.masked_ref.startswith("***")
    assert len(payment.masked_ref) <= 7  # e.g. '***ABCD' or '***1234'

    # Verify txn_ref is a gateway token, not a credit card PAN
    assert payment.txn_ref.startswith("CAR-")
    assert len(payment.txn_ref) <= 20

    # 3. Comprehensive automated database audit
    audit_report = inspect_database_for_card_data(db_session)
    assert audit_report["compliant"] is True
    assert len(audit_report["violations"]) == 0
    assert audit_report["recordsChecked"] >= 1


def test_tc_sec_05_receipt_contains_only_masked_reference(db_session):
    """Verify that receipts issued for card payments contain only masked references."""
    session = create_card_session(db_session, fee=50)
    session.status = SESSION_PAID

    payment = Payment(
        session_id=session.id,
        amount=50,
        mode="CARD",
        status=PAYMENT_SUCCESS,
        txn_ref="CAR-TESTTOKEN99",
        masked_ref="***EN99",
    )
    db_session.add(payment)
    db_session.commit()

    receipt = build_receipt_dict(session, payment)
    assert receipt["mode"] == "CARD"
    assert receipt["maskedRef"] == "***EN99"
    # Verify no raw card fields are exposed in receipt dict
    assert "cardNumber" not in receipt
    assert "cvv" not in receipt
    assert "pin" not in receipt


# ==============================================================================
# Card Number Masking & Tokenization Tests
# ==============================================================================

def test_mask_card_number():
    # 16-digit standard cards
    assert mask_card_number("4111111111111234") == "****-****-****-1234"
    assert mask_card_number("5500-0000-0000-4321") == "****-****-****-4321"
    assert mask_card_number("6011 0000 0000 9876") == "****-****-****-9876"

    # 15-digit Amex card
    assert mask_card_number("378282246310005") == "****-****-****-0005"

    # Short or empty input
    assert mask_card_number("123") == "****"
    assert mask_card_number("") == ""
    assert mask_card_number(None) == ""


def test_mask_token_or_reference():
    assert mask_token_or_reference("CAR-9876543210") == "***3210"
    assert mask_token_or_reference("UPI-TXN1234") == "***1234"
    assert mask_token_or_reference("12") == "***12"
    assert mask_token_or_reference(None) is None
    assert mask_token_or_reference("") is None


# ==============================================================================
# Payload Sanitization & SAD/PIN Redaction Tests
# ==============================================================================

def test_sanitize_payment_dict_strips_cvv_and_pin():
    """Verify CVV, CVC, PIN, and security codes are stripped/redacted from payloads."""
    raw_payload = {
        "sessionId": 10,
        "mode": "CARD",
        "amount": 100,
        "cardNumber": "4111-2222-3333-4444",
        "cvv": "123",
        "pin": "4567",
        "metadata": {
            "security_code": "987",
            "device": "terminal-1",
        },
    }

    sanitized = sanitize_payment_dict(raw_payload)

    # Card number is masked
    assert sanitized["cardNumber"] == "****-****-****-4444"
    # CVV and PIN are redacted
    assert sanitized["cvv"] == "[REDACTED]"
    assert sanitized["pin"] == "[REDACTED]"
    assert sanitized["metadata"]["security_code"] == "[REDACTED]"
    # Normal fields are preserved
    assert sanitized["sessionId"] == 10
    assert sanitized["amount"] == 100
    assert sanitized["metadata"]["device"] == "terminal-1"


def test_redact_sensitive_string_in_logs_and_messages():
    """Verify card numbers and CVVs embedded in log messages or text strings are redacted."""
    log_line = "Failed charge for card 4111111111119999 with cvv: 456 on gateway"
    redacted = redact_sensitive_string(log_line)

    assert "4111111111119999" not in redacted
    assert "****-****-****-9999" in redacted
    assert "456" not in redacted
    assert "[REDACTED]" in redacted

    assert redact_sensitive_string("") == ""
    assert redact_sensitive_string(None) is None


# ==============================================================================
# Database Audit Violation Detection Tests
# ==============================================================================

def test_database_audit_detects_violations(db_session):
    """Verify inspect_database_for_card_data flags unmasked card data if improperly inserted."""
    session = create_card_session(db_session, fee=50)

    # Deliberately insert a non-compliant payment record with an unmasked reference
    bad_payment = Payment(
        session_id=session.id,
        amount=50,
        mode="CARD",
        status=PAYMENT_SUCCESS,
        txn_ref="4111111111111234",  # Raw PAN leak in txn_ref
        masked_ref="UNMASKED_REF",   # Missing '***' mask prefix
    )
    db_session.add(bad_payment)

    # Deliberately insert an AuditLog and Session with raw card leak
    from backend.app.models import AuditLog
    bad_audit = AuditLog(
        action="TEST_LEAK",
        user_id="test_user",
        details="Card 4111111111111234 payment failed",
    )
    bad_session = ParkingSession(
        plate="KA05LEAK01",
        slot_id="C-002",
        status=SESSION_ACTIVE,
        override_reason="Payment issue with 4111111111111234",
    )
    db_session.add(bad_audit)
    db_session.add(bad_session)
    db_session.commit()

    report = inspect_database_for_card_data(db_session)
    assert report["compliant"] is False
    assert any("unmasked masked_ref" in v for v in report["violations"])
    assert any("raw card number" in v for v in report["violations"])
    assert any("AuditLog" in v for v in report["violations"])
    assert any("Session" in v for v in report["violations"])

    # Clean up the bad records
    db_session.delete(bad_payment)
    db_session.delete(bad_audit)
    db_session.delete(bad_session)
    db_session.commit()

    # Re-verify database is compliant
    clean_report = inspect_database_for_card_data(db_session)
    assert clean_report["compliant"] is True


def test_sanitize_dict_with_embedded_card_and_non_digit_match():
    """Test sanitizing dictionary containing card number in non-standard field and short pattern match."""
    payload = {
        "user_note": "Payment made using card 4111111111119999 at terminal",
    }
    sanitized = sanitize_payment_dict(payload)
    assert "4111111111119999" not in sanitized["user_note"]
    assert "****-****-****-9999" in sanitized["user_note"]

    # Short pattern inside redact_sensitive_string where digit count is less than 13
    assert redact_sensitive_string("12-34-56-78-90") == "12-34-56-78-90"

