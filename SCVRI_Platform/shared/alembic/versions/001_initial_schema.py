"""Initial schema — all SCVRI platform tables, indexes, RLS, triggers, Citus distribution.

Revision ID: 001_initial
Revises: 
Create Date: 2026-03-04

IMPORTANT: Run this against a fresh Citus + PostgreSQL 15 database.
The migration:
  1. Creates all schemas
  2. Creates all enum types
  3. Creates all tables with constraints
  4. Creates indexes
  5. Configures Row-Level Security (RLS)
  6. Installs immutability trigger on audit_log
  7. Installs search_tsv trigger on suppliers
  8. Installs sla_deadline trigger on erasure_requests
  9. Distributes tables via Citus
  10. Creates reference tables (tenants, roles)
  11. Sets up initial system roles
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, UUID, TSVECTOR

revision = "001_initial"
down_revision = None
branch_labels = None
depends_on = None


# ============================================================
# UPGRADE
# ============================================================
def upgrade() -> None:
    _create_schemas()
    _create_enums()
    _create_tables()
    _create_indexes()
    _configure_rls()
    _create_triggers()
    _configure_citus()
    _seed_roles()


# ============================================================
# DOWNGRADE
# ============================================================
def downgrade() -> None:
    _drop_triggers()
    _drop_tables()
    _drop_enums()
    _drop_schemas()


# ===========================================================================
# STEP 1 — Schemas
# ===========================================================================
def _create_schemas() -> None:
    for schema in ("platform", "auth", "supplier", "supply_chain", "risk", "alerting", "compliance", "audit"):
        op.execute(f"CREATE SCHEMA IF NOT EXISTS {schema}")


def _drop_schemas() -> None:
    for schema in ("platform", "auth", "supplier", "supply_chain", "risk", "alerting", "compliance", "audit"):
        op.execute(f"DROP SCHEMA IF EXISTS {schema} CASCADE")


# ===========================================================================
# STEP 2 — Enum Types
# ===========================================================================
def _create_enums() -> None:
    op.execute("""
        DO $$ BEGIN
            -- Platform
            CREATE TYPE platform.tenant_plan_enum AS ENUM ('starter','professional','enterprise');
            CREATE TYPE platform.aws_region_enum AS ENUM ('us-east-1','eu-west-1');
            CREATE TYPE platform.sso_provider_enum AS ENUM ('saml','oidc');

            -- Auth
            CREATE TYPE auth.role_name_enum AS ENUM (
                'supply_chain_executive','supply_chain_manager','procurement_officer',
                'risk_analyst','compliance_officer','it_administrator','ml_lead','supplier_portal_user'
            );
            CREATE TYPE auth.mfa_type_enum AS ENUM ('totp','fido2','backup_code');

            -- Supplier
            CREATE TYPE supplier.onboarding_status_enum AS ENUM (
                'pending_onboarding','questionnaire_sent','questionnaire_in_progress',
                'documents_requested','under_review','compliance_check','approved','rejected','active'
            );
            CREATE TYPE supplier.supplier_status_enum AS ENUM ('draft','active','suspended','deactivated','banned');
            CREATE TYPE supplier.supplier_tier_enum AS ENUM ('strategic','preferred','standard','one_time');
            CREATE TYPE supplier.score_grade_enum AS ENUM ('A','B','C','D');
            CREATE TYPE supplier.contact_type_enum AS ENUM ('primary','commercial','technical','legal','sustainability');
            CREATE TYPE supplier.document_type_enum AS ENUM (
                'certification','financial_statement','insurance','questionnaire','contract','other'
            );
            CREATE TYPE supplier.doc_upload_status_enum AS ENUM ('pending','scanning','clean','infected','failed');

            -- Supply chain
            CREATE TYPE supply_chain.po_status_enum AS ENUM (
                'draft','submitted','acknowledged','in_production','shipped',
                'partially_received','received','invoiced','closed','cancelled'
            );
            CREATE TYPE supply_chain.shipment_status_enum AS ENUM (
                'booked','in_transit','at_port','customs_hold','out_for_delivery',
                'delivered','exception','returned','cancelled'
            );
            CREATE TYPE supply_chain.transport_mode_enum AS ENUM ('ocean','air','road','rail','multimodal');

            -- Risk
            CREATE TYPE risk.risk_level_enum AS ENUM ('critical','high','medium','low');
            CREATE TYPE risk.threshold_dir_enum AS ENUM ('above','below');
            CREATE TYPE risk.breach_level_enum AS ENUM ('warning','critical');

            -- Alerting
            CREATE TYPE alerting.alert_status_enum AS ENUM ('open','acknowledged','in_progress','resolved','suppressed');
            CREATE TYPE alerting.alert_severity_enum AS ENUM ('critical','high','medium','low','informational');
            CREATE TYPE alerting.notification_channel_enum AS ENUM ('email','slack','teams','sms','pagerduty','webhook');
            CREATE TYPE alerting.notif_status_enum AS ENUM ('pending','sent','delivered','failed','skipped');

            -- Compliance
            CREATE TYPE compliance.erasure_status_enum AS ENUM (
                'received','scope_identified','soft_deleted','cascade_deleted',
                'pseudonymised','completed','partially_completed','failed','sla_escalated'
            );
            CREATE TYPE compliance.right_type_enum AS ENUM (
                'erasure','access','portability','rectification','restriction','objection','ccpa_opt_out'
            );
            CREATE TYPE compliance.legal_basis_enum AS ENUM (
                'contract','legitimate_interests','consent','legal_obligation','vital_interests','public_task'
            );
        EXCEPTION
            WHEN duplicate_object THEN NULL;
        END $$;
    """)


def _drop_enums() -> None:
    # Dropped automatically via CASCADE when schemas are dropped.
    pass


def _drop_tables() -> None:
    # All tables live inside the platform schemas; they are dropped via
    # CASCADE when _drop_schemas() runs.  This function exists so the
    # downgrade() call order is explicit and mirrors upgrade().
    pass


# ===========================================================================
# STEP 3 — Tables
# ===========================================================================
def _create_tables() -> None:
    # ------------------------------------------------------------------ #
    # platform.tenants
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS platform.tenants (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            VARCHAR(255) NOT NULL,
            slug            VARCHAR(100) NOT NULL UNIQUE,
            domain          VARCHAR(255),
            plan            platform.tenant_plan_enum NOT NULL DEFAULT 'enterprise',
            max_suppliers   INT NOT NULL DEFAULT 10000,
            max_users       INT NOT NULL DEFAULT 500,
            api_rate_limit_per_minute INT NOT NULL DEFAULT 2000,
            data_region     platform.aws_region_enum NOT NULL DEFAULT 'us-east-1',
            sso_enabled     BOOLEAN NOT NULL DEFAULT FALSE,
            sso_provider    platform.sso_provider_enum,
            sso_metadata    JSONB,
            is_active       BOOLEAN NOT NULL DEFAULT TRUE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ------------------------------------------------------------------ #
    # auth.roles
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth.roles (
            id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
            name            auth.role_name_enum NOT NULL UNIQUE,
            display_name    VARCHAR(200) NOT NULL,
            description     TEXT,
            permissions     JSONB NOT NULL DEFAULT '{}',
            is_mfa_required BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
        )
    """)

    # ------------------------------------------------------------------ #
    # auth.users
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth.users (
            id                      UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL REFERENCES platform.tenants(id),
            email                   VARCHAR(500) NOT NULL,
            first_name              VARCHAR(200) NOT NULL,
            last_name               VARCHAR(200) NOT NULL,
            display_name            VARCHAR(300),
            password_hash           VARCHAR(200),
            must_reset_password     BOOLEAN NOT NULL DEFAULT FALSE,
            password_changed_at     TIMESTAMPTZ,
            previous_password_hashes JSONB,
            sso_subject             VARCHAR(500),
            sso_provider            VARCHAR(100),
            mfa_enabled             BOOLEAN NOT NULL DEFAULT FALSE,
            mfa_type                auth.mfa_type_enum,
            totp_secret_encrypted   TEXT,
            fido2_credentials       JSONB,
            backup_codes_hash       JSONB,
            is_active               BOOLEAN NOT NULL DEFAULT TRUE,
            is_mfa_required         BOOLEAN NOT NULL DEFAULT FALSE,
            failed_login_attempts   INT NOT NULL DEFAULT 0,
            locked_until            TIMESTAMPTZ,
            last_login_at           TIMESTAMPTZ,
            last_login_ip           VARCHAR(45),
            procurement_categories  JSONB,
            supplier_segments       JSONB,
            geo_regions             JSONB,
            ccpa_opt_out            BOOLEAN NOT NULL DEFAULT FALSE,
            is_deleted              BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at              TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            UNIQUE (tenant_id, email)
        )
    """)

    # ------------------------------------------------------------------ #
    # auth.user_roles
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth.user_roles (
            id          UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id   UUID NOT NULL,
            user_id     UUID NOT NULL,
            role_id     UUID NOT NULL REFERENCES auth.roles(id),
            granted_by  UUID,
            expires_at  TIMESTAMPTZ,
            created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            UNIQUE (tenant_id, user_id, role_id),
            FOREIGN KEY (user_id, tenant_id) REFERENCES auth.users(id, tenant_id) ON DELETE CASCADE
        )
    """)

    # ------------------------------------------------------------------ #
    # auth.refresh_tokens
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS auth.refresh_tokens (
            id                  UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            user_id             UUID NOT NULL,
            jti                 VARCHAR(100) NOT NULL UNIQUE,
            token_hash          VARCHAR(200) NOT NULL,
            family              VARCHAR(100) NOT NULL,
            is_revoked          BOOLEAN NOT NULL DEFAULT FALSE,
            revoked_at          TIMESTAMPTZ,
            expires_at          TIMESTAMPTZ NOT NULL,
            issued_at           TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            device_fingerprint  VARCHAR(200),
            ip_address          VARCHAR(45),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            FOREIGN KEY (user_id, tenant_id) REFERENCES auth.users(id, tenant_id) ON DELETE CASCADE
        )
    """)

    # ------------------------------------------------------------------ #
    # supplier.suppliers
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier.suppliers (
            id                  UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            legal_name          VARCHAR(500) NOT NULL,
            trading_name        VARCHAR(500),
            duns_number         VARCHAR(9),
            tax_id              VARCHAR(50),
            registration_number VARCHAR(100),
            status              supplier.supplier_status_enum NOT NULL DEFAULT 'draft',
            onboarding_status   supplier.onboarding_status_enum NOT NULL DEFAULT 'pending_onboarding',
            tier                supplier.supplier_tier_enum NOT NULL DEFAULT 'standard',
            primary_category    VARCHAR(200),
            secondary_categories VARCHAR(200)[],
            commodity_codes     VARCHAR(20)[],
            country_code        VARCHAR(2) NOT NULL,
            state_province      VARCHAR(100),
            city                VARCHAR(200),
            postal_code         VARCHAR(20),
            address_line_1      VARCHAR(500),
            address_line_2      VARCHAR(500),
            geo_region          VARCHAR(50),
            annual_revenue_usd  NUMERIC(18,2),
            employee_count      INT,
            credit_rating       VARCHAR(10),
            is_wbe              BOOLEAN NOT NULL DEFAULT FALSE,
            is_mbe              BOOLEAN NOT NULL DEFAULT FALSE,
            is_lgbtbe           BOOLEAN NOT NULL DEFAULT FALSE,
            is_veteran_owned    BOOLEAN NOT NULL DEFAULT FALSE,
            is_disability_owned BOOLEAN NOT NULL DEFAULT FALSE,
            is_hbcu_affiliated  BOOLEAN NOT NULL DEFAULT FALSE,
            search_tsv          TSVECTOR,
            erp_vendor_id       VARCHAR(100),
            erp_system          VARCHAR(50),
            metadata            JSONB,
            internal_notes      TEXT,
            is_deleted          BOOLEAN NOT NULL DEFAULT FALSE,
            deleted_at          TIMESTAMPTZ,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            UNIQUE (tenant_id, duns_number),
            UNIQUE (tenant_id, tax_id)
        )
    """)

    # ------------------------------------------------------------------ #
    # supplier.supplier_contacts
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier.supplier_contacts (
            id              UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            supplier_id     UUID NOT NULL,
            contact_type    supplier.contact_type_enum NOT NULL DEFAULT 'primary',
            first_name      VARCHAR(200) NOT NULL,
            last_name       VARCHAR(200) NOT NULL,
            email           VARCHAR(500) NOT NULL,
            phone           VARCHAR(50),
            title           VARCHAR(200),
            is_primary      BOOLEAN NOT NULL DEFAULT FALSE,
            is_erased       BOOLEAN NOT NULL DEFAULT FALSE,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            FOREIGN KEY (supplier_id, tenant_id) REFERENCES supplier.suppliers(id, tenant_id) ON DELETE CASCADE
        )
    """)

    # ------------------------------------------------------------------ #
    # supplier.supplier_certifications
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier.supplier_certifications (
            id              UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            supplier_id     UUID NOT NULL,
            cert_type       VARCHAR(100) NOT NULL,
            cert_number     VARCHAR(200),
            issuing_body    VARCHAR(200),
            issue_date      DATE,
            expiry_date     DATE,
            is_verified     BOOLEAN NOT NULL DEFAULT FALSE,
            verified_by     UUID,
            verified_at     TIMESTAMPTZ,
            document_id     UUID,
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            FOREIGN KEY (supplier_id, tenant_id) REFERENCES supplier.suppliers(id, tenant_id) ON DELETE CASCADE
        )
    """)

    # ------------------------------------------------------------------ #
    # supplier.supplier_documents
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier.supplier_documents (
            id              UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            supplier_id     UUID NOT NULL,
            filename        VARCHAR(500) NOT NULL,
            content_type    VARCHAR(100) NOT NULL,
            size_bytes      BIGINT NOT NULL,
            s3_bucket       VARCHAR(200) NOT NULL,
            s3_key          VARCHAR(1000) NOT NULL,
            s3_version_id   VARCHAR(200),
            document_type   supplier.document_type_enum NOT NULL DEFAULT 'other',
            upload_status   supplier.doc_upload_status_enum NOT NULL DEFAULT 'pending',
            uploaded_by     UUID,
            checksum_sha256 VARCHAR(64),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            FOREIGN KEY (supplier_id, tenant_id) REFERENCES supplier.suppliers(id, tenant_id) ON DELETE CASCADE
        )
    """)

    # ------------------------------------------------------------------ #
    # supplier.supplier_scorecards
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS supplier.supplier_scorecards (
            id                      UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            supplier_id             UUID NOT NULL,
            period_start            DATE NOT NULL,
            period_end              DATE NOT NULL,
            total_deliveries        INT NOT NULL DEFAULT 0,
            on_time_deliveries      INT NOT NULL DEFAULT 0,
            items_ordered           INT NOT NULL DEFAULT 0,
            items_received          INT NOT NULL DEFAULT 0,
            returned_items          INT NOT NULL DEFAULT 0,
            invoice_discrepancy_pct NUMERIC(5,2) NOT NULL DEFAULT 0.00,
            otd_rate                NUMERIC(5,4) NOT NULL DEFAULT 0.0000,
            defect_rate             NUMERIC(5,4) NOT NULL DEFAULT 0.0000,
            fill_rate               NUMERIC(5,4) NOT NULL DEFAULT 0.0000,
            invoice_accuracy        NUMERIC(5,2) NOT NULL DEFAULT 100.00,
            overall_score           NUMERIC(5,2) NOT NULL DEFAULT 0.00,
            grade                   supplier.score_grade_enum NOT NULL DEFAULT 'D',
            formula_version         VARCHAR(20) NOT NULL DEFAULT '1.0',
            computed_by             VARCHAR(50) NOT NULL DEFAULT 'celery_worker',
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            FOREIGN KEY (supplier_id, tenant_id) REFERENCES supplier.suppliers(id, tenant_id) ON DELETE CASCADE
        )
    """)

    # ------------------------------------------------------------------ #
    # supply_chain.purchase_orders
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS supply_chain.purchase_orders (
            id                      UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            po_number               VARCHAR(100) NOT NULL,
            supplier_id             UUID NOT NULL,
            status                  supply_chain.po_status_enum NOT NULL DEFAULT 'draft',
            po_date                 DATE NOT NULL,
            required_delivery_date  DATE,
            confirmed_delivery_date DATE,
            actual_delivery_date    DATE,
            currency                VARCHAR(3) NOT NULL DEFAULT 'USD',
            total_amount            NUMERIC(18,2) NOT NULL DEFAULT 0.00,
            invoiced_amount         NUMERIC(18,2) NOT NULL DEFAULT 0.00,
            payment_terms           VARCHAR(100),
            incoterms               VARCHAR(10),
            country_of_origin       VARCHAR(2),
            is_at_risk              BOOLEAN NOT NULL DEFAULT FALSE,
            risk_flags              JSONB,
            erp_po_id               VARCHAR(200),
            erp_system              VARCHAR(50),
            erp_last_synced_at      TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            UNIQUE (tenant_id, po_number),
            FOREIGN KEY (supplier_id, tenant_id) REFERENCES supplier.suppliers(id, tenant_id)
        )
    """)

    # ------------------------------------------------------------------ #
    # supply_chain.po_line_items
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS supply_chain.po_line_items (
            id                  UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            po_id               UUID NOT NULL,
            line_number         INT NOT NULL,
            item_number         VARCHAR(200),
            description         TEXT NOT NULL,
            quantity_ordered    NUMERIC(14,4) NOT NULL,
            quantity_received   NUMERIC(14,4) NOT NULL DEFAULT 0.0000,
            unit_of_measure     VARCHAR(20) NOT NULL,
            unit_price          NUMERIC(18,6) NOT NULL,
            line_total          NUMERIC(18,2) NOT NULL,
            commodity_code      VARCHAR(20),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            FOREIGN KEY (po_id, tenant_id) REFERENCES supply_chain.purchase_orders(id, tenant_id) ON DELETE CASCADE
        )
    """)

    # ------------------------------------------------------------------ #
    # supply_chain.shipments
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS supply_chain.shipments (
            id                  UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            tracking_number     VARCHAR(200),
            bill_of_lading      VARCHAR(200),
            carrier_name        VARCHAR(200),
            carrier_scac        VARCHAR(4),
            transport_mode      supply_chain.transport_mode_enum,
            status              supply_chain.shipment_status_enum NOT NULL DEFAULT 'booked',
            po_id               UUID NOT NULL,
            supplier_id         UUID NOT NULL,
            origin_country      VARCHAR(2),
            origin_port         VARCHAR(10),
            destination_country VARCHAR(2),
            destination_port    VARCHAR(10),
            current_location    VARCHAR(200),
            current_latitude    NUMERIC(10,7),
            current_longitude   NUMERIC(10,7),
            departed_at         TIMESTAMPTZ,
            estimated_arrival   TIMESTAMPTZ,
            actual_arrival      TIMESTAMPTZ,
            is_delayed          BOOLEAN NOT NULL DEFAULT FALSE,
            delay_days          INT,
            delay_reason        VARCHAR(500),
            erp_shipment_id     VARCHAR(200),
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            FOREIGN KEY (po_id, tenant_id) REFERENCES supply_chain.purchase_orders(id, tenant_id),
            FOREIGN KEY (supplier_id, tenant_id) REFERENCES supplier.suppliers(id, tenant_id)
        )
    """)

    # ------------------------------------------------------------------ #
    # supply_chain.shipment_events
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS supply_chain.shipment_events (
            id              UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            shipment_id     UUID NOT NULL,
            event_type      VARCHAR(100) NOT NULL,
            location        VARCHAR(300),
            description     TEXT,
            occurred_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            source          VARCHAR(50),
            created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            FOREIGN KEY (shipment_id, tenant_id) REFERENCES supply_chain.shipments(id, tenant_id) ON DELETE CASCADE
        )
    """)

    # ------------------------------------------------------------------ #
    # supply_chain.iot_telemetry (partitioned)
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS supply_chain.iot_telemetry (
            id                  UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            shipment_id         UUID NOT NULL,
            device_id           VARCHAR(100) NOT NULL,
            recorded_at         TIMESTAMPTZ NOT NULL,
            temperature_celsius NUMERIC(6,2),
            humidity_pct        NUMERIC(5,2),
            shock_g             NUMERIC(6,3),
            latitude            NUMERIC(10,7),
            longitude           NUMERIC(10,7),
            is_breach           BOOLEAN NOT NULL DEFAULT FALSE,
            breach_type         VARCHAR(50),
            thresholds          JSONB,
            PRIMARY KEY (id, tenant_id, recorded_at),
            FOREIGN KEY (shipment_id, tenant_id) REFERENCES supply_chain.shipments(id, tenant_id) ON DELETE CASCADE
        ) PARTITION BY RANGE (recorded_at)
    """)
    # Create initial monthly partitions
    for year, month, next_month, end_year in [
        (2024, 1, 2, 2024), (2024, 2, 3, 2024), (2024, 3, 4, 2024),
        (2024, 4, 5, 2024), (2024, 5, 6, 2024), (2024, 6, 7, 2024),
        (2024, 7, 8, 2024), (2024, 8, 9, 2024), (2024, 9, 10, 2024),
        (2024, 10, 11, 2024), (2024, 11, 12, 2024), (2024, 12, 1, 2025),
        (2025, 1, 2, 2025), (2025, 2, 3, 2025), (2025, 3, 4, 2025),
        (2025, 4, 5, 2025), (2025, 5, 6, 2025), (2025, 6, 7, 2025),
        (2025, 7, 8, 2025), (2025, 8, 9, 2025), (2025, 9, 10, 2025),
        (2025, 10, 11, 2025), (2025, 11, 12, 2025), (2025, 12, 1, 2026),
        (2026, 1, 2, 2026), (2026, 2, 3, 2026), (2026, 3, 4, 2026),
        (2026, 4, 5, 2026), (2026, 5, 6, 2026), (2026, 6, 7, 2026),
    ]:
        end_m = next_month if next_month > 1 else 1
        end_y = end_year if next_month > 1 else end_year + 1
        op.execute(f"""
            CREATE TABLE IF NOT EXISTS supply_chain.iot_telemetry_{year}_{month:02d}
            PARTITION OF supply_chain.iot_telemetry
            FOR VALUES FROM ('{year}-{month:02d}-01') TO ('{end_y}-{end_m:02d}-01')
        """)

    # ------------------------------------------------------------------ #
    # risk.supplier_risk_scores
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk.supplier_risk_scores (
            id                      UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            supplier_id             UUID NOT NULL,
            composite_score         NUMERIC(5,2) NOT NULL,
            risk_level              risk.risk_level_enum NOT NULL,
            financial_score         NUMERIC(5,2),
            operational_score       NUMERIC(5,2),
            geopolitical_score      NUMERIC(5,2),
            esg_score               NUMERIC(5,2),
            delivery_score          NUMERIC(5,2),
            model_version           VARCHAR(50),
            model_run_id            VARCHAR(100),
            features_snapshot       JSONB,
            shap_values             JSONB,
            is_overridden           BOOLEAN NOT NULL DEFAULT FALSE,
            override_score          NUMERIC(5,2),
            override_reason         TEXT,
            overridden_by           UUID,
            overridden_at           TIMESTAMPTZ,
            scored_at               TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            next_scheduled_rescore  TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            UNIQUE (tenant_id, supplier_id),
            FOREIGN KEY (supplier_id, tenant_id) REFERENCES supplier.suppliers(id, tenant_id)
        )
    """)

    # ------------------------------------------------------------------ #
    # risk.risk_score_history (partitioned quarterly)
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk.risk_score_history (
            id                  UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            supplier_id         UUID NOT NULL,
            composite_score     NUMERIC(5,2) NOT NULL,
            risk_level          risk.risk_level_enum NOT NULL,
            trigger_event       VARCHAR(100),
            trigger_event_id    VARCHAR(200),
            model_version       VARCHAR(50),
            scored_at           TIMESTAMPTZ NOT NULL,
            PRIMARY KEY (id, tenant_id, scored_at)
        ) PARTITION BY RANGE (scored_at)
    """)
    for year in [2024, 2025, 2026, 2027]:
        for q, m_start, m_end in [(1, 1, 4), (2, 4, 7), (3, 7, 10), (4, 10, 1)]:
            end_y = year if q < 4 else year + 1
            op.execute(f"""
                CREATE TABLE IF NOT EXISTS risk.risk_score_history_{year}_q{q}
                PARTITION OF risk.risk_score_history
                FOR VALUES FROM ('{year}-{m_start:02d}-01')
                    TO ('{end_y}-{m_end if q < 4 else 1:02d}-01')
            """)

    # ------------------------------------------------------------------ #
    # risk.kri_definitions
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk.kri_definitions (
            id                  UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            kri_code            VARCHAR(50) NOT NULL,
            name                VARCHAR(200) NOT NULL,
            description         TEXT,
            category            VARCHAR(50) NOT NULL,
            unit                VARCHAR(30) NOT NULL,
            warning_threshold   NUMERIC(10,4),
            critical_threshold  NUMERIC(10,4),
            threshold_direction risk.threshold_dir_enum NOT NULL DEFAULT 'above',
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            weight_in_composite NUMERIC(4,3) NOT NULL DEFAULT 0.000,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            UNIQUE (tenant_id, kri_code)
        )
    """)

    # ------------------------------------------------------------------ #
    # risk.kri_snapshots (partitioned quarterly)
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk.kri_snapshots (
            id              UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id       UUID NOT NULL,
            kri_id          UUID NOT NULL,
            supplier_id     UUID NOT NULL,
            snapshot_date   TIMESTAMPTZ NOT NULL,
            value           NUMERIC(14,4) NOT NULL,
            breach_level    risk.breach_level_enum,
            source          VARCHAR(100),
            PRIMARY KEY (id, tenant_id, snapshot_date)
        ) PARTITION BY RANGE (snapshot_date)
    """)
    for year in [2024, 2025, 2026, 2027]:
        for q, m_start, m_end in [(1, 1, 4), (2, 4, 7), (3, 7, 10), (4, 10, 1)]:
            end_y = year if q < 4 else year + 1
            op.execute(f"""
                CREATE TABLE IF NOT EXISTS risk.kri_snapshots_{year}_q{q}
                PARTITION OF risk.kri_snapshots
                FOR VALUES FROM ('{year}-{m_start:02d}-01')
                    TO ('{end_y}-{m_end if q < 4 else 1:02d}-01')
            """)

    # ------------------------------------------------------------------ #
    # risk.risk_rules
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS risk.risk_rules (
            id                  UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            rule_code           VARCHAR(50) NOT NULL,
            name                VARCHAR(200) NOT NULL,
            description         TEXT,
            is_system           BOOLEAN NOT NULL DEFAULT FALSE,
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            condition_dsl       JSONB NOT NULL,
            severity            risk.risk_level_enum NOT NULL,
            alert_title_template    VARCHAR(500) NOT NULL,
            alert_body_template     TEXT NOT NULL,
            recommended_actions JSONB,
            dedup_window_seconds    INT NOT NULL DEFAULT 3600,
            created_by          UUID,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            UNIQUE (tenant_id, rule_code)
        )
    """)

    # ------------------------------------------------------------------ #
    # alerting.alerts (partitioned quarterly)
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS alerting.alerts (
            id                      UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            rule_id                 UUID,
            rule_code               VARCHAR(50),
            supplier_id             UUID,
            shipment_id             UUID,
            trigger_event_id        VARCHAR(200),
            trigger_event_type      VARCHAR(100),
            title                   VARCHAR(500) NOT NULL,
            body                    TEXT NOT NULL,
            severity                alerting.alert_severity_enum NOT NULL,
            status                  alerting.alert_status_enum NOT NULL DEFAULT 'open',
            recommended_actions     JSONB,
            context_data            JSONB,
            assigned_to             UUID,
            acknowledged_by         UUID,
            acknowledged_at         TIMESTAMPTZ,
            resolved_by             UUID,
            resolved_at             TIMESTAMPTZ,
            resolution_notes        TEXT,
            dedup_key               VARCHAR(300),
            escalation_level        INT NOT NULL DEFAULT 0,
            last_escalated_at       TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id, created_at)
        ) PARTITION BY RANGE (created_at)
    """)
    for year in [2024, 2025, 2026, 2027]:
        for q, m_start, m_end in [(1, 1, 4), (2, 4, 7), (3, 7, 10), (4, 10, 1)]:
            end_y = year if q < 4 else year + 1
            op.execute(f"""
                CREATE TABLE IF NOT EXISTS alerting.alerts_{year}_q{q}
                PARTITION OF alerting.alerts
                FOR VALUES FROM ('{year}-{m_start:02d}-01')
                    TO ('{end_y}-{m_end if q < 4 else 1:02d}-01')
            """)

    # ------------------------------------------------------------------ #
    # alerting.alert_escalations
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS alerting.alert_escalations (
            id                      UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            alert_id                UUID NOT NULL,
            from_level              INT NOT NULL,
            to_level                INT NOT NULL,
            escalated_to_user_id    UUID,
            escalated_to_role       VARCHAR(100),
            reason                  TEXT,
            escalated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id)
        )
    """)

    # ------------------------------------------------------------------ #
    # alerting.notification_log
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS alerting.notification_log (
            id                      UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            alert_id                UUID NOT NULL,
            channel                 alerting.notification_channel_enum NOT NULL,
            recipient               VARCHAR(500) NOT NULL,
            status                  alerting.notif_status_enum NOT NULL DEFAULT 'pending',
            attempt_count           INT NOT NULL DEFAULT 0,
            last_attempt_at         TIMESTAMPTZ,
            next_retry_at           TIMESTAMPTZ,
            error_message           TEXT,
            external_message_id     VARCHAR(500),
            sent_at                 TIMESTAMPTZ,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id)
        )
    """)

    # ------------------------------------------------------------------ #
    # alerting.notification_subscriptions
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS alerting.notification_subscriptions (
            id                  UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            user_id             UUID,
            role                VARCHAR(100),
            channel             alerting.notification_channel_enum NOT NULL,
            destination         VARCHAR(1000) NOT NULL,
            severity_filter     JSONB,
            rule_filter         JSONB,
            is_active           BOOLEAN NOT NULL DEFAULT TRUE,
            created_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id)
        )
    """)

    # ------------------------------------------------------------------ #
    # alerting.webhook_endpoints
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS alerting.webhook_endpoints (
            id                      UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            endpoint_url            VARCHAR(2000) NOT NULL,
            signing_secret_encrypted TEXT NOT NULL,
            events_subscribed       JSONB NOT NULL,
            is_active               BOOLEAN NOT NULL DEFAULT TRUE,
            failure_count           INT NOT NULL DEFAULT 0,
            last_success_at         TIMESTAMPTZ,
            last_failure_at         TIMESTAMPTZ,
            created_by              UUID,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id),
            UNIQUE (tenant_id, endpoint_url)
        )
    """)

    # ------------------------------------------------------------------ #
    # compliance.erasure_requests
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS compliance.erasure_requests (
            id                      UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            right_type              compliance.right_type_enum NOT NULL DEFAULT 'erasure',
            status                  compliance.erasure_status_enum NOT NULL DEFAULT 'received',
            data_subject_email      VARCHAR(500) NOT NULL,
            data_subject_user_id    UUID,
            requestor_name          VARCHAR(400),
            requestor_email         VARCHAR(500),
            sla_deadline            TIMESTAMPTZ NOT NULL,
            sla_escalated           BOOLEAN NOT NULL DEFAULT FALSE,
            scope_summary           JSONB,
            completed_at            TIMESTAMPTZ,
            processed_by            VARCHAR(100),
            notes                   TEXT,
            audit_retained          BOOLEAN NOT NULL DEFAULT TRUE,
            audit_retention_basis   TEXT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id)
        )
    """)

    # ------------------------------------------------------------------ #
    # compliance.data_processing_records
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS compliance.data_processing_records (
            id                      UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            processing_activity     VARCHAR(300) NOT NULL,
            purpose                 TEXT NOT NULL,
            legal_basis             compliance.legal_basis_enum NOT NULL,
            data_categories         JSONB NOT NULL,
            data_subjects           JSONB NOT NULL,
            recipients              JSONB,
            retention_period        VARCHAR(100) NOT NULL,
            third_country_transfers BOOLEAN NOT NULL DEFAULT FALSE,
            transfer_safeguards     TEXT,
            dpia_required           BOOLEAN NOT NULL DEFAULT FALSE,
            dpia_completed_at       TIMESTAMPTZ,
            is_active               BOOLEAN NOT NULL DEFAULT TRUE,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id)
        )
    """)

    # ------------------------------------------------------------------ #
    # compliance.consent_records
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS compliance.consent_records (
            id                      UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id               UUID NOT NULL,
            user_id                 UUID NOT NULL,
            consent_type            VARCHAR(200) NOT NULL,
            is_granted              BOOLEAN NOT NULL,
            granted_at              TIMESTAMPTZ,
            withdrawn_at            TIMESTAMPTZ,
            consent_text_version    VARCHAR(50) NOT NULL,
            ip_address              VARCHAR(45),
            user_agent              TEXT,
            created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            PRIMARY KEY (id, tenant_id)
        )
    """)

    # ------------------------------------------------------------------ #
    # audit.audit_log (partitioned quarterly)
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE TABLE IF NOT EXISTS audit.audit_log (
            id                  UUID NOT NULL DEFAULT gen_random_uuid(),
            tenant_id           UUID NOT NULL,
            actor_id            UUID,
            actor_email         VARCHAR(500),
            actor_role          VARCHAR(100),
            actor_ip            VARCHAR(45),
            actor_user_agent    TEXT,
            event_type          VARCHAR(200) NOT NULL,
            event_time          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
            correlation_id      VARCHAR(100),
            resource_type       VARCHAR(100),
            resource_id         VARCHAR(200),
            action              VARCHAR(50) NOT NULL,
            old_values          JSONB,
            new_values          JSONB,
            metadata            JSONB,
            service_name        VARCHAR(100),
            service_version     VARCHAR(50),
            PRIMARY KEY (id, tenant_id, event_time)
        ) PARTITION BY RANGE (event_time)
    """)
    for year in [2024, 2025, 2026, 2027, 2028, 2029, 2030, 2031]:
        for q, m_start, m_end in [(1, 1, 4), (2, 4, 7), (3, 7, 10), (4, 10, 1)]:
            end_y = year if q < 4 else year + 1
            op.execute(f"""
                CREATE TABLE IF NOT EXISTS audit.audit_log_{year}_q{q}
                PARTITION OF audit.audit_log
                FOR VALUES FROM ('{year}-{m_start:02d}-01')
                    TO ('{end_y}-{m_end if q < 4 else 1:02d}-01')
            """)


# ===========================================================================
# STEP 4 — Indexes
# ===========================================================================
def _create_indexes() -> None:
    op.execute("""
        -- Tenant
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tenants_slug ON platform.tenants(slug);

        -- Users
        CREATE INDEX IF NOT EXISTS idx_users_tenant_email ON auth.users(tenant_id, email);
        CREATE INDEX IF NOT EXISTS idx_users_tenant_active ON auth.users(tenant_id) WHERE is_active = TRUE AND is_deleted = FALSE;

        -- Refresh tokens
        CREATE UNIQUE INDEX IF NOT EXISTS idx_refresh_jti ON auth.refresh_tokens(jti);
        CREATE INDEX IF NOT EXISTS idx_refresh_user ON auth.refresh_tokens(tenant_id, user_id);
        CREATE INDEX IF NOT EXISTS idx_refresh_expires ON auth.refresh_tokens(expires_at) WHERE is_revoked = FALSE;

        -- Suppliers
        CREATE INDEX IF NOT EXISTS idx_suppliers_tenant_name ON supplier.suppliers(tenant_id, legal_name);
        CREATE INDEX IF NOT EXISTS idx_suppliers_search_tsv ON supplier.suppliers USING GIN (search_tsv);
        CREATE INDEX IF NOT EXISTS idx_suppliers_status ON supplier.suppliers(tenant_id, status) WHERE is_deleted = FALSE;
        CREATE INDEX IF NOT EXISTS idx_suppliers_onboarding ON supplier.suppliers(tenant_id, onboarding_status) WHERE is_deleted = FALSE;
        CREATE INDEX IF NOT EXISTS idx_suppliers_country ON supplier.suppliers(tenant_id, country_code) WHERE is_deleted = FALSE;

        -- Certifications
        CREATE INDEX IF NOT EXISTS idx_certs_supplier ON supplier.supplier_certifications(tenant_id, supplier_id);
        CREATE INDEX IF NOT EXISTS idx_certs_expiry ON supplier.supplier_certifications(tenant_id, expiry_date);

        -- Purchase Orders
        CREATE INDEX IF NOT EXISTS idx_po_tenant_supplier ON supply_chain.purchase_orders(tenant_id, supplier_id);
        CREATE INDEX IF NOT EXISTS idx_po_tenant_date ON supply_chain.purchase_orders(tenant_id, po_date);
        CREATE INDEX IF NOT EXISTS idx_po_status ON supply_chain.purchase_orders(tenant_id, status);

        -- Shipments
        CREATE INDEX IF NOT EXISTS idx_shipment_po ON supply_chain.shipments(tenant_id, po_id);
        CREATE INDEX IF NOT EXISTS idx_shipment_supplier ON supply_chain.shipments(tenant_id, supplier_id);
        CREATE INDEX IF NOT EXISTS idx_shipment_status ON supply_chain.shipments(tenant_id, status);
        CREATE INDEX IF NOT EXISTS idx_shipment_eta ON supply_chain.shipments(tenant_id, estimated_arrival);

        -- Risk scores
        CREATE UNIQUE INDEX IF NOT EXISTS idx_risk_score_supplier ON risk.supplier_risk_scores(tenant_id, supplier_id);
        CREATE INDEX IF NOT EXISTS idx_risk_level ON risk.supplier_risk_scores(tenant_id, risk_level);
        CREATE INDEX IF NOT EXISTS idx_risk_composite ON risk.supplier_risk_scores(tenant_id, composite_score DESC);

        -- Alerts
        CREATE INDEX IF NOT EXISTS idx_alert_tenant_status ON alerting.alerts(tenant_id, status);
        CREATE INDEX IF NOT EXISTS idx_alert_severity ON alerting.alerts(tenant_id, severity);
        CREATE INDEX IF NOT EXISTS idx_alert_supplier ON alerting.alerts(tenant_id, supplier_id);
        CREATE INDEX IF NOT EXISTS idx_alert_dedup ON alerting.alerts(tenant_id, dedup_key) WHERE dedup_key IS NOT NULL;

        -- Erasure requests
        CREATE INDEX IF NOT EXISTS idx_erasure_sla ON compliance.erasure_requests(tenant_id, sla_deadline, status);
        CREATE INDEX IF NOT EXISTS idx_erasure_email ON compliance.erasure_requests(tenant_id, data_subject_email);

        -- Audit log
        CREATE INDEX IF NOT EXISTS idx_audit_actor ON audit.audit_log(tenant_id, actor_id);
        CREATE INDEX IF NOT EXISTS idx_audit_resource ON audit.audit_log(tenant_id, resource_type, resource_id);
        CREATE INDEX IF NOT EXISTS idx_audit_event_type ON audit.audit_log(tenant_id, event_type);
    """)


# ===========================================================================
# STEP 5 — Row-Level Security
# ===========================================================================
def _configure_rls() -> None:
    tables = [
        ("auth", "users"),
        ("auth", "user_roles"),
        ("auth", "refresh_tokens"),
        ("supplier", "suppliers"),
        ("supplier", "supplier_contacts"),
        ("supplier", "supplier_certifications"),
        ("supplier", "supplier_documents"),
        ("supplier", "supplier_scorecards"),
        ("supply_chain", "purchase_orders"),
        ("supply_chain", "po_line_items"),
        ("supply_chain", "shipments"),
        ("supply_chain", "shipment_events"),
        ("supply_chain", "iot_telemetry"),
        ("risk", "supplier_risk_scores"),
        ("risk", "risk_score_history"),
        ("risk", "kri_definitions"),
        ("risk", "kri_snapshots"),
        ("risk", "risk_rules"),
        ("alerting", "alerts"),
        ("alerting", "alert_escalations"),
        ("alerting", "notification_log"),
        ("alerting", "notification_subscriptions"),
        ("alerting", "webhook_endpoints"),
        ("compliance", "erasure_requests"),
        ("compliance", "data_processing_records"),
        ("compliance", "consent_records"),
        ("audit", "audit_log"),
    ]
    for schema, table in tables:
        fqn = f"{schema}.{table}"
        op.execute(f"ALTER TABLE {fqn} ENABLE ROW LEVEL SECURITY")
        op.execute(f"ALTER TABLE {fqn} FORCE ROW LEVEL SECURITY")
        op.execute(f"""
            CREATE POLICY tenant_isolation ON {fqn}
            USING (tenant_id = current_setting('scvri.tenant_id', TRUE)::UUID)
        """)

    # Supplier portal isolation policy — portal users can only see their own supplier record
    op.execute("""
        CREATE POLICY supplier_portal_isolation ON supplier.suppliers
        AS RESTRICTIVE
        USING (
            id::TEXT = current_setting('scvri.supplier_id', TRUE)
            OR current_setting('scvri.is_portal_user', TRUE) = 'false'
        )
    """)


# ===========================================================================
# STEP 6 — Triggers
# ===========================================================================
def _create_triggers() -> None:
    # ------------------------------------------------------------------ #
    # Audit log immutability — prevent UPDATE and DELETE
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE OR REPLACE FUNCTION audit.prevent_audit_modification()
        RETURNS TRIGGER LANGUAGE plpgsql SECURITY DEFINER AS $$
        BEGIN
            RAISE EXCEPTION 'audit_log is append-only. Modification forbidden. (GDPR Art. 17(3)(b))';
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_audit_immutable
        BEFORE UPDATE OR DELETE ON audit.audit_log
        FOR EACH ROW EXECUTE FUNCTION audit.prevent_audit_modification()
    """)

    # ------------------------------------------------------------------ #
    # Supplier full-text search vector updater
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE OR REPLACE FUNCTION supplier.update_search_tsv()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            NEW.search_tsv :=
                setweight(to_tsvector('english', COALESCE(NEW.legal_name, '')), 'A') ||
                setweight(to_tsvector('english', COALESCE(NEW.trading_name, '')), 'B') ||
                setweight(to_tsvector('english', COALESCE(NEW.duns_number, '')), 'C') ||
                setweight(to_tsvector('english', COALESCE(NEW.erp_vendor_id, '')), 'C');
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_supplier_search_tsv
        BEFORE INSERT OR UPDATE OF legal_name, trading_name, duns_number, erp_vendor_id
        ON supplier.suppliers
        FOR EACH ROW EXECUTE FUNCTION supplier.update_search_tsv()
    """)

    # ------------------------------------------------------------------ #
    # Erasure request SLA deadline setter
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE OR REPLACE FUNCTION compliance.set_erasure_sla_deadline()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            IF NEW.sla_deadline IS NULL THEN
                NEW.sla_deadline := NEW.created_at + INTERVAL '30 days';
            END IF;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_erasure_sla_deadline
        BEFORE INSERT ON compliance.erasure_requests
        FOR EACH ROW EXECUTE FUNCTION compliance.set_erasure_sla_deadline()
    """)

    # ------------------------------------------------------------------ #
    # updated_at auto-updater for all main tables
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE OR REPLACE FUNCTION platform.update_updated_at()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$
    """)
    tables_with_updated_at = [
        "platform.tenants", "auth.roles", "auth.users", "auth.user_roles",
        "auth.refresh_tokens", "supplier.suppliers", "supplier.supplier_contacts",
        "supplier.supplier_certifications", "supplier.supplier_documents",
        "supplier.supplier_scorecards", "supply_chain.purchase_orders",
        "supply_chain.po_line_items", "supply_chain.shipments",
        "supply_chain.shipment_events", "risk.supplier_risk_scores",
        "risk.kri_definitions", "risk.risk_rules",
        "alerting.alert_escalations", "alerting.notification_log",
        "alerting.notification_subscriptions", "alerting.webhook_endpoints",
        "compliance.erasure_requests", "compliance.data_processing_records",
        "compliance.consent_records",
    ]
    for table in tables_with_updated_at:
        trigger_name = f"trg_upd_{table.replace('.', '_')}"
        op.execute(f"""
            CREATE TRIGGER {trigger_name}
            BEFORE UPDATE ON {table}
            FOR EACH ROW EXECUTE FUNCTION platform.update_updated_at()
        """)

    # ------------------------------------------------------------------ #
    # Scorecard grade classifier
    # ------------------------------------------------------------------ #
    op.execute("""
        CREATE OR REPLACE FUNCTION supplier.compute_scorecard_grade()
        RETURNS TRIGGER LANGUAGE plpgsql AS $$
        BEGIN
            -- Apply SCOR-model weighted formula
            NEW.otd_rate := CASE WHEN NEW.total_deliveries > 0
                THEN NEW.on_time_deliveries::NUMERIC / NEW.total_deliveries
                ELSE 0 END;
            NEW.defect_rate := CASE WHEN NEW.items_received > 0
                THEN NEW.returned_items::NUMERIC / NEW.items_received
                ELSE 0 END;
            NEW.fill_rate := CASE WHEN NEW.items_ordered > 0
                THEN NEW.items_received::NUMERIC / NEW.items_ordered
                ELSE 0 END;
            NEW.invoice_accuracy := 100.0 - NEW.invoice_discrepancy_pct;
            NEW.overall_score :=
                (0.35 * NEW.otd_rate * 100)
                + (0.25 * NEW.fill_rate * 100)
                + (0.25 * (1 - NEW.defect_rate) * 100)
                + (0.15 * NEW.invoice_accuracy);
            NEW.grade := CASE
                WHEN NEW.overall_score >= 90 THEN 'A'
                WHEN NEW.overall_score >= 75 THEN 'B'
                WHEN NEW.overall_score >= 60 THEN 'C'
                ELSE 'D'
            END::supplier.score_grade_enum;
            RETURN NEW;
        END;
        $$
    """)
    op.execute("""
        CREATE TRIGGER trg_scorecard_grade
        BEFORE INSERT OR UPDATE ON supplier.supplier_scorecards
        FOR EACH ROW EXECUTE FUNCTION supplier.compute_scorecard_grade()
    """)


def _drop_triggers() -> None:
    # All triggers dropped automatically with CASCADE schema drop in downgrade
    pass


# ===========================================================================
# STEP 7 — Citus Distribution (skip in non-Citus environments)
# ===========================================================================
def _configure_citus() -> None:
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'citus') THEN
                -- Reference tables (small lookup tables — replicated to all workers)
                PERFORM create_reference_table('platform.tenants');
                PERFORM create_reference_table('auth.roles');

                -- Distributed tables — sharded on tenant_id
                PERFORM create_distributed_table('auth.users', 'tenant_id');
                PERFORM create_distributed_table('auth.user_roles', 'tenant_id');
                PERFORM create_distributed_table('auth.refresh_tokens', 'tenant_id');
                PERFORM create_distributed_table('supplier.suppliers', 'tenant_id');
                PERFORM create_distributed_table('supplier.supplier_contacts', 'tenant_id');
                PERFORM create_distributed_table('supplier.supplier_certifications', 'tenant_id');
                PERFORM create_distributed_table('supplier.supplier_documents', 'tenant_id');
                PERFORM create_distributed_table('supplier.supplier_scorecards', 'tenant_id');
                PERFORM create_distributed_table('supply_chain.purchase_orders', 'tenant_id');
                PERFORM create_distributed_table('supply_chain.po_line_items', 'tenant_id');
                PERFORM create_distributed_table('supply_chain.shipments', 'tenant_id');
                PERFORM create_distributed_table('supply_chain.shipment_events', 'tenant_id');
                PERFORM create_distributed_table('supply_chain.iot_telemetry', 'tenant_id');
                PERFORM create_distributed_table('risk.supplier_risk_scores', 'tenant_id');
                PERFORM create_distributed_table('risk.risk_score_history', 'tenant_id');
                PERFORM create_distributed_table('risk.kri_definitions', 'tenant_id');
                PERFORM create_distributed_table('risk.kri_snapshots', 'tenant_id');
                PERFORM create_distributed_table('risk.risk_rules', 'tenant_id');
                PERFORM create_distributed_table('alerting.alerts', 'tenant_id');
                PERFORM create_distributed_table('alerting.alert_escalations', 'tenant_id');
                PERFORM create_distributed_table('alerting.notification_log', 'tenant_id');
                PERFORM create_distributed_table('alerting.notification_subscriptions', 'tenant_id');
                PERFORM create_distributed_table('alerting.webhook_endpoints', 'tenant_id');
                PERFORM create_distributed_table('compliance.erasure_requests', 'tenant_id');
                PERFORM create_distributed_table('audit.audit_log', 'tenant_id');
            END IF;
        END $$;
    """)


# ===========================================================================
# STEP 8 — Seed system roles
# ===========================================================================
def _seed_roles() -> None:
    roles = [
        ("supply_chain_executive", "Supply Chain Executive",
         "Read-only dashboard access across all supply chain data", False),
        ("supply_chain_manager", "Supply Chain Manager",
         "Manage POs, shipments, and supplier relationships", False),
        ("procurement_officer", "Procurement Officer",
         "Full supplier onboarding and procurement management", False),
        ("risk_analyst", "Risk Analyst",
         "View and override risk scores, manage KRIs and risk rules", True),
        ("compliance_officer", "Compliance Officer",
         "GDPR/CCPA request processing, compliance reports, audit log access", True),
        ("it_administrator", "IT Administrator",
         "User management, SSO configuration, API key management", True),
        ("ml_lead", "ML Lead",
         "Model management, cross-tenant alternate supplier pool, feature store", True),
        ("supplier_portal_user", "Supplier Portal User",
         "Scoped access to own supplier record via the onboarding portal", False),
    ]
    for name, display_name, description, is_mfa_required in roles:
        op.execute(f"""
            INSERT INTO auth.roles (name, display_name, description, permissions, is_mfa_required)
            VALUES (
                '{name}',
                '{display_name}',
                '{description}',
                '{{}}',
                {str(is_mfa_required).lower()}
            )
            ON CONFLICT (name) DO NOTHING
        """)
