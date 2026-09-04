"""Pydantic schemas for Supplier entities."""
from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Annotated, Any

from pydantic import EmailStr, Field, HttpUrl, field_validator, model_validator

from scvri_shared.schemas import CamelBase, TimestampSchema

# ---------------------------------------------------------------------------
# Enums mirrored from SQLAlchemy models (used in Pydantic validators)
# ---------------------------------------------------------------------------
VALID_STATUSES = {"draft", "active", "suspended", "deactivated", "banned", "inactive"}
VALID_ONBOARDING = {
    "draft", "submitted", "under_review", "returned", "approved", "rejected", "active", "suspended", "inactive",
    "pending_onboarding", "questionnaire_sent", "questionnaire_in_progress",
    "documents_requested", "compliance_check",
}

VALID_TIERS = {
    "strategic", "preferred", "standard", "one_time",
    "tier_1", "tier_2", "tier_3", "tier_4",
}


# ---------------------------------------------------------------------------
# Supplier Contact schemas
# ---------------------------------------------------------------------------
class ContactCreate(CamelBase):
    contact_type: str = "primary"
    first_name: str = Field(min_length=1, max_length=200)
    last_name: str = Field(min_length=1, max_length=200)
    email: EmailStr
    phone: str | None = Field(default=None, max_length=50)
    title: str | None = Field(default=None, max_length=200)
    is_primary: bool = False


class ContactUpdate(CamelBase):
    contact_type: str | None = None
    first_name: str | None = Field(default=None, min_length=1, max_length=200)
    last_name: str | None = Field(default=None, min_length=1, max_length=200)
    email: EmailStr | None = None
    phone: str | None = None
    title: str | None = None
    is_primary: bool | None = None


class ContactResponse(TimestampSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_id: uuid.UUID
    contact_type: str
    first_name: str
    last_name: str
    email: str
    phone: str | None
    title: str | None
    is_primary: bool
    is_erased: bool


# ---------------------------------------------------------------------------
# Supplier Certification schemas
# ---------------------------------------------------------------------------
class CertificationCreate(CamelBase):
    cert_type: str = Field(min_length=1, max_length=100)
    cert_number: str | None = Field(default=None, max_length=200)
    issuing_body: str | None = Field(default=None, max_length=200)
    issue_date: date | None = None
    expiry_date: date | None = None
    document_id: uuid.UUID | None = None


class CertificationResponse(TimestampSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    supplier_id: uuid.UUID
    cert_type: str
    cert_number: str | None
    issuing_body: str | None
    issue_date: date | None
    expiry_date: date | None
    is_verified: bool
    verified_by: uuid.UUID | None
    verified_at: datetime | None
    document_id: uuid.UUID | None


# ---------------------------------------------------------------------------
# Supplier Diversity flags
# ---------------------------------------------------------------------------
class DiversityInfo(CamelBase):
    is_wbe: bool = False
    is_mbe: bool = False
    is_lgbtbe: bool = False
    is_veteran_owned: bool = False
    is_disability_owned: bool = False
    is_hbcu_affiliated: bool = False


# ---------------------------------------------------------------------------
# Supplier Create / Update
# ---------------------------------------------------------------------------
class SupplierCreate(CamelBase):
    name: str | None = None
    legal_name: str = Field(default="", max_length=500)
    trading_name: str | None = Field(default=None, max_length=500)
    duns_number: str | None = Field(default=None, min_length=9, max_length=9)
    tax_id: str | None = Field(default=None, max_length=50)
    registration_number: str | None = Field(default=None, max_length=100)
    country_code: str = Field(min_length=2, max_length=2)
    state_province: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, max_length=200)
    postal_code: str | None = Field(default=None, max_length=20)
    address_line_1: str | None = Field(default=None, max_length=500)
    address_line_2: str | None = Field(default=None, max_length=500)
    geo_region: str | None = Field(default=None, max_length=50)
    tier: str = Field(default="standard")
    supplier_tier: str | None = None
    industry_code: str | None = Field(default=None, max_length=50)
    primary_category: str | None = Field(default=None, max_length=200)
    secondary_categories: list[str] | None = None
    commodity_codes: list[str] | None = None
    annual_revenue_usd: float | None = None
    employee_count: int | None = Field(default=None, ge=0)
    erp_vendor_id: str | None = Field(default=None, max_length=100)
    erp_system: str | None = Field(default=None, max_length=50)
    diversity: DiversityInfo = Field(default_factory=DiversityInfo)
    metadata: dict[str, Any] | None = None
    internal_notes: str | None = None

    # Initial contacts (optional — can be added separately)
    contacts: list[ContactCreate] = Field(default_factory=list)

    @model_validator(mode="before")
    @classmethod
    def _normalize_fields(cls, data: Any) -> Any:
        if isinstance(data, dict):
            if not data.get("legal_name") and data.get("name"):
                data["legal_name"] = data["name"]
            elif not data.get("name") and data.get("legal_name"):
                data["name"] = data["legal_name"]
            if "supplier_tier" in data:
                data["tier"] = data["supplier_tier"]
        return data

    @model_validator(mode="after")
    def _validate_required_name(self) -> "SupplierCreate":
        if not self.legal_name and not self.name:
            raise ValueError("legal_name or name is required")
        if not self.legal_name:
            self.legal_name = self.name or ""
        return self

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: str) -> str:
        if v not in VALID_TIERS:
            raise ValueError(f"tier must be one of {VALID_TIERS}")
        return v

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, v: str) -> str:
        return v.upper()



class SupplierUpdate(CamelBase):
    trading_name: str | None = Field(default=None, max_length=500)
    duns_number: str | None = Field(default=None, min_length=9, max_length=9)
    tax_id: str | None = Field(default=None, max_length=50)
    registration_number: str | None = Field(default=None, max_length=100)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    state_province: str | None = None
    city: str | None = None
    postal_code: str | None = None
    address_line_1: str | None = None
    address_line_2: str | None = None
    geo_region: str | None = None
    tier: str | None = None
    primary_category: str | None = None
    secondary_categories: list[str] | None = None
    commodity_codes: list[str] | None = None
    annual_revenue_usd: float | None = None
    employee_count: int | None = None
    erp_vendor_id: str | None = None
    erp_system: str | None = None
    diversity: DiversityInfo | None = None
    metadata: dict[str, Any] | None = None
    internal_notes: str | None = None
    credit_rating: str | None = Field(default=None, max_length=10)

    @field_validator("tier")
    @classmethod
    def validate_tier(cls, v: str | None) -> str | None:
        if v is not None and v not in VALID_TIERS:
            raise ValueError(f"tier must be one of {VALID_TIERS}")
        return v


# ---------------------------------------------------------------------------
# Supplier Response
# ---------------------------------------------------------------------------
class SupplierSummary(CamelBase):
    """Lightweight supplier representation for list endpoints."""
    id: uuid.UUID
    tenant_id: uuid.UUID
    legal_name: str
    trading_name: str | None
    status: str
    onboarding_status: str
    tier: str
    primary_category: str | None
    country_code: str
    risk_level: str | None = None   # joined from risk scores
    overall_score: float | None = None  # joined from scorecards
    created_at: datetime
    updated_at: datetime


class SupplierResponse(TimestampSchema):
    id: uuid.UUID
    tenant_id: uuid.UUID
    legal_name: str
    trading_name: str | None
    duns_number: str | None
    registration_number: str | None
    status: str
    onboarding_status: str
    tier: str
    primary_category: str | None
    secondary_categories: list[str] | None
    commodity_codes: list[str] | None
    country_code: str
    state_province: str | None
    city: str | None
    postal_code: str | None
    address_line_1: str | None
    address_line_2: str | None
    geo_region: str | None
    annual_revenue_usd: float | None
    employee_count: int | None
    credit_rating: str | None
    is_wbe: bool
    is_mbe: bool
    is_lgbtbe: bool
    is_veteran_owned: bool
    is_disability_owned: bool
    is_hbcu_affiliated: bool
    erp_vendor_id: str | None
    erp_system: str | None
    metadata: dict[str, Any] | None
    contacts: list[ContactResponse] = Field(default_factory=list)
    certifications: list[CertificationResponse] = Field(default_factory=list)

    # Omit sensitive fields (tax_id) from default response
    # PII fields returned only to compliance_officer / it_administrator roles


# ---------------------------------------------------------------------------
# Supplier search request
# ---------------------------------------------------------------------------
class SupplierSearchRequest(CamelBase):
    query: str | None = Field(default=None, min_length=1, max_length=500)
    status: list[str] | None = None
    tier: list[str] | None = None
    onboarding_status: list[str] | None = None
    country_codes: list[str] | None = None
    primary_category: str | None = None
    geo_region: str | None = None
    is_wbe: bool | None = None
    is_mbe: bool | None = None
    min_overall_score: float | None = Field(default=None, ge=0, le=100)
    max_overall_score: float | None = Field(default=None, ge=0, le=100)
    risk_level: str | None = None
    page: int = Field(default=1, ge=1)
    page_size: int = Field(default=20, ge=1, le=200)
    sort_by: str = "legal_name"
    sort_dir: str = "asc"


# ---------------------------------------------------------------------------
# Onboarding state transition
# ---------------------------------------------------------------------------
class OnboardingTransitionRequest(CamelBase):
    target_status: str
    reason: str | None = Field(default=None, max_length=1000)
    metadata: dict[str, Any] | None = None

    @field_validator("target_status")
    @classmethod
    def validate_target(cls, v: str) -> str:
        if v not in VALID_ONBOARDING:
            raise ValueError(f"target_status must be one of {VALID_ONBOARDING}")
        return v


# ---------------------------------------------------------------------------
# Batch operations
# ---------------------------------------------------------------------------
class BulkSupplierStatusUpdate(CamelBase):
    supplier_ids: list[uuid.UUID] = Field(min_length=1, max_length=100)
    status: str

    @field_validator("status")
    @classmethod
    def validate_status(cls, v: str) -> str:
        if v not in VALID_STATUSES:
            raise ValueError(f"status must be one of {VALID_STATUSES}")
        return v
