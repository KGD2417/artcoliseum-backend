"""Password hashing (bcrypt), JWT encode/decode, and OTP generation."""
import secrets
from datetime import datetime, timedelta, timezone

import bcrypt
from jose import JWTError, jwt

from .config import settings


# ── Passwords ───────────────────────────────────────────────────────────────
def hash_password(password: str) -> str:
    # bcrypt has a 72-byte input limit; truncate to stay within it.
    pw = password.encode("utf-8")[:72]
    return bcrypt.hashpw(pw, bcrypt.gensalt()).decode("utf-8")


def verify_password(password: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode("utf-8")[:72], hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# ── JWT ─────────────────────────────────────────────────────────────────────
def _create_token(sub: str, token_type: str, expires: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload = {"sub": sub, "type": token_type, "iat": now, "exp": now + expires}
    return jwt.encode(payload, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM)


def create_access_token(sub: str) -> str:
    return _create_token(sub, "access", timedelta(minutes=settings.ACCESS_TTL_MIN))


def create_refresh_token(sub: str) -> str:
    return _create_token(sub, "refresh", timedelta(days=settings.REFRESH_TTL_DAYS))


def decode_token(token: str, expected_type: str | None = None) -> dict | None:
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
    except JWTError:
        return None
    if expected_type and payload.get("type") != expected_type:
        return None
    return payload


# ── OTP ─────────────────────────────────────────────────────────────────────
def generate_otp(digits: int = 6) -> str:
    return "".join(secrets.choice("0123456789") for _ in range(digits))
