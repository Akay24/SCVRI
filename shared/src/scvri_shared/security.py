"""Security utilities: JWT (RS256), bcrypt, TOTP, FIDO2 stub, Redis revocation.

Usage:
    from scvri_shared.security import create_access_token, verify_access_token, hash_password

All token creation / verification is stateless except for a Redis jti blocklist
check that prevents use of revoked tokens even before their natural expiry.
"""
from __future__ import annotations

import hashlib
import secrets
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

import pyotp
from cryptography.hazmat.primitives.serialization import load_pem_private_key, load_pem_public_key
from jose import ExpiredSignatureError, JWTError, jwt
from passlib.context import CryptContext

from scvri_shared.config import settings
from scvri_shared.exceptions import AuthenticationError, TokenExpiredError

# ---------------------------------------------------------------------------
# Password context — bcrypt cost 12
# ---------------------------------------------------------------------------
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto", bcrypt__rounds=12)


def hash_password(plain: str) -> str:
    """Return bcrypt-12 hash of *plain* password."""
    return _pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    """Return True if *plain* matches *hashed*.  Constant-time comparison."""
    return _pwd_context.verify(plain, hashed)


# ---------------------------------------------------------------------------
# JWT — RS256 (private key signs access tokens; public key verifies)
# ---------------------------------------------------------------------------

def _load_pem(path_or_pem: str) -> bytes:
    """Return PEM bytes from either a file path or an inline PEM string."""
    if path_or_pem.startswith("-----"):
        return path_or_pem.encode()
    import pathlib  # noqa: PLC0415
    return pathlib.Path(path_or_pem).read_bytes()


class _KeyCache:
    """Lazy-load RSA keys once and cache in process memory."""
    _private_key: Any = None
    _public_key: Any = None

    @classmethod
    def private(cls) -> Any:
        if cls._private_key is None:
            cls._private_key = load_pem_private_key(
                _load_pem(settings.jwt_private_key_path),
                password=None,
            )
        return cls._private_key

    @classmethod
    def public(cls) -> Any:
        if cls._public_key is None:
            cls._public_key = load_pem_public_key(
                _load_pem(settings.jwt_public_key_path),
            )
        return cls._public_key


def create_access_token(
    *,
    user_id: uuid.UUID,
    tenant_id: uuid.UUID,
    email: str,
    role: str,
    scopes: list[str] | None = None,
    procurement_categories: list[str] | None = None,
    supplier_segments: list[str] | None = None,
    geo_regions: list[str] | None = None,
    extra_claims: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Create a signed RS256 JWT access token.

    Returns:
        (token_str, jti) — jti is the JWT ID needed to register an active session
        and later revoke the token.
    """
    now = datetime.now(tz=timezone.utc)
    expire = now + timedelta(minutes=settings.jwt_access_token_expire_minutes)
    jti = str(uuid.uuid4())

    payload: dict[str, Any] = {
        "iss": f"{settings.jwt_issuer}/{settings.environment}",
        "aud": settings.jwt_audience,
        "sub": str(user_id),
        "tid": str(tenant_id),
        "email": email,
        "role": role,
        "scopes": scopes or [],
        "procurement_categories": procurement_categories or [],
        "supplier_segments": supplier_segments or [],
        "geo_regions": geo_regions or [],
        "jti": jti,
        "iat": now,
        "nbf": now,
        "exp": expire,
    }
    if extra_claims:
        payload.update(extra_claims)

    # For HS256 (dev/test), sign with the key path value directly as a secret string.
    # For RS256 (prod), load the private key PEM from disk via _KeyCache.
    if settings.jwt_algorithm.startswith("HS"):
        signing_key: Any = _load_pem(settings.jwt_private_key_path).decode()
    else:
        signing_key = _KeyCache.private()
    token = jwt.encode(payload, signing_key, algorithm=settings.jwt_algorithm)
    return token, jti


def verify_access_token(token: str) -> dict[str, Any]:
    """Decode and validate an RS256 JWT access token.

    Raises:
        TokenExpiredError — if the token has expired.
        AuthenticationError — if the token is invalid, malformed, or the jti
            has been revoked in Redis.
    """
    try:
        if settings.jwt_algorithm.startswith("HS"):
            verifying_key: Any = _load_pem(settings.jwt_public_key_path).decode()
        else:
            verifying_key = _KeyCache.public()
        payload = jwt.decode(
            token,
            verifying_key,
            algorithms=[settings.jwt_algorithm],
            audience=settings.jwt_audience,
        )
    except ExpiredSignatureError as exc:
        raise TokenExpiredError("Access token has expired") from exc
    except JWTError as exc:
        raise AuthenticationError(f"Invalid access token: {exc}") from exc

    # Check Redis revocation list synchronously (caller may be async — see notes)
    _check_jti_not_revoked(payload["jti"])

    return payload


def _check_jti_not_revoked(jti: str) -> None:
    """Check the Redis blocklist for a revoked jti.

    In async contexts call the async variant; here we fall back to a
    best-effort check using the sync Redis client.  The full async guard
    is implemented in the FastAPI dependency.
    """
    try:
        import redis as redis_sync  # noqa: PLC0415
        r = redis_sync.from_url(str(settings.redis_url), decode_responses=True)
        if r.exists(f"revoked_jti:{jti}"):
            raise AuthenticationError("Token has been revoked")
    except ImportError:
        pass  # Redis not available — skip blocklist check (dev fallback only)


async def async_check_jti_not_revoked(jti: str) -> None:
    """Async jti revocation check — used inside FastAPI dependencies."""
    import redis.asyncio as aioredis  # noqa: PLC0415
    r = aioredis.from_url(str(settings.redis_url), decode_responses=True)
    async with r:
        if await r.exists(f"revoked_jti:{jti}"):
            raise AuthenticationError("Token has been revoked")


async def revoke_jti(jti: str, ttl_seconds: int | None = None) -> None:
    """Add *jti* to the Redis revocation set with an appropriate TTL."""
    import redis.asyncio as aioredis  # noqa: PLC0415
    r = aioredis.from_url(str(settings.redis_url), decode_responses=True)
    async with r:
        key = f"revoked_jti:{jti}"
        ttl = ttl_seconds or (settings.jwt_access_token_expire_minutes * 60 + 60)
        await r.setex(key, ttl, "1")


# ---------------------------------------------------------------------------
# Refresh tokens — 256-bit random, stored as SHA-256 hash in DB
# ---------------------------------------------------------------------------
REFRESH_TOKEN_BYTES = 32


def generate_refresh_token() -> tuple[str, str]:
    """Return (raw_token, sha256_hash).

    Store only *sha256_hash* in the database.  Return *raw_token* to the client.
    """
    raw = secrets.token_urlsafe(REFRESH_TOKEN_BYTES)
    digest = hashlib.sha256(raw.encode()).hexdigest()
    return raw, digest


def hash_refresh_token(raw: str) -> str:
    """Hash a raw refresh token for DB storage / lookup."""
    return hashlib.sha256(raw.encode()).hexdigest()


# ---------------------------------------------------------------------------
# TOTP — RFC 6238
# ---------------------------------------------------------------------------
TOTP_ISSUER = "SCVRI"
TOTP_DIGITS = 6
TOTP_INTERVAL = 30


def generate_totp_secret() -> str:
    """Return a base32-encoded TOTP secret."""
    return pyotp.random_base32()


def get_totp_uri(secret: str, email: str, tenant_name: str) -> str:
    """Return an otpauth:// provisioning URI for QR code generation."""
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL)
    return totp.provisioning_uri(name=email, issuer_name=f"{TOTP_ISSUER} ({tenant_name})")


def verify_totp(secret: str, code: str, valid_window: int = 1) -> bool:
    """Verify a TOTP *code* against *secret*.

    *valid_window* allows ±N intervals of clock drift.  Default is 1 (±30 sec).
    """
    totp = pyotp.TOTP(secret, digits=TOTP_DIGITS, interval=TOTP_INTERVAL)
    return totp.verify(code, valid_window=valid_window)


# ---------------------------------------------------------------------------
# Backup codes — 10 × 8-char alphanumeric codes
# ---------------------------------------------------------------------------
BACKUP_CODE_COUNT = 10
BACKUP_CODE_LEN = 8


def generate_backup_codes() -> list[str]:
    """Return *BACKUP_CODE_COUNT* plain-text backup codes.

    Caller must hash each code (hash_password) before storing.
    """
    return [
        secrets.token_urlsafe(BACKUP_CODE_LEN)[:BACKUP_CODE_LEN].upper()
        for _ in range(BACKUP_CODE_COUNT)
    ]


def verify_backup_code(plain_code: str, hashed_codes: list[str]) -> tuple[bool, int]:
    """Return (is_valid, index_used).

    Caller must remove the used code from *hashed_codes* after successful verification.
    """
    for idx, hashed in enumerate(hashed_codes):
        if verify_password(plain_code.upper(), hashed):
            return True, idx
    return False, -1


# ---------------------------------------------------------------------------
# Password policy validation
# ---------------------------------------------------------------------------
_COMPLEXITY_REQUIREMENTS = {
    "min_length": 12,
    "require_uppercase": True,
    "require_lowercase": True,
    "require_digits": True,
    "require_special": True,
}
_SPECIAL_CHARS = set("!@#$%^&*()_+-=[]{}|;':\",./<>?")


def validate_password_complexity(password: str) -> list[str]:
    """Return a list of policy violations (empty list means password is acceptable)."""
    errors: list[str] = []
    if len(password) < _COMPLEXITY_REQUIREMENTS["min_length"]:
        errors.append(f"Password must be at least {_COMPLEXITY_REQUIREMENTS['min_length']} characters.")
    if _COMPLEXITY_REQUIREMENTS["require_uppercase"] and not any(c.isupper() for c in password):
        errors.append("Password must contain at least one uppercase letter.")
    if _COMPLEXITY_REQUIREMENTS["require_lowercase"] and not any(c.islower() for c in password):
        errors.append("Password must contain at least one lowercase letter.")
    if _COMPLEXITY_REQUIREMENTS["require_digits"] and not any(c.isdigit() for c in password):
        errors.append("Password must contain at least one digit.")
    if _COMPLEXITY_REQUIREMENTS["require_special"] and not any(c in _SPECIAL_CHARS for c in password):
        errors.append("Password must contain at least one special character.")
    return errors
