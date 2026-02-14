"""
Sawa — Security: Twilio validation, PIN auth, RBAC, phone encryption
"""
from datetime import datetime, timezone, timedelta

from fastapi import Request, HTTPException
import bcrypt as _bcrypt
from twilio.request_validator import RequestValidator
from cryptography.fernet import Fernet
import base64
import hashlib

from config import settings
from db import AsyncSession, User, get_user, log_action, get_conversation_state

# ── Fernet encryption for phone-at-rest ─────────────────────────────────────

def _derive_fernet_key(secret: str) -> bytes:
    """Derive a Fernet key from the app secret."""
    digest = hashlib.sha256(secret.encode()).digest()
    return base64.urlsafe_b64encode(digest)


_fernet = Fernet(_derive_fernet_key(settings.secret_key))


def encrypt_phone(phone: str) -> str:
    return _fernet.encrypt(phone.encode()).decode()


def decrypt_phone(token: str) -> str:
    return _fernet.decrypt(token.encode()).decode()


# ── Twilio Signature Validation ─────────────────────────────────────────────

async def validate_twilio_request(request: Request):
    """FastAPI dependency — validates Twilio webhook signature."""
    if settings.skip_twilio_validation:
        return

    if not settings.twilio_auth_token:
        return  # No token configured; skip in dev

    validator = RequestValidator(settings.twilio_auth_token)

    # Reconstruct URL
    url = str(request.url)
    # Twilio sends form data
    form = await request.form()
    params = {k: v for k, v in form.items()}

    signature = request.headers.get("X-Twilio-Signature", "")

    if not validator.validate(url, params, signature):
        raise HTTPException(status_code=403, detail="Invalid Twilio signature")


# ── PIN Helpers ─────────────────────────────────────────────────────────────

def hash_pin(pin: str) -> str:
    return _bcrypt.hashpw(pin.encode(), _bcrypt.gensalt()).decode()


def verify_pin(pin: str, pin_hash: str) -> bool:
    return _bcrypt.checkpw(pin.encode(), pin_hash.encode())


PIN_TTL = timedelta(minutes=10)


async def is_pin_verified(session: AsyncSession, phone: str) -> bool:
    """Check if user has a valid (non-expired) PIN session."""
    conv = await get_conversation_state(session, phone)
    if conv and conv.pin_verified_at:
        elapsed = datetime.now(timezone.utc) - conv.pin_verified_at
        return elapsed < PIN_TTL
    return False


# ── RBAC ────────────────────────────────────────────────────────────────────

# Actions requiring specific roles
OWNER_ADMIN_ACTIONS = {
    "ADD_EMPLOYEE", "PAYROLL", "LIST", "POST_JOB", "CANDIDATES",
    "PAYSLIP_ALL", "LEAVE_ALL",
}
EMPLOYEE_ACTIONS = {"PAYSLIP_OWN", "LEAVE_OWN", "APPLY"}

# Actions requiring PIN
PIN_REQUIRED_ACTIONS = {"PAYROLL", "PAYSLIP", "PAYSLIP_ALL"}


def check_role(user: User | None, action: str) -> bool:
    """Check if user's role permits this action."""
    if user is None:
        return False
    if user.role in ("owner", "admin"):
        return True
    if user.role == "employee" and action in EMPLOYEE_ACTIONS:
        return True
    return False
