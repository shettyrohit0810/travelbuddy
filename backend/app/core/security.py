"""Password hashing and JWT issuance.

Access and refresh tokens are signed with *different* secrets and carry an explicit
`type` claim that is checked on decode. Using one secret for both means a stolen
refresh token is silently accepted as an access token; checking only the signature and
not the claim means the same thing.
"""
from datetime import datetime, timedelta, timezone
from typing import Any

import bcrypt
import jwt

from app.core.config import settings

ACCESS = "access"
REFRESH = "refresh"


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(plain.encode(), bcrypt.gensalt(rounds=12)).decode()


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode(), hashed.encode())
    except (ValueError, TypeError):
        # A malformed stored hash must read as "wrong password", never as an exception
        # that a caller might mistake for a server fault and retry around.
        return False


def _issue(subject: str, token_type: str, secret: str, expires: timedelta) -> str:
    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "sub": str(subject),
        "type": token_type,
        "iat": now,
        "exp": now + expires,
    }
    return jwt.encode(payload, secret, algorithm=settings.ALGORITHM)


def create_access_token(subject: str) -> str:
    return _issue(subject, ACCESS, settings.SECRET_KEY,
                  timedelta(minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES))


def create_refresh_token(subject: str) -> str:
    return _issue(subject, REFRESH, settings.REFRESH_SECRET_KEY,
                  timedelta(days=settings.REFRESH_TOKEN_EXPIRE_DAYS))


def decode_token(token: str, expected_type: str) -> dict | None:
    """Decode and verify. Returns None on any failure -- including a valid token of the
    wrong type, which is the case a signature-only check would wrongly accept."""
    secret = settings.SECRET_KEY if expected_type == ACCESS else settings.REFRESH_SECRET_KEY
    try:
        payload = jwt.decode(token, secret, algorithms=[settings.ALGORITHM])
    except jwt.PyJWTError:
        return None
    if payload.get("type") != expected_type or not payload.get("sub"):
        return None
    return payload
