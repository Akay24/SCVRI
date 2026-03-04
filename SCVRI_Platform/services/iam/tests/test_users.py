"""Tests for user service and user schema validation."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.conftest import TENANT_ID, USER_ID, TEST_EMAIL, TEST_PASSWORD, make_user_row


# ── Schema validation ──────────────────────────────────────────────────────────

class TestUserCreateValidation:
    def test_valid_user(self):
        from iam.schemas.user import UserCreate

        u = UserCreate(
            email="alice@acme.io",
            full_name="Alice Smith",
            password="Password1",
            role="viewer",
            tenant_id=TENANT_ID,
        )
        assert u.email == "alice@acme.io"

    def test_password_too_short(self):
        from pydantic import ValidationError
        from iam.schemas.user import UserCreate

        with pytest.raises(ValidationError, match="at least 8"):
            UserCreate(
                email="a@b.io",
                full_name="A",
                password="Short1",
                role="viewer",
                tenant_id=TENANT_ID,
            )

    def test_password_no_uppercase(self):
        from pydantic import ValidationError
        from iam.schemas.user import UserCreate

        with pytest.raises(ValidationError, match="uppercase"):
            UserCreate(
                email="a@b.io",
                full_name="A",
                password="password1",
                role="viewer",
                tenant_id=TENANT_ID,
            )

    def test_password_no_digit(self):
        from pydantic import ValidationError
        from iam.schemas.user import UserCreate

        with pytest.raises(ValidationError, match="digit"):
            UserCreate(
                email="a@b.io",
                full_name="A",
                password="Password",
                role="viewer",
                tenant_id=TENANT_ID,
            )

    def test_invalid_email_rejected(self):
        from pydantic import ValidationError
        from iam.schemas.user import UserCreate

        with pytest.raises(ValidationError):
            UserCreate(
                email="not-an-email",
                full_name="A",
                password="Password1",
                role="viewer",
                tenant_id=TENANT_ID,
            )

    def test_invalid_role_rejected(self):
        from pydantic import ValidationError
        from iam.schemas.user import UserCreate

        with pytest.raises(ValidationError):
            UserCreate(
                email="a@b.io",
                full_name="A",
                password="Password1",
                role="superuser",  # not a valid PlatformRole
                tenant_id=TENANT_ID,
            )


# ── SCIM name extraction ───────────────────────────────────────────────────────

class TestSCIMSchemas:
    def test_scim_user_name_display_name(self):
        from iam.schemas.user import SCIMUserName

        name = SCIMUserName(givenName="Bob", familyName="Jones")
        assert name.givenName == "Bob"
        assert name.familyName == "Jones"

    def test_scim_user_response_schemas(self):
        from iam.schemas.user import SCIMUserResponse, SCIMEmail, SCIMUserName

        r = SCIMUserResponse(
            id=USER_ID,
            userName=TEST_EMAIL,
            name=SCIMUserName(givenName="Alice", familyName="Smith"),
            emails=[SCIMEmail(value=TEST_EMAIL, primary=True)],
            active=True,
            meta={
                "resourceType": "User",
                "location": f"https://scvri.io/scim/v2/Users/{USER_ID}",
            },
        )
        assert r.userName == TEST_EMAIL
        assert r.active is True


# ── user_service.create_user ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_create_user_success(mock_db):
    from iam.services.user_service import create_user
    from iam.schemas.user import UserCreate, UserResponse

    payload = UserCreate(
        email=TEST_EMAIL,
        full_name="Alice Smith",
        password=TEST_PASSWORD,
        role="viewer",
        tenant_id=TENANT_ID,
    )
    created_row = make_user_row()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one=lambda: created_row)
    ))

    result = await create_user(mock_db, payload)
    assert isinstance(result, UserResponse)
    assert result.email == TEST_EMAIL
    mock_db.execute.assert_called_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_create_user_duplicate_email(mock_db):
    from sqlalchemy.exc import IntegrityError
    from iam.services.user_service import create_user
    from iam.schemas.user import UserCreate
    from scvri_shared.exceptions import ConflictError

    payload = UserCreate(
        email=TEST_EMAIL,
        full_name="Alice",
        password=TEST_PASSWORD,
        role="viewer",
        tenant_id=TENANT_ID,
    )

    mock_db.execute = AsyncMock(side_effect=IntegrityError("duplicate", {}, Exception()))

    with pytest.raises(ConflictError):
        await create_user(mock_db, payload)


# ── user_service.get_user ──────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_user_success(mock_db):
    from iam.services.user_service import get_user

    row = make_user_row()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: row)
    ))

    result = await get_user(mock_db, TENANT_ID, USER_ID)
    assert result.user_id == USER_ID


@pytest.mark.asyncio
async def test_get_user_not_found(mock_db):
    from iam.services.user_service import get_user
    from scvri_shared.exceptions import NotFoundError

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: None)
    ))

    with pytest.raises(NotFoundError):
        await get_user(mock_db, TENANT_ID, uuid.uuid4())


# ── user_service.list_users ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_list_users_returns_list(mock_db):
    from iam.services.user_service import list_users

    rows = [make_user_row(), make_user_row(email="bob@acme.io")]
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(all=lambda: rows)
    ))

    result = await list_users(mock_db, TENANT_ID)
    assert len(result) == 2


@pytest.mark.asyncio
async def test_list_users_empty(mock_db):
    from iam.services.user_service import list_users

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(all=lambda: [])
    ))

    result = await list_users(mock_db, TENANT_ID)
    assert result == []


# ── user_service.update_user ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_update_user_role(mock_db):
    from iam.services.user_service import update_user
    from iam.schemas.user import UserUpdate

    updated_row = make_user_row(role="risk_analyst")
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: updated_row)
    ))

    result = await update_user(mock_db, TENANT_ID, USER_ID, UserUpdate(role="risk_analyst"))
    assert result.role == "risk_analyst"
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_update_user_not_found(mock_db):
    from iam.services.user_service import update_user
    from iam.schemas.user import UserUpdate
    from scvri_shared.exceptions import NotFoundError

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: None)
    ))

    with pytest.raises(NotFoundError):
        await update_user(mock_db, TENANT_ID, uuid.uuid4(), UserUpdate(status="inactive"))


# ── user_service.delete_user ───────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_delete_user_soft_deletes(mock_db):
    from iam.services.user_service import delete_user

    # delete_user typically issues an UPDATE, then checks rowcount or returns None
    mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=1))

    await delete_user(mock_db, TENANT_ID, USER_ID)
    mock_db.execute.assert_awaited_once()
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_delete_user_not_found(mock_db):
    from iam.services.user_service import delete_user
    from scvri_shared.exceptions import NotFoundError

    mock_db.execute = AsyncMock(return_value=MagicMock(rowcount=0))

    with pytest.raises(NotFoundError):
        await delete_user(mock_db, TENANT_ID, uuid.uuid4())


# ── user_service.change_password ──────────────────────────────────────────────

@pytest.mark.asyncio
async def test_change_password_success(mock_db):
    from iam.services.user_service import change_password
    from iam.schemas.user import UserPasswordChange

    row = make_user_row()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: row)
    ))

    payload = UserPasswordChange(
        current_password=TEST_PASSWORD,
        new_password="NewPassword2",
    )

    # Should complete without raising
    await change_password(mock_db, TENANT_ID, USER_ID, payload)
    mock_db.commit.assert_awaited_once()


@pytest.mark.asyncio
async def test_change_password_wrong_current(mock_db):
    from iam.services.user_service import change_password
    from iam.schemas.user import UserPasswordChange
    from scvri_shared.exceptions import AuthenticationError

    row = make_user_row()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: row)
    ))

    payload = UserPasswordChange(
        current_password="WrongCurrent1",
        new_password="NewPassword2",
    )

    with pytest.raises(AuthenticationError):
        await change_password(mock_db, TENANT_ID, USER_ID, payload)


@pytest.mark.asyncio
async def test_change_password_user_not_found(mock_db):
    from iam.services.user_service import change_password
    from iam.schemas.user import UserPasswordChange
    from scvri_shared.exceptions import NotFoundError

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: None)
    ))

    payload = UserPasswordChange(
        current_password=TEST_PASSWORD,
        new_password="NewPassword2",
    )

    with pytest.raises(NotFoundError):
        await change_password(mock_db, TENANT_ID, uuid.uuid4(), payload)


# ── user_service.get_user_by_email ────────────────────────────────────────────

@pytest.mark.asyncio
async def test_get_user_by_email_found(mock_db):
    from iam.services.user_service import get_user_by_email

    row = make_user_row()
    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: row)
    ))

    result = await get_user_by_email(mock_db, TENANT_ID, TEST_EMAIL)
    assert result is not None
    assert result.email == TEST_EMAIL


@pytest.mark.asyncio
async def test_get_user_by_email_not_found(mock_db):
    from iam.services.user_service import get_user_by_email

    mock_db.execute = AsyncMock(return_value=MagicMock(
        mappings=lambda: MagicMock(one_or_none=lambda: None)
    ))

    result = await get_user_by_email(mock_db, TENANT_ID, "nobody@x.io")
    assert result is None
