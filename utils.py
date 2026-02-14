"""
Sawa — Utility functions
"""
from decimal import Decimal
from fastapi.responses import Response
from xml.sax.saxutils import escape
import re


def twiml_response(message: str) -> Response:
    """Wrap a text message in TwiML so Twilio sends it back via WhatsApp."""
    # WhatsApp 4096 char limit
    if len(message) > 4096:
        message = message[:4090] + "\n..."
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        f'<Response><Message>{escape(message)}</Message></Response>'
    )
    return Response(content=xml, media_type="application/xml")


def parse_number(text: str):
    """Parse a number from user input, returning float or None.
    Supports shorthand: 200k → 200000, 3.5m → 3500000
    """
    try:
        cleaned = text.lower().replace(',', '').replace('\u20a6', '').strip()
        multiplier = 1
        if cleaned.endswith('k'):
            multiplier = 1_000
            cleaned = cleaned[:-1]
        elif cleaned.endswith('m'):
            multiplier = 1_000_000
            cleaned = cleaned[:-1]
        val = float(cleaned) * multiplier
        if val < 0 or val > 1_000_000_000:
            return None
        return val
    except Exception:
        return None


def fmt(amount) -> str:
    """Format amount as Nigerian Naira."""
    return f"\u20a6{Decimal(str(amount)):,.2f}"


def validate_email(email: str) -> bool:
    """Basic email format validation."""
    return bool(re.match(r'^[^@\s]+@[^@\s]+\.[^@\s]+$', email))


def normalize_phone(phone_str: str) -> str:
    """Strip non-digits and return cleaned phone number."""
    return re.sub(r'\D', '', phone_str)


def validate_phone(phone_str: str) -> bool:
    """Validate phone number has reasonable length (7-15 digits)."""
    digits = normalize_phone(phone_str)
    return 7 <= len(digits) <= 15


def sanitize_input(text: str, max_length: int = 500) -> str:
    """Strip control characters and enforce max length."""
    # Strip control chars except newline
    cleaned = re.sub(r'[\x00-\x09\x0b-\x1f\x7f]', '', text)
    return cleaned[:max_length].strip()
