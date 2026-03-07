"""Authentication schemas — tokens, login, MFA."""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Literal

from pydantic import EmailStr, field_validator

from scvri_shared.schemas import CamelBase


# ── Login ─────────────────────────────────────────────────────────────────────

class LoginRequest(CamelBase):
    email: EmailStr
    password: str
    tenant_id: uuid.UUID | None = None   # optional — resolved from email domain if omitted


class LoginResponse(CamelBase):
    """Returned on successful password auth (no MFA) or after MFA verification."""
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int                       # seconds until access_token expires
    user_id: uuid.UUID
    tenant_id: uuid.UUID
    role: str


class MFAChallengeResponse(CamelBase):
    """Returned when MFA is required — client must call /auth/mfa/verify."""
    mfa_required: bool = True
    mfa_method: Literal["totp"]
    session_token: str                    # short-lived, single-use token for MFA step


class MFAVerifyRequest(CamelBase):
    session_token: str
    code: str                             # 6-digit TOTP code

    @field_validator("code")
    @classmethod
    def six_digits(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 6:
            raise ValueError("TOTP code must be exactly 6 digits")
        return v


# ── Token refresh ─────────────────────────────────────────────────────────────

class TokenRefreshRequest(CamelBase):
    refresh_token: str


class TokenRefreshResponse(CamelBase):
    access_token: str
    refresh_token: str                    # rotated on each refresh
    token_type: str = "bearer"
    expires_in: int


# ── MFA provisioning ──────────────────────────────────────────────────────────

class TOTPSetupResponse(CamelBase):
    """Returned when user initiates TOTP setup."""
    secret: str                           # base32-encoded TOTP secret
    provisioning_uri: str                 # otpauth:// URI for QR code
    qr_code_data_uri: str                 # data:image/png;base64,... for inline render


class TOTPVerifyRequest(CamelBase):
    """Confirm TOTP setup by submitting first valid code."""
    code: str

    @field_validator("code")
    @classmethod
    def six_digits(cls, v: str) -> str:
        v = v.strip()
        if not v.isdigit() or len(v) != 6:
            raise ValueError("TOTP code must be exactly 6 digits")
        return v


class TOTPDisableRequest(CamelBase):
    """Disable MFA — requires current password confirmation."""
    current_password: str


# ── Password reset flow ───────────────────────────────────────────────────────

class PasswordResetRequestIn(CamelBase):
    email: EmailStr


class PasswordResetConfirm(CamelBase):
    token: str
    new_password: str

    @field_validator("new_password")
    @classmethod
    def strength(cls, v: str) -> str:
        if len(v) < 8:
            raise ValueError("password must be at least 8 characters")
        return v


# ── JWT token payload (internal) ──────────────────────────────────────────────

class AccessTokenClaims(CamelBase):
    sub: str                   # user_id (UUID string)
    tenant_id: str
    role: str
    email: str
    iat: int
    exp: int
    jti: str                   # unique token ID (for revocation)
    token_type: Literal["access"] = "access"


class RefreshTokenClaims(CamelBase):
    sub: str
    tenant_id: str
    jti: str
    iat: int
    exp: int
    token_type: Literal["refresh"] = "refresh"
