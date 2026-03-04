"""Tests for JWT, bcrypt, TOTP, and backup code utilities."""
from __future__ import annotations

import time
import uuid

import pytest

from scvri_shared.exceptions import AuthenticationError, TokenExpiredError
from scvri_shared.security import (
    generate_backup_codes,
    generate_refresh_token,
    generate_totp_secret,
    get_totp_uri,
    hash_password,
    hash_refresh_token,
    validate_password_complexity,
    verify_backup_code,
    verify_password,
    verify_totp,
)


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------
class TestPasswordHashing:
    def test_hash_produces_bcrypt_hash(self) -> None:
        hashed = hash_password("P@ssword123!")
        assert hashed.startswith("$2b$")

    def test_verify_correct_password(self) -> None:
        plain = "P@ssword123!"
        assert verify_password(plain, hash_password(plain)) is True

    def test_verify_wrong_password(self) -> None:
        assert verify_password("wrong", hash_password("correct")) is False

    def test_different_hashes_for_same_password(self) -> None:
        """bcrypt uses random salt — two hashes of the same plaintext differ."""
        plain = "P@ssword123!"
        assert hash_password(plain) != hash_password(plain)

    def test_timing_constant(self) -> None:
        """verify_password should not short-circuit (constant-time)."""
        hashed = hash_password("P@ssword123!")
        t0 = time.perf_counter()
        verify_password("wrong1234!", hashed)
        t1 = time.perf_counter()
        verify_password("P@ssword123!", hashed)
        t2 = time.perf_counter()
        # Both should be in the same order of magnitude (< 10× difference)
        assert (t2 - t1) < (t1 - t0) * 10 + 0.1


# ---------------------------------------------------------------------------
# Password policy
# ---------------------------------------------------------------------------
class TestPasswordPolicy:
    def test_strong_password_passes(self) -> None:
        errors = validate_password_complexity("Sup3r!SecurePw")
        assert errors == []

    def test_too_short(self) -> None:
        errors = validate_password_complexity("Sh0rt!")
        assert any("12" in e for e in errors)

    def test_no_uppercase(self) -> None:
        errors = validate_password_complexity("p@ssw0rd!test12")
        assert any("uppercase" in e.lower() for e in errors)

    def test_no_special_char(self) -> None:
        errors = validate_password_complexity("Password123456")
        assert any("special" in e.lower() for e in errors)

    def test_no_digit(self) -> None:
        errors = validate_password_complexity("P@sswordNoDigit")
        assert any("digit" in e.lower() for e in errors)


# ---------------------------------------------------------------------------
# JWT — uses HS256 in tests (settings_override patches to HS256)
# ---------------------------------------------------------------------------
class TestJWT:
    def test_create_and_verify_access_token(self, settings_override) -> None:
        from scvri_shared.security import create_access_token, verify_access_token

        user_id = uuid.uuid4()
        tenant_id = uuid.uuid4()
        token, jti = create_access_token(
            user_id=user_id,
            tenant_id=tenant_id,
            email="test@example.com",
            role="procurement_officer",
            scopes=["suppliers:read"],
        )
        assert token
        assert jti

        payload = verify_access_token(token)
        assert payload["sub"] == str(user_id)
        assert payload["tid"] == str(tenant_id)
        assert payload["role"] == "procurement_officer"
        assert "suppliers:read" in payload["scopes"]

    def test_invalid_token_raises(self, settings_override) -> None:
        from scvri_shared.security import verify_access_token

        with pytest.raises(AuthenticationError):
            verify_access_token("not.a.valid.token")

    def test_tampered_token_raises(self, settings_override) -> None:
        from scvri_shared.security import create_access_token, verify_access_token

        token, _ = create_access_token(
            user_id=uuid.uuid4(),
            tenant_id=uuid.uuid4(),
            email="t@t.com",
            role="risk_analyst",
        )
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(AuthenticationError):
            verify_access_token(tampered)


# ---------------------------------------------------------------------------
# Refresh tokens
# ---------------------------------------------------------------------------
class TestRefreshTokens:
    def test_generate_returns_raw_and_hash(self) -> None:
        raw, digest = generate_refresh_token()
        assert raw != digest
        assert len(digest) == 64  # SHA-256 hex

    def test_hash_is_deterministic(self) -> None:
        raw, digest = generate_refresh_token()
        assert hash_refresh_token(raw) == digest

    def test_different_raw_tokens_different_hashes(self) -> None:
        _, d1 = generate_refresh_token()
        _, d2 = generate_refresh_token()
        assert d1 != d2


# ---------------------------------------------------------------------------
# TOTP
# ---------------------------------------------------------------------------
class TestTOTP:
    def test_generate_secret_is_base32(self) -> None:
        secret = generate_totp_secret()
        import base64  # noqa: PLC0415

        # Should be decodable as base32
        base64.b32decode(secret)

    def test_totp_uri_format(self) -> None:
        secret = generate_totp_secret()
        uri = get_totp_uri(secret, "admin@scvri.io", "Acme Corp")
        assert uri.startswith("otpauth://totp/")
        assert "SCVRI" in uri
        assert "Acme%20Corp" in uri or "Acme Corp" in uri

    def test_valid_code_verifies(self) -> None:
        import pyotp  # noqa: PLC0415

        secret = generate_totp_secret()
        current_code = pyotp.TOTP(secret).now()
        assert verify_totp(secret, current_code) is True

    def test_wrong_code_fails(self) -> None:
        secret = generate_totp_secret()
        assert verify_totp(secret, "000000") is False


# ---------------------------------------------------------------------------
# Backup codes
# ---------------------------------------------------------------------------
class TestBackupCodes:
    def test_generates_ten_codes(self) -> None:
        codes = generate_backup_codes()
        assert len(codes) == 10

    def test_codes_are_unique(self) -> None:
        codes = generate_backup_codes()
        assert len(set(codes)) == 10

    def test_verify_correct_code(self) -> None:
        codes = generate_backup_codes()
        hashed = [hash_password(c) for c in codes]
        valid, idx = verify_backup_code(codes[3], hashed)
        assert valid is True
        assert idx == 3

    def test_verify_wrong_code(self) -> None:
        codes = generate_backup_codes()
        hashed = [hash_password(c) for c in codes]
        valid, idx = verify_backup_code("XXXXXXXX", hashed)
        assert valid is False
        assert idx == -1
