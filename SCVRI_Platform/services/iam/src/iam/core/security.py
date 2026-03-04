"""
Core security utilities — JWT RS256 issuance/verification, bcrypt hashing, TOTP.

Key decisions:
  - RS256 (asymmetric) so other services can verify tokens with the public key only.
  - Private key loaded once at startup from env (PEM string or file path).
  - Refresh tokens are stored in Redis with TTL; rotation invalidates the old token.
  - TOTP uses pyotp (RFC 6238, 30-second window, SHA1 per spec).
"""
from __future__ import annotations

import base64
import io
import time
import uuid
from datetime import timedelta
from typing import Any

from jose import JWTError, jwt
from passlib.context import CryptContext
import pyotp
import qrcode
import qrcode.image.svg

from scvri_shared.config import settings
from scvri_shared.logging import get_logger

log = get_logger(__name__)

# ── Password hashing ──────────────────────────────────────────────────────────

_pwd_ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return _pwd_ctx.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return _pwd_ctx.verify(plain, hashed)


# ── JWT configuration ─────────────────────────────────────────────────────────

ALGORITHM = "RS256"
ACCESS_TOKEN_TTL_SECONDS: int = 3600          # 1 hour
REFRESH_TOKEN_TTL_SECONDS: int = 30 * 86_400  # 30 days


def _load_private_key() -> str:
    """Load RS256 private key PEM from settings (string or file path)."""
    key_pem: str = getattr(settings, "jwt_private_key", "")
    if not key_pem:
        path: str = getattr(settings, "jwt_private_key_path", "")
        if path:
            with open(path) as fh:
                key_pem = fh.read()
    if not key_pem:
        raise RuntimeError(
            "IAM startup error: set IAM_JWT_PRIVATE_KEY or IAM_JWT_PRIVATE_KEY_PATH"
        )
    return key_pem


def _load_public_key() -> str:
    """Load RS256 public key PEM from settings."""
    key_pem: str = getattr(settings, "jwt_public_key", "")
    if not key_pem:
        path: str = getattr(settings, "jwt_public_key_path", "")
        if path:
            with open(path) as fh:
                key_pem = fh.read()
    if not key_pem:
        raise RuntimeError(
            "IAM startup error: set IAM_JWT_PUBLIC_KEY or IAM_JWT_PUBLIC_KEY_PATH"
        )
    return key_pem


# Loaded lazily so unit tests can patch settings before import
_private_key: str | None = None
_public_key: str | None = None


def get_private_key() -> str:
    global _private_key
    if _private_key is None:
        _private_key = _load_private_key()
    return _private_key


def get_public_key() -> str:
    global _public_key
    if _public_key is None:
        _public_key = _load_public_key()
    return _public_key


# ── Access token ──────────────────────────────────────────────────────────────

def create_access_token(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    role: str,
    email: str,
    ttl_seconds: int = ACCESS_TOKEN_TTL_SECONDS,
) -> tuple[str, str]:
    """
    Issue a signed RS256 access token.
    Returns (encoded_jwt, jti).
    """
    now = int(time.time())
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "role": role,
        "email": email,
        "iat": now,
        "exp": now + ttl_seconds,
        "jti": jti,
        "token_type": "access",
    }
    encoded = jwt.encode(payload, get_private_key(), algorithm=ALGORITHM)
    return encoded, jti


def decode_access_token(token: str) -> dict[str, Any]:
    """
    Verify and decode an RS256 JWT.
    Raises jose.JWTError on invalid / expired tokens.
    """
    return jwt.decode(token, get_public_key(), algorithms=[ALGORITHM])


# ── Refresh token ─────────────────────────────────────────────────────────────

def create_refresh_token(
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    ttl_seconds: int = REFRESH_TOKEN_TTL_SECONDS,
) -> tuple[str, str]:
    """
    Issue a refresh token (RS256, shorter payload).
    Returns (encoded_jwt, jti).
    """
    now = int(time.time())
    jti = str(uuid.uuid4())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "jti": jti,
        "iat": now,
        "exp": now + ttl_seconds,
        "token_type": "refresh",
    }
    encoded = jwt.encode(payload, get_private_key(), algorithm=ALGORITHM)
    return encoded, jti


def decode_refresh_token(token: str) -> dict[str, Any]:
    """
    Verify and decode a refresh token.
    Raises jose.JWTError on invalid / expired tokens.
    """
    claims = jwt.decode(token, get_public_key(), algorithms=[ALGORITHM])
    if claims.get("token_type") != "refresh":
        raise JWTError("not a refresh token")
    return claims


# ── MFA session token (short-lived, for 2-step login) ────────────────────────

MFA_SESSION_TTL_SECONDS = 300  # 5 minutes


def create_mfa_session_token(user_id: uuid.UUID, tenant_id: uuid.UUID) -> str:
    """Issue a 5-minute token used during the MFA verification step."""
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "tenant_id": str(tenant_id),
        "iat": now,
        "exp": now + MFA_SESSION_TTL_SECONDS,
        "token_type": "mfa_session",
    }
    return jwt.encode(payload, get_private_key(), algorithm=ALGORITHM)


def decode_mfa_session_token(token: str) -> dict[str, Any]:
    claims = jwt.decode(token, get_public_key(), algorithms=[ALGORITHM])
    if claims.get("token_type") != "mfa_session":
        raise JWTError("not an mfa_session token")
    return claims


# ── Password reset token ──────────────────────────────────────────────────────

RESET_TOKEN_TTL_SECONDS = 3600  # 1 hour


def create_password_reset_token(user_id: uuid.UUID) -> str:
    now = int(time.time())
    payload: dict[str, Any] = {
        "sub": str(user_id),
        "iat": now,
        "exp": now + RESET_TOKEN_TTL_SECONDS,
        "token_type": "pwd_reset",
        "jti": str(uuid.uuid4()),
    }
    return jwt.encode(payload, get_private_key(), algorithm=ALGORITHM)


def decode_password_reset_token(token: str) -> dict[str, Any]:
    claims = jwt.decode(token, get_public_key(), algorithms=[ALGORITHM])
    if claims.get("token_type") != "pwd_reset":
        raise JWTError("not a pwd_reset token")
    return claims


# ── Token revocation (Redis) ──────────────────────────────────────────────────

async def revoke_token(redis_client: Any, jti: str, ttl_seconds: int) -> None:
    """Add a JTI to the Redis revocation set."""
    await redis_client.setex(f"revoked_jti:{jti}", ttl_seconds, "1")


async def is_token_revoked(redis_client: Any, jti: str) -> bool:
    return await redis_client.exists(f"revoked_jti:{jti}") == 1


# ── Refresh token storage (rotation) ─────────────────────────────────────────

REFRESH_REDIS_PREFIX = "refresh_token:"


async def store_refresh_token(
    redis_client: Any,
    user_id: uuid.UUID,
    jti: str,
    ttl_seconds: int = REFRESH_TOKEN_TTL_SECONDS,
) -> None:
    """Store refresh JTI → user_id mapping for validation & rotation."""
    await redis_client.setex(f"{REFRESH_REDIS_PREFIX}{jti}", ttl_seconds, str(user_id))


async def validate_and_rotate_refresh_token(
    redis_client: Any,
    jti: str,
    expected_user_id: str,
) -> bool:
    """Validate that jti exists and belongs to user; delete it (rotation)."""
    stored = await redis_client.getdel(f"{REFRESH_REDIS_PREFIX}{jti}")
    if stored is None:
        return False
    stored_str = stored.decode() if isinstance(stored, bytes) else stored
    return stored_str == expected_user_id


# ── TOTP ──────────────────────────────────────────────────────────────────────

TOTP_ISSUER = "SCVRI Platform"


def generate_totp_secret() -> str:
    """Generate a new base32-encoded TOTP secret."""
    return pyotp.random_base32()


def get_totp_provisioning_uri(secret: str, email: str) -> str:
    """Return otpauth:// URI for QR code generation."""
    totp = pyotp.TOTP(secret)
    return totp.provisioning_uri(name=email, issuer_name=TOTP_ISSUER)


def build_totp_qr_data_uri(provisioning_uri: str) -> str:
    """Render the provisioning URI as a base64-encoded PNG data URI."""
    img = qrcode.make(provisioning_uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    b64 = base64.b64encode(buf.getvalue()).decode()
    return f"data:image/png;base64,{b64}"


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    """
    Verify a 6-digit TOTP code.
    valid_window=1 means ±1 period (±30 seconds) tolerance for clock skew.
    """
    totp = pyotp.TOTP(secret)
    return totp.verify(code, valid_window=valid_window)
