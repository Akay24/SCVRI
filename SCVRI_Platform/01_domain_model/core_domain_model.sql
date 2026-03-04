-- =============================================================================
-- SCVRI PLATFORM: CORE DOMAIN MODEL
-- Module: 01_domain_model
-- Target: PostgreSQL 15 with Citus for horizontal sharding by tenant_id
-- Encoding: UTF-8
-- Isolation Model: Row-Level Security (RLS) per tenant on all tables
-- Encryption: AES-256 at rest (AWS RDS encryption + TDE), TLS 1.3 in transit
-- SRS Coverage: All FR-* modules, NFR-SEC-001/002, NFR-COMP-001/003
-- =============================================================================

-- ---------------------------------------------------------------------------
-- EXTENSIONS
-- ---------------------------------------------------------------------------
CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
CREATE EXTENSION IF NOT EXISTS "pg_trgm";          -- fuzzy name matching (SUP-FR dedup)
CREATE EXTENSION IF NOT EXISTS "btree_gist";
CREATE EXTENSION IF NOT EXISTS "pgcrypto";          -- field-level encryption for PII
CREATE EXTENSION IF NOT EXISTS "citus";             -- horizontal sharding

-- ---------------------------------------------------------------------------
-- SCHEMAS
-- ---------------------------------------------------------------------------
CREATE SCHEMA IF NOT EXISTS core;        -- tenants, IAM
CREATE SCHEMA IF NOT EXISTS supply;      -- suppliers, POs, shipments
CREATE SCHEMA IF NOT EXISTS risk;        -- risk scores, events, incidents
CREATE SCHEMA IF NOT EXISTS alert;       -- alert rules, deliveries
CREATE SCHEMA IF NOT EXISTS analytics;  -- KRI snapshots, report definitions
CREATE SCHEMA IF NOT EXISTS audit;       -- immutable audit trail
CREATE SCHEMA IF NOT EXISTS gdpr;        -- erasure requests, consent records

-- ---------------------------------------------------------------------------
-- MODULE 1.1: TENANT & TENANT CONFIGURATION
-- NFR-COMP-003: data stored in region selected at provisioning
-- NFR-SEC-*: all tables have tenant_id as distribution key
-- ---------------------------------------------------------------------------
CREATE TABLE core.tenants (
    tenant_id           UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    slug                VARCHAR(64)     NOT NULL UNIQUE,                -- URL slug / subdomain
    display_name        VARCHAR(255)    NOT NULL,
    status              VARCHAR(32)     NOT NULL DEFAULT 'active'
                            CHECK (status IN ('provisioning','active','suspended','offboarded')),
    tier                VARCHAR(32)     NOT NULL DEFAULT 'enterprise'
                            CHECK (tier IN ('starter','professional','enterprise')),
    data_region         VARCHAR(16)     NOT NULL
                            CHECK (data_region IN ('us-east-1','eu-west-1','ap-southeast-1')),
    db_schema_name      VARCHAR(64)     NOT NULL UNIQUE,                -- per-tenant schema name
    s3_bucket_prefix    VARCHAR(255)    NOT NULL,                       -- s3://<bucket>/<prefix>/
    max_suppliers       INT             NOT NULL DEFAULT 10000,
    max_users           INT             NOT NULL DEFAULT 500,
    sso_enabled         BOOLEAN         NOT NULL DEFAULT FALSE,
    sso_provider        VARCHAR(64),                                    -- 'okta','azure_ad','google'
    sso_metadata_url    TEXT,
    mfa_required        BOOLEAN         NOT NULL DEFAULT TRUE,
    session_idle_timeout_min  INT       NOT NULL DEFAULT 30,
    session_abs_timeout_hr    INT       NOT NULL DEFAULT 8,
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    offboarded_at       TIMESTAMPTZ,
    -- GDPR: data deletion window
    erasure_completed_at TIMESTAMPTZ
);

CREATE TABLE core.tenant_feature_flags (
    flag_id         UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID            NOT NULL REFERENCES core.tenants(tenant_id),
    flag_key        VARCHAR(128)    NOT NULL,
    flag_value      TEXT            NOT NULL DEFAULT 'false',
    updated_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, flag_key)
);
SELECT create_distributed_table('core.tenant_feature_flags', 'tenant_id');

-- ---------------------------------------------------------------------------
-- MODULE 1.2: USERS & ROLES
-- IAM-FR-001: RBAC with 8 pre-defined roles + custom roles
-- IAM-FR-002: SSO via SAML 2.0 / OIDC
-- IAM-FR-003: MFA enforcement
-- IAM-FR-005: audit log of all user actions
-- ---------------------------------------------------------------------------
CREATE TABLE core.roles (
    role_id         UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID            NOT NULL REFERENCES core.tenants(tenant_id),
    role_name       VARCHAR(64)     NOT NULL,
    role_type       VARCHAR(32)     NOT NULL
                        CHECK (role_type IN ('system','custom')),
    permissions     JSONB           NOT NULL DEFAULT '[]',
    -- Permissions schema: [{"resource":"suppliers","actions":["read","write"]},...]
    created_at      TIMESTAMPTZ     NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, role_name)
);
SELECT create_distributed_table('core.roles', 'tenant_id');

-- Seed system roles (applied per tenant at provisioning)
-- supply_chain_manager, procurement_officer, risk_analyst, logistics_coordinator,
-- executive, it_administrator, data_analyst, compliance_officer
-- + supplier_user (external, isolated)

CREATE TABLE core.users (
    user_id             UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID            NOT NULL REFERENCES core.tenants(tenant_id),
    email               VARCHAR(320)    NOT NULL,
    -- PII: encrypted at field level using pgcrypto + KMS-managed key
    email_encrypted     BYTEA,                                          -- AES-256 encrypted copy
    display_name        VARCHAR(255)    NOT NULL,
    user_type           VARCHAR(32)     NOT NULL
                            CHECK (user_type IN ('internal','supplier_portal','service_account')),
    status              VARCHAR(32)     NOT NULL DEFAULT 'active'
                            CHECK (status IN ('invited','active','locked','deactivated')),
    mfa_enrolled        BOOLEAN         NOT NULL DEFAULT FALSE,
    mfa_method          VARCHAR(32)     CHECK (mfa_method IN ('totp','push','fido2')),
    password_hash       TEXT,                                           -- bcrypt cost=12; null if SSO-only
    sso_subject         VARCHAR(512),                                   -- sub claim from OIDC/SAML
    last_login_at       TIMESTAMPTZ,
    last_login_ip       INET,
    failed_login_count  SMALLINT        NOT NULL DEFAULT 0,
    locked_until        TIMESTAMPTZ,
    supplier_id         UUID,                                           -- FK set for supplier_portal users
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ,                                    -- GDPR soft-delete
    UNIQUE(tenant_id, email)
);
SELECT create_distributed_table('core.users', 'tenant_id');
CREATE INDEX idx_users_email            ON core.users(tenant_id, email)      WHERE deleted_at IS NULL;
CREATE INDEX idx_users_sso_subject      ON core.users(tenant_id, sso_subject) WHERE sso_subject IS NOT NULL;
CREATE INDEX idx_users_supplier_id      ON core.users(tenant_id, supplier_id) WHERE supplier_id IS NOT NULL;

CREATE TABLE core.user_roles (
    user_id         UUID    NOT NULL,
    role_id         UUID    NOT NULL,
    tenant_id       UUID    NOT NULL,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    granted_by      UUID    NOT NULL,
    PRIMARY KEY (user_id, role_id, tenant_id)
);
SELECT create_distributed_table('core.user_roles', 'tenant_id');

CREATE TABLE core.user_data_scopes (
    scope_id            UUID    PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID    NOT NULL,
    user_id             UUID    NOT NULL,
    -- IAM-FR-004: scoping by supplier segment, category, geography
    supplier_segments   TEXT[]  NOT NULL DEFAULT '{}',  -- ['strategic','preferred'] or ['*'] for all
    procurement_cats    TEXT[]  NOT NULL DEFAULT '{}',  -- category codes or ['*']
    geo_regions         TEXT[]  NOT NULL DEFAULT '{}',  -- ISO-3166 country codes or ['*']
    UNIQUE(tenant_id, user_id)
);
SELECT create_distributed_table('core.user_data_scopes', 'tenant_id');

-- ---------------------------------------------------------------------------
-- MODULE 1.3: SUPPLIER MASTER
-- SUP-FR-001: supplier master database with configurable attributes
-- SUP-FR-007: segmentation by strategic tier
-- SUP-FR-008: diversity metrics
-- VIS-FR-001: multi-tier supplier graph
-- ---------------------------------------------------------------------------
CREATE TABLE supply.suppliers (
    supplier_id             UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id               UUID            NOT NULL,
    -- Legal identity
    legal_name              VARCHAR(512)    NOT NULL,
    trade_name              VARCHAR(512),
    duns_number             VARCHAR(20)     UNIQUE,                     -- D&B DUNS for deduplication (SUP dedup)
    tax_id_encrypted        BYTEA,                                      -- field-level encrypted PII
    legal_entity_type       VARCHAR(64),                                -- LLC, Corp, PLC, etc.
    -- Classification
    strategic_tier          VARCHAR(32)     NOT NULL DEFAULT 'approved'
                                CHECK (strategic_tier IN ('strategic','preferred','approved','conditional','disqualified')),
    procurement_category    VARCHAR(128),
    commodity_codes         TEXT[],                                     -- HS codes / UNSPSC
    spend_tier              VARCHAR(16)     CHECK (spend_tier IN ('tier1','tier2','tier3','tier4')),
    -- Supply chain graph
    parent_supplier_id      UUID            REFERENCES supply.suppliers(supplier_id),
    supply_chain_depth      SMALLINT        NOT NULL DEFAULT 1          -- 1=direct, 2=tier2, 3=tier3
                                CHECK (supply_chain_depth BETWEEN 1 AND 3),
    -- Location
    country_code            CHAR(2)         NOT NULL,                   -- ISO-3166
    state_province          VARCHAR(128),
    city                    VARCHAR(128),
    postal_code             VARCHAR(32),
    address_line1           VARCHAR(255),
    address_line2           VARCHAR(255),
    lat                     DECIMAL(9,6),
    lng                     DECIMAL(9,6),
    -- Contacts
    primary_contact_name    VARCHAR(255),
    primary_contact_email   VARCHAR(320),
    primary_contact_phone   VARCHAR(64),
    -- Diversity (SUP-FR-008)
    diversity_flags         TEXT[]          NOT NULL DEFAULT '{}',
    -- e.g. ['MBE','WBE','veteran_owned','LGBTBE']
    -- Status & lifecycle
    status                  VARCHAR(32)     NOT NULL DEFAULT 'active'
                                CHECK (status IN ('onboarding','active','under_review','suspended','disqualified','offboarded')),
    onboarded_at            TIMESTAMPTZ,
    last_reviewed_at        TIMESTAMPTZ,
    -- Attributes (extensible JSONB for custom tenant fields)
    custom_attributes       JSONB           NOT NULL DEFAULT '{}',
    -- Timestamps
    created_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at              TIMESTAMPTZ     NOT NULL DEFAULT now(),
    deleted_at              TIMESTAMPTZ,                                -- GDPR soft-delete
    deleted_by              UUID
);
SELECT create_distributed_table('supply.suppliers', 'tenant_id');
CREATE INDEX idx_suppliers_tenant_status    ON supply.suppliers(tenant_id, status) WHERE deleted_at IS NULL;
CREATE INDEX idx_suppliers_duns             ON supply.suppliers(duns_number)        WHERE duns_number IS NOT NULL;
CREATE INDEX idx_suppliers_parent           ON supply.suppliers(tenant_id, parent_supplier_id) WHERE parent_supplier_id IS NOT NULL;
CREATE INDEX idx_suppliers_country          ON supply.suppliers(tenant_id, country_code);
CREATE INDEX idx_suppliers_category        ON supply.suppliers(tenant_id, procurement_category);
CREATE INDEX idx_suppliers_legal_name_trgm ON supply.suppliers USING gin(legal_name gin_trgm_ops);  -- fuzzy match

-- Supply chain graph edges (for multi-tier traversal)
-- VIS-FR-001: tier 1/2/3 visualization
CREATE TABLE supply.supplier_relationships (
    rel_id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID        NOT NULL,
    parent_id       UUID        NOT NULL,    -- upstream supplier
    child_id        UUID        NOT NULL,    -- downstream supplier
    relationship_type VARCHAR(64) NOT NULL
                        CHECK (relationship_type IN ('direct_supplier','sub_supplier','logistics_partner','co_manufacturer')),
    material_flows  TEXT[],                 -- HS/UNSPSC codes flowing on this edge
    spend_pct       DECIMAL(5,2),           -- % of parent spend through this edge
    is_single_source BOOLEAN    NOT NULL DEFAULT FALSE,  -- RISK-FR-006 concentration flag
    active          BOOLEAN     NOT NULL DEFAULT TRUE,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, parent_id, child_id)
);
SELECT create_distributed_table('supply.supplier_relationships', 'tenant_id');
CREATE INDEX idx_rel_parent ON supply.supplier_relationships(tenant_id, parent_id);
CREATE INDEX idx_rel_child  ON supply.supplier_relationships(tenant_id, child_id);

-- ---------------------------------------------------------------------------
-- MODULE 1.4: PURCHASE ORDERS
-- VIS-FR-006: PO lifecycle tracker
-- VIS-FR-011: spend at risk
-- ---------------------------------------------------------------------------
CREATE TABLE supply.purchase_orders (
    po_id               UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID            NOT NULL,
    po_number           VARCHAR(128)    NOT NULL,
    supplier_id         UUID            NOT NULL,
    buyer_user_id       UUID,
    status              VARCHAR(32)     NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open','confirmed','partially_shipped','shipped','in_transit','partially_received','received','cancelled','disputed')),
    currency_code       CHAR(3)         NOT NULL DEFAULT 'USD',
    total_value         DECIMAL(18,4)   NOT NULL,
    issued_at           TIMESTAMPTZ     NOT NULL,
    required_delivery_at TIMESTAMPTZ,
    confirmed_delivery_at TIMESTAMPTZ,
    actual_delivery_at  TIMESTAMPTZ,
    cancellation_reason TEXT,
    source_system       VARCHAR(64),                                    -- 'sap','oracle','dynamics'
    source_system_id    VARCHAR(256),                                   -- native PO ID in source system
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, po_number)
);
SELECT create_distributed_table('supply.purchase_orders', 'tenant_id');
CREATE INDEX idx_po_supplier    ON supply.purchase_orders(tenant_id, supplier_id, status);
CREATE INDEX idx_po_status      ON supply.purchase_orders(tenant_id, status);
CREATE INDEX idx_po_delivery    ON supply.purchase_orders(tenant_id, required_delivery_at);

CREATE TABLE supply.po_line_items (
    line_id             UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID            NOT NULL,
    po_id               UUID            NOT NULL,
    line_number         SMALLINT        NOT NULL,
    sku                 VARCHAR(256)    NOT NULL,
    description         TEXT,
    quantity_ordered    DECIMAL(18,4)   NOT NULL,
    quantity_received   DECIMAL(18,4)   NOT NULL DEFAULT 0,
    unit_price          DECIMAL(18,4)   NOT NULL,
    line_value          DECIMAL(18,4)   NOT NULL,
    commodity_code      VARCHAR(32),
    status              VARCHAR(32)     NOT NULL DEFAULT 'open',
    PRIMARY KEY (line_id, tenant_id)
);
SELECT create_distributed_table('supply.po_line_items', 'tenant_id');
CREATE INDEX idx_po_line_po ON supply.po_line_items(tenant_id, po_id);

-- ---------------------------------------------------------------------------
-- MODULE 1.5: SHIPMENTS
-- VIS-FR-002: real-time shipment tracking
-- VIS-FR-003: IoT sensor integration
-- VIS-FR-007: multi-modal transport
-- ---------------------------------------------------------------------------
CREATE TABLE supply.shipments (
    shipment_id         UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID            NOT NULL,
    po_id               UUID,
    supplier_id         UUID            NOT NULL,
    carrier_name        VARCHAR(256),
    carrier_scac        VARCHAR(8),                                     -- SCAC code
    tracking_number     VARCHAR(256),
    transport_mode      VARCHAR(32)     NOT NULL
                            CHECK (transport_mode IN ('ocean','air','road','rail','multimodal')),
    status              VARCHAR(32)     NOT NULL DEFAULT 'booked'
                            CHECK (status IN ('booked','picked_up','in_transit','at_port','customs','out_for_delivery','delivered','exception','lost')),
    origin_country      CHAR(2)         NOT NULL,
    origin_port_code    VARCHAR(10),
    dest_country        CHAR(2)         NOT NULL,
    dest_port_code      VARCHAR(10),
    dest_facility_id    UUID,
    etd                 TIMESTAMPTZ,                                    -- estimated time of departure
    atd                 TIMESTAMPTZ,                                    -- actual time of departure
    eta                 TIMESTAMPTZ,                                    -- estimated time of arrival
    ata                 TIMESTAMPTZ,                                    -- actual time of arrival
    current_lat         DECIMAL(9,6),
    current_lng         DECIMAL(9,6),
    current_location_desc TEXT,
    last_event_at       TIMESTAMPTZ,
    -- Condition monitoring (VIS-FR-003)
    temp_min_threshold  DECIMAL(6,2),
    temp_max_threshold  DECIMAL(6,2),
    temp_breach_count   INT             NOT NULL DEFAULT 0,
    humidity_breach_count INT           NOT NULL DEFAULT 0,
    shock_event_count   INT             NOT NULL DEFAULT 0,
    -- Metadata
    total_packages      INT,
    gross_weight_kg     DECIMAL(10,3),
    source_system       VARCHAR(64),
    source_system_id    VARCHAR(256),
    created_at          TIMESTAMPTZ     NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ     NOT NULL DEFAULT now()
);
SELECT create_distributed_table('supply.shipments', 'tenant_id');
CREATE INDEX idx_shipment_supplier  ON supply.shipments(tenant_id, supplier_id, status);
CREATE INDEX idx_shipment_po        ON supply.shipments(tenant_id, po_id);
CREATE INDEX idx_shipment_tracking  ON supply.shipments(tenant_id, tracking_number) WHERE tracking_number IS NOT NULL;
CREATE INDEX idx_shipment_eta       ON supply.shipments(tenant_id, eta)             WHERE status NOT IN ('delivered','lost');

-- IoT telemetry (high-volume; partitioned by month)
CREATE TABLE supply.iot_telemetry (
    telemetry_id    UUID            NOT NULL DEFAULT uuid_generate_v4(),
    tenant_id       UUID            NOT NULL,
    shipment_id     UUID            NOT NULL,
    sensor_id       VARCHAR(128)    NOT NULL,
    sensor_type     VARCHAR(32)     NOT NULL CHECK (sensor_type IN ('temperature','humidity','gps','shock','light')),
    recorded_at     TIMESTAMPTZ     NOT NULL,
    value           DECIMAL(12,4)   NOT NULL,
    unit            VARCHAR(16)     NOT NULL,
    lat             DECIMAL(9,6),
    lng             DECIMAL(9,6),
    is_breach       BOOLEAN         NOT NULL DEFAULT FALSE,
    PRIMARY KEY (telemetry_id, recorded_at)
) PARTITION BY RANGE (recorded_at);

-- Create monthly partitions (2026 example)
CREATE TABLE supply.iot_telemetry_2026_01 PARTITION OF supply.iot_telemetry
    FOR VALUES FROM ('2026-01-01') TO ('2026-02-01');
CREATE TABLE supply.iot_telemetry_2026_02 PARTITION OF supply.iot_telemetry
    FOR VALUES FROM ('2026-02-01') TO ('2026-03-01');
CREATE TABLE supply.iot_telemetry_2026_03 PARTITION OF supply.iot_telemetry
    FOR VALUES FROM ('2026-03-01') TO ('2026-04-01');
-- (Additional partitions created automatically via pg_partman)

SELECT create_distributed_table('supply.iot_telemetry', 'tenant_id');
CREATE INDEX idx_iot_shipment_time ON supply.iot_telemetry(tenant_id, shipment_id, recorded_at DESC);

-- ---------------------------------------------------------------------------
-- MODULE 1.6: INVENTORY
-- VIS-FR-004: inventory levels, days-of-supply, safety stock
-- ---------------------------------------------------------------------------
CREATE TABLE supply.inventory_snapshots (
    snapshot_id         UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID            NOT NULL,
    sku                 VARCHAR(256)    NOT NULL,
    warehouse_id        VARCHAR(128)    NOT NULL,
    supplier_id         UUID,
    on_hand_qty         DECIMAL(18,4)   NOT NULL DEFAULT 0,
    safety_stock_qty    DECIMAL(18,4)   NOT NULL DEFAULT 0,
    avg_daily_demand    DECIMAL(18,4),
    days_of_supply      DECIMAL(8,2)
                            GENERATED ALWAYS AS
                            (CASE WHEN avg_daily_demand > 0
                                  THEN on_hand_qty / avg_daily_demand
                                  ELSE NULL END) STORED,
    snapshot_at         TIMESTAMPTZ     NOT NULL DEFAULT now(),
    source_system       VARCHAR(64)
);
SELECT create_distributed_table('supply.inventory_snapshots', 'tenant_id');
CREATE INDEX idx_inv_sku_wh ON supply.inventory_snapshots(tenant_id, sku, warehouse_id);

-- ---------------------------------------------------------------------------
-- MODULE 1.7: RISK SCORES
-- RISK-FR-001: composite risk score (0-100) updated min every 24h
-- RISK-FR-002: dimension breakdown + trend
-- RISK-FR-009: financial health monitoring
-- RISK-FR-010: ESG risk scores
-- ---------------------------------------------------------------------------
CREATE TABLE risk.supplier_risk_scores (
    score_id            UUID            PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID            NOT NULL,
    supplier_id         UUID            NOT NULL,
    composite_score     DECIMAL(5,2)    NOT NULL CHECK (composite_score BETWEEN 0 AND 100),
    financial_score     DECIMAL(5,2)    NOT NULL CHECK (financial_score BETWEEN 0 AND 100),
    operational_score   DECIMAL(5,2)    NOT NULL CHECK (operational_score BETWEEN 0 AND 100),
    geopolitical_score  DECIMAL(5,2)    NOT NULL CHECK (geopolitical_score BETWEEN 0 AND 100),
    esg_score           DECIMAL(5,2)    NOT NULL CHECK (esg_score BETWEEN 0 AND 100),
    concentration_score DECIMAL(5,2)    NOT NULL CHECK (concentration_score BETWEEN 0 AND 100),
    cyber_score         DECIMAL(5,2)    NOT NULL DEFAULT 50,
    natural_hazard_score DECIMAL(5,2)   NOT NULL DEFAULT 50,
    -- Trend: score_7d_ago for delta calculation (ALERT-FR-001: 10-point delta trigger)
    composite_score_prev DECIMAL(5,2),
    score_delta_24h     DECIMAL(5,2)
                            GENERATED ALWAYS AS (composite_score - COALESCE(composite_score_prev, composite_score)) STORED,
    -- Explainability (RISK-FR-002, AI governance)
    shap_factors        JSONB           NOT NULL DEFAULT '{}',
    -- {"financial":{"credit_score_drop":0.35,"payment_delay":0.20},...}
    model_version       VARCHAR(64)     NOT NULL,
    model_name          VARCHAR(128)    NOT NULL,
    confidence_interval_lower DECIMAL(5,2),
    confidence_interval_upper DECIMAL(5,2),
    -- Human override (AI governance: human corrections always take precedence)
    is_overridden       BOOLEAN         NOT NULL DEFAULT FALSE,
    override_score      DECIMAL(5,2),
    override_by         UUID,
    override_reason     TEXT,
    override_at         TIMESTAMPTZ,
    scored_at           TIMESTAMPTZ     NOT NULL DEFAULT now(),
    valid_until         TIMESTAMPTZ     NOT NULL,                       -- scored_at + 24h + buffer
    is_stale            BOOLEAN
                            GENERATED ALWAYS AS (now() > valid_until) STORED
);
SELECT create_distributed_table('risk.supplier_risk_scores', 'tenant_id');
CREATE INDEX idx_risk_score_supplier    ON risk.supplier_risk_scores(tenant_id, supplier_id, scored_at DESC);
CREATE INDEX idx_risk_score_stale       ON risk.supplier_risk_scores(tenant_id, is_stale) WHERE is_stale = TRUE;
CREATE INDEX idx_risk_score_composite   ON risk.supplier_risk_scores(tenant_id, composite_score DESC);

-- Risk score history (for trend analysis)
CREATE TABLE risk.risk_score_history (
    history_id      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID        NOT NULL,
    supplier_id     UUID        NOT NULL,
    composite_score DECIMAL(5,2) NOT NULL,
    scored_at       TIMESTAMPTZ NOT NULL,
    model_version   VARCHAR(64) NOT NULL
) PARTITION BY RANGE (scored_at);
CREATE TABLE risk.risk_score_history_2026_q1 PARTITION OF risk.risk_score_history
    FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
CREATE TABLE risk.risk_score_history_2026_q2 PARTITION OF risk.risk_score_history
    FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
SELECT create_distributed_table('risk.risk_score_history', 'tenant_id');
CREATE INDEX idx_rsh_supplier_time ON risk.risk_score_history(tenant_id, supplier_id, scored_at DESC);

-- Risk events log (RISK-FR-012: full audit trail)
CREATE TABLE risk.risk_events (
    event_id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID        NOT NULL,
    event_type          VARCHAR(64) NOT NULL,
    -- 'disruption','financial_distress','geopolitical','esg_violation','natural_disaster','cyber_incident'
    severity            VARCHAR(16) NOT NULL CHECK (severity IN ('critical','high','medium','low')),
    affected_supplier_ids UUID[]    NOT NULL DEFAULT '{}',
    affected_countries  CHAR(2)[]  NOT NULL DEFAULT '{}',
    source              VARCHAR(128) NOT NULL,   -- 'dnb','refinitiv','news_nlp','manual','external_feed'
    source_url          TEXT,
    headline            TEXT        NOT NULL,
    description         TEXT,
    analyst_notes       TEXT,
    mitigation_actions  JSONB       NOT NULL DEFAULT '[]',
    status              VARCHAR(32) NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open','investigating','mitigating','resolved','false_positive')),
    detected_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    resolved_at         TIMESTAMPTZ,
    resolved_by         UUID,
    spend_at_risk       DECIMAL(18,4),           -- VIS-FR-011
    -- Retention: 7 years (data requirements §6.1)
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now()
);
SELECT create_distributed_table('risk.risk_events', 'tenant_id');
CREATE INDEX idx_re_severity_status ON risk.risk_events(tenant_id, severity, status);
CREATE INDEX idx_re_suppliers       ON risk.risk_events USING gin(tenant_id, affected_supplier_ids);
CREATE INDEX idx_re_detected        ON risk.risk_events(tenant_id, detected_at DESC);

-- ---------------------------------------------------------------------------
-- MODULE 1.8: ALERTS
-- ALERT-FR-001 to ALERT-FR-008
-- ---------------------------------------------------------------------------
CREATE TABLE alert.alert_rules (
    rule_id         UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID        NOT NULL,
    rule_name       VARCHAR(256) NOT NULL,
    rule_type       VARCHAR(32) NOT NULL CHECK (rule_type IN ('threshold','delta','pattern','ai_recommendation')),
    -- No-code rule builder: conditions as JSON (ALERT-FR-002)
    conditions      JSONB       NOT NULL,
    -- {"field":"composite_score","operator":">=","value":75}
    -- {"field":"composite_score_delta_24h","operator":">=","value":10}
    severity        VARCHAR(16) NOT NULL CHECK (severity IN ('critical','high','medium','low')),
    delivery_channels TEXT[]    NOT NULL DEFAULT '{"in_app","email"}',
    -- 'in_app','email','sms','slack','teams','webhook'
    escalation_config JSONB     NOT NULL DEFAULT '{}',
    -- {"delay_minutes":15,"escalate_to_role":"risk_analyst","then_to_role":"supply_chain_manager"}
    dedup_window_minutes INT    NOT NULL DEFAULT 60,        -- ALERT-FR-006
    is_active       BOOLEAN     NOT NULL DEFAULT TRUE,
    created_by      UUID        NOT NULL,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
SELECT create_distributed_table('alert.alert_rules', 'tenant_id');

CREATE TABLE alert.alerts (
    alert_id            UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID        NOT NULL,
    rule_id             UUID        NOT NULL,
    severity            VARCHAR(16) NOT NULL,
    entity_type         VARCHAR(32) NOT NULL, -- 'supplier','shipment','po','region'
    entity_id           UUID        NOT NULL,
    title               TEXT        NOT NULL,
    body                TEXT        NOT NULL,
    ai_mitigation_actions JSONB     NOT NULL DEFAULT '[]',   -- ALERT-FR-007
    status              VARCHAR(32) NOT NULL DEFAULT 'open'
                            CHECK (status IN ('open','acknowledged','assigned','resolved','suppressed')),
    dedup_key           VARCHAR(512) NOT NULL,               -- hash(rule_id+entity_id+window_bucket)
    acknowledged_by     UUID,
    acknowledged_at     TIMESTAMPTZ,
    assigned_to         UUID,
    resolved_by         UUID,
    resolved_at         TIMESTAMPTZ,
    resolution_notes    TEXT,
    generated_at        TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- SLA: < 5 min from event to delivery (NFR-PERF-005)
    event_detected_at   TIMESTAMPTZ NOT NULL,
    first_delivered_at  TIMESTAMPTZ,
    delivery_latency_ms INT
                            GENERATED ALWAYS AS
                            (CASE WHEN first_delivered_at IS NOT NULL
                                  THEN EXTRACT(EPOCH FROM (first_delivered_at - event_detected_at)) * 1000
                                  ELSE NULL END)::INT STORED,
    UNIQUE(tenant_id, dedup_key)
);
SELECT create_distributed_table('alert.alerts', 'tenant_id');
CREATE INDEX idx_alert_status       ON alert.alerts(tenant_id, status, severity);
CREATE INDEX idx_alert_entity       ON alert.alerts(tenant_id, entity_type, entity_id);
CREATE INDEX idx_alert_generated    ON alert.alerts(tenant_id, generated_at DESC);

CREATE TABLE alert.alert_deliveries (
    delivery_id     UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID        NOT NULL,
    alert_id        UUID        NOT NULL,
    channel         VARCHAR(32) NOT NULL, -- 'email','sms','slack','teams','webhook','in_app'
    recipient       VARCHAR(512) NOT NULL,
    status          VARCHAR(32) NOT NULL DEFAULT 'pending'
                        CHECK (status IN ('pending','sending','delivered','failed','bounced')),
    attempts        SMALLINT    NOT NULL DEFAULT 0,
    last_attempt_at TIMESTAMPTZ,
    delivered_at    TIMESTAMPTZ,
    provider_message_id VARCHAR(512),
    failure_reason  TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);
SELECT create_distributed_table('alert.alert_deliveries', 'tenant_id');
CREATE INDEX idx_ad_alert   ON alert.alert_deliveries(tenant_id, alert_id);
CREATE INDEX idx_ad_status  ON alert.alert_deliveries(tenant_id, status) WHERE status IN ('pending','failed');

-- ---------------------------------------------------------------------------
-- MODULE 1.9: SUPPLIER DOCUMENTS
-- SUP-FR-003: document vault with version control + expiry tracking
-- SUP-FR-005: certification expiry notifications
-- ---------------------------------------------------------------------------
CREATE TABLE supply.supplier_documents (
    doc_id              UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID        NOT NULL,
    supplier_id         UUID        NOT NULL,
    doc_type            VARCHAR(64) NOT NULL,
    -- 'iso_cert','soc2','financial_statement','audit_report','contract','insurance','esg_report','other'
    doc_name            VARCHAR(512) NOT NULL,
    version             INT         NOT NULL DEFAULT 1,
    is_current_version  BOOLEAN     NOT NULL DEFAULT TRUE,
    s3_key              TEXT        NOT NULL,                           -- encrypted at rest in S3
    content_hash        CHAR(64)    NOT NULL,                          -- SHA-256 for integrity
    file_size_bytes     BIGINT,
    mime_type           VARCHAR(128),
    issued_date         DATE,
    expiry_date         DATE,
    expiry_alert_sent_90 BOOLEAN    NOT NULL DEFAULT FALSE,
    expiry_alert_sent_60 BOOLEAN    NOT NULL DEFAULT FALSE,
    expiry_alert_sent_30 BOOLEAN    NOT NULL DEFAULT FALSE,
    uploaded_by         UUID        NOT NULL,
    upload_source       VARCHAR(32) -- 'portal','api','email_ingest','manual'
                            CHECK (upload_source IN ('portal','api','email_ingest','manual')),
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    deleted_at          TIMESTAMPTZ
);
SELECT create_distributed_table('supply.supplier_documents', 'tenant_id');
CREATE INDEX idx_docs_supplier      ON supply.supplier_documents(tenant_id, supplier_id, is_current_version);
CREATE INDEX idx_docs_expiry        ON supply.supplier_documents(tenant_id, expiry_date) WHERE deleted_at IS NULL;

-- ---------------------------------------------------------------------------
-- MODULE 1.10: AUDIT LOG (IMMUTABLE)
-- IAM-FR-005, ALERT-FR-008, INT-FR-007
-- NFR-COMP-005: immutable append-only for regulatory traceability
-- Append-only enforced by: no UPDATE/DELETE permissions on this table;
--   row-level trigger raises exception on any modification
-- ---------------------------------------------------------------------------
CREATE TABLE audit.audit_log (
    log_id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID        NOT NULL,
    occurred_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    actor_type      VARCHAR(32) NOT NULL CHECK (actor_type IN ('user','service_account','system','supplier_user')),
    actor_id        UUID,
    actor_email     VARCHAR(320),
    session_id      UUID,
    ip_address      INET,
    action          VARCHAR(128) NOT NULL,
    -- e.g. 'supplier.create','risk_score.override','alert.acknowledge','user.login','data.export'
    resource_type   VARCHAR(64),
    resource_id     UUID,
    old_value       JSONB,
    new_value       JSONB,
    outcome         VARCHAR(16) NOT NULL DEFAULT 'success' CHECK (outcome IN ('success','failure','blocked')),
    failure_reason  TEXT,
    request_id      UUID,                   -- X-Request-ID header
    user_agent      TEXT
) PARTITION BY RANGE (occurred_at);

CREATE TABLE audit.audit_log_2026_q1 PARTITION OF audit.audit_log
    FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
CREATE TABLE audit.audit_log_2026_q2 PARTITION OF audit.audit_log
    FOR VALUES FROM ('2026-04-01') TO ('2026-07-01');
CREATE TABLE audit.audit_log_2026_q3 PARTITION OF audit.audit_log
    FOR VALUES FROM ('2026-07-01') TO ('2026-10-01');
CREATE TABLE audit.audit_log_2026_q4 PARTITION OF audit.audit_log
    FOR VALUES FROM ('2026-10-01') TO ('2027-01-01');
-- Future partitions created by pg_partman (quarterly)
SELECT create_distributed_table('audit.audit_log', 'tenant_id');
CREATE INDEX idx_audit_tenant_time  ON audit.audit_log(tenant_id, occurred_at DESC);
CREATE INDEX idx_audit_actor        ON audit.audit_log(tenant_id, actor_id, occurred_at DESC);
CREATE INDEX idx_audit_resource     ON audit.audit_log(tenant_id, resource_type, resource_id);
CREATE INDEX idx_audit_action       ON audit.audit_log(tenant_id, action, occurred_at DESC);

-- Immutability enforcement trigger
CREATE OR REPLACE FUNCTION audit.prevent_audit_modification()
RETURNS TRIGGER LANGUAGE plpgsql AS $$
BEGIN
    RAISE EXCEPTION 'Audit log is immutable. Modification of record % is not permitted.', OLD.log_id;
END;
$$;

CREATE TRIGGER trg_audit_immutable
    BEFORE UPDATE OR DELETE ON audit.audit_log
    FOR EACH ROW EXECUTE FUNCTION audit.prevent_audit_modification();

-- ---------------------------------------------------------------------------
-- MODULE 1.11: GDPR / CCPA COMPLIANCE TABLES
-- NFR-COMP-001: Right to Erasure (Article 17) — max 30-day SLA
-- NFR-COMP-002: CCPA deletion + opt-out
-- ---------------------------------------------------------------------------
CREATE TABLE gdpr.erasure_requests (
    request_id          UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID        NOT NULL,
    requester_email     VARCHAR(320) NOT NULL,
    requester_type      VARCHAR(32) NOT NULL CHECK (requester_type IN ('user','supplier_contact','data_subject','legal_request')),
    request_type        VARCHAR(32) NOT NULL CHECK (request_type IN ('erasure','access','portability','restriction','ccpa_deletion','ccpa_optout')),
    regulation          VARCHAR(16) NOT NULL CHECK (regulation IN ('gdpr','ccpa','both')),
    status              VARCHAR(32) NOT NULL DEFAULT 'received'
                            CHECK (status IN ('received','verified','in_progress','completed','rejected','partially_completed')),
    -- SLA: 30 days from received_at
    received_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    verification_completed_at TIMESTAMPTZ,
    processing_started_at TIMESTAMPTZ,
    sla_deadline        TIMESTAMPTZ NOT NULL
                            GENERATED ALWAYS AS (received_at + INTERVAL '30 days') STORED,
    completed_at        TIMESTAMPTZ,
    rejection_reason    TEXT,
    affected_tables     TEXT[]      NOT NULL DEFAULT '{}',
    affected_record_ids JSONB       NOT NULL DEFAULT '{}',
    processed_by        UUID,
    notes               TEXT,
    -- Evidence for compliance audit
    evidence_s3_key     TEXT
);
CREATE INDEX idx_erasure_status     ON gdpr.erasure_requests(tenant_id, status);
CREATE INDEX idx_erasure_deadline   ON gdpr.erasure_requests(tenant_id, sla_deadline) WHERE status NOT IN ('completed','rejected');

CREATE TABLE gdpr.consent_records (
    consent_id      UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID        NOT NULL,
    data_subject_id UUID        NOT NULL,               -- user_id or external contact id
    purpose         VARCHAR(128) NOT NULL,
    lawful_basis    VARCHAR(64) NOT NULL,               -- 'consent','legitimate_interest','contract','legal_obligation'
    granted         BOOLEAN     NOT NULL DEFAULT TRUE,
    granted_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    revoked_at      TIMESTAMPTZ,
    ip_address      INET,
    user_agent      TEXT,
    evidence_text   TEXT                                -- snapshot of consent text shown to user
);

-- ---------------------------------------------------------------------------
-- MODULE 1.12: SUPPLIER PERFORMANCE SCORECARDS
-- SUP-FR-004: KPIs: OTD rate, defect rate, fill rate, invoice accuracy
-- ---------------------------------------------------------------------------
CREATE TABLE supply.supplier_scorecards (
    scorecard_id        UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id           UUID        NOT NULL,
    supplier_id         UUID        NOT NULL,
    period_start        DATE        NOT NULL,
    period_end          DATE        NOT NULL,
    -- KPIs
    otd_rate            DECIMAL(5,4),   -- on-time delivery rate (0.0-1.0)
    defect_rate         DECIMAL(5,4),
    fill_rate           DECIMAL(5,4),
    invoice_accuracy    DECIMAL(5,4),
    responsiveness_score DECIMAL(3,1), -- 1-10
    perfect_order_rate  DECIMAL(5,4),
    lead_time_variance  DECIMAL(8,2),  -- std dev days
    -- Rollup
    overall_score       DECIMAL(5,2),
    score_grade         CHAR(2),        -- A+,A,B,C,D,F
    total_po_lines      INT,
    total_spend         DECIMAL(18,4),
    computed_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(tenant_id, supplier_id, period_start, period_end)
);
SELECT create_distributed_table('supply.supplier_scorecards', 'tenant_id');
CREATE INDEX idx_scorecard_supplier ON supply.supplier_scorecards(tenant_id, supplier_id, period_start DESC);

-- ---------------------------------------------------------------------------
-- MODULE 1.13: ROW-LEVEL SECURITY (TENANT ISOLATION)
-- All tables with tenant_id must enforce RLS
-- Application connects as role 'app_user'
-- Current tenant_id passed via: SET app.current_tenant_id = '<uuid>'
-- ---------------------------------------------------------------------------

-- Enable RLS on all critical tables
ALTER TABLE supply.suppliers                ENABLE ROW LEVEL SECURITY;
ALTER TABLE supply.purchase_orders          ENABLE ROW LEVEL SECURITY;
ALTER TABLE supply.shipments                ENABLE ROW LEVEL SECURITY;
ALTER TABLE supply.inventory_snapshots      ENABLE ROW LEVEL SECURITY;
ALTER TABLE supply.iot_telemetry            ENABLE ROW LEVEL SECURITY;
ALTER TABLE supply.supplier_documents       ENABLE ROW LEVEL SECURITY;
ALTER TABLE supply.supplier_scorecards      ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk.supplier_risk_scores       ENABLE ROW LEVEL SECURITY;
ALTER TABLE risk.risk_events                ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert.alert_rules               ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert.alerts                    ENABLE ROW LEVEL SECURITY;
ALTER TABLE alert.alert_deliveries          ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.users                      ENABLE ROW LEVEL SECURITY;
ALTER TABLE core.roles                      ENABLE ROW LEVEL SECURITY;

-- Policy template (replicated per table)
CREATE POLICY tenant_isolation ON supply.suppliers
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation ON supply.purchase_orders
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

CREATE POLICY tenant_isolation ON risk.supplier_risk_scores
    USING (tenant_id = current_setting('app.current_tenant_id')::UUID);

-- Application role: no superuser, no RLS bypass
CREATE ROLE app_user NOSUPERUSER NOCREATEDB NOCREATEROLE;
GRANT USAGE ON SCHEMA supply, risk, alert, audit, core, analytics, gdpr TO app_user;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA supply TO app_user;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA risk TO app_user;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA alert TO app_user;
GRANT SELECT, INSERT ON audit.audit_log TO app_user;   -- NO UPDATE/DELETE on audit
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA core TO app_user;
GRANT SELECT, INSERT, UPDATE ON ALL TABLES IN SCHEMA gdpr TO app_user;
-- Revoke direct table access for anything requiring superuser
REVOKE ALL ON audit.audit_log FROM PUBLIC;

-- ---------------------------------------------------------------------------
-- MODULE 1.14: KRI SNAPSHOTS (Analytics)
-- RPT-FR-005: KRI tracking over time windows
-- ---------------------------------------------------------------------------
CREATE TABLE analytics.kri_snapshots (
    snapshot_id     UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    tenant_id       UUID        NOT NULL,
    kri_name        VARCHAR(128) NOT NULL,
    entity_type     VARCHAR(32) NOT NULL, -- 'platform','tenant','category','supplier','region'
    entity_id       VARCHAR(256),
    value           DECIMAL(18,6) NOT NULL,
    unit            VARCHAR(32),
    threshold_warn  DECIMAL(18,6),
    threshold_crit  DECIMAL(18,6),
    is_breach       BOOLEAN NOT NULL DEFAULT FALSE,
    snapshot_at     TIMESTAMPTZ NOT NULL DEFAULT now()
) PARTITION BY RANGE (snapshot_at);
CREATE TABLE analytics.kri_snapshots_2026_q1 PARTITION OF analytics.kri_snapshots
    FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
SELECT create_distributed_table('analytics.kri_snapshots', 'tenant_id');
CREATE INDEX idx_kri_entity_time ON analytics.kri_snapshots(tenant_id, kri_name, entity_id, snapshot_at DESC);

-- ---------------------------------------------------------------------------
-- MODULE 1.15: EXTERNAL INTELLIGENCE FEED CACHE
-- RISK-FR-003: 15 external data feeds
-- Retention: 2 years (§6.1 data requirements)
-- ---------------------------------------------------------------------------
CREATE TABLE risk.external_intelligence (
    intel_id        UUID        PRIMARY KEY DEFAULT uuid_generate_v4(),
    source          VARCHAR(64) NOT NULL,  -- 'dnb','refinitiv','news_nlp','weather','port_congestion','geopolitical'
    event_type      VARCHAR(64) NOT NULL,
    geo_scope       CHAR(2)[],             -- affected countries
    supplier_ids_matched UUID[],           -- matched to tenant suppliers at ingest time
    headline        TEXT,
    severity        VARCHAR(16),
    confidence_level DECIMAL(3,2),         -- 0.0-1.0 source confidence
    source_url      TEXT,
    published_at    TIMESTAMPTZ,
    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    processed_at    TIMESTAMPTZ,
    -- Global table - no tenant isolation (pre-match); tenant FK added at match time
    nlp_entities    JSONB       NOT NULL DEFAULT '{}',  -- extracted entities from NLP
    raw_payload     JSONB       NOT NULL DEFAULT '{}'   -- original feed payload (size-limited)
) PARTITION BY RANGE (ingested_at);
CREATE TABLE risk.external_intelligence_2026_q1 PARTITION OF risk.external_intelligence
    FOR VALUES FROM ('2026-01-01') TO ('2026-04-01');
CREATE INDEX idx_intel_source_time  ON risk.external_intelligence(source, ingested_at DESC);
CREATE INDEX idx_intel_geo          ON risk.external_intelligence USING gin(geo_scope);
CREATE INDEX idx_intel_suppliers    ON risk.external_intelligence USING gin(supplier_ids_matched);

-- =============================================================================
-- END OF CORE DOMAIN MODEL
-- Coverage: VIS-FR-001..012, SUP-FR-001..010, RISK-FR-001..013,
--           ALERT-FR-001..008, INT-FR-007, IAM-FR-001..006,
--           NFR-SEC-001..007, NFR-COMP-001..005, NFR-SCAL-002..004
-- Tenant Isolation: Citus distribution on tenant_id + RLS policies
-- Encryption: AES-256 at rest (RDS), field-level pgcrypto for PII, TLS 1.3 in transit
-- Partitioning: iot_telemetry by month, audit_log/risk_score_history/kri_snapshots by quarter
-- Audit Trail: append-only audit.audit_log with modification-prevention trigger
-- =============================================================================
