# SCVRI Platform

**Supply Chain Visibility & Risk Intelligence**

---

## What is SCVRI?

SCVRI is an enterprise supply chain risk management platform that gives procurement, operations, and risk teams a unified view of every supplier, shipment, and disruption event in their supply network — in real time.

---

## Problem Statement

Modern supply chains span dozens of countries, hundreds of suppliers, and thousands of shipments moving simultaneously. When something goes wrong — a typhoon near a critical port, a supplier on the edge of insolvency, a carrier experiencing systemic delays — most companies find out days or weeks too late, through a missed delivery or an emergency call.

The core problems SCVRI solves:

| Problem | Impact |
|---|---|
| **No real-time visibility** into where shipments are and what risks they face | Reactive firefighting instead of proactive mitigation |
| **Siloed supplier data** spread across ERP, spreadsheets, and email | Decision-makers lack a single source of truth |
| **Alert fatigue** from unstructured notifications with no triage workflow | Critical events are missed or acted on too slowly |
| **No risk quantification** — teams can't answer "how much spend is exposed?" | Boards and CFOs can't make informed decisions |
| **Manual reporting** — risk reports take days to compile and are stale by the time they're read | Leadership acts on outdated information |

---

## Solution

SCVRI aggregates data from ERPs, carrier APIs, IoT sensors, and external intelligence feeds and surfaces it through five capabilities:

### 1. Executive Dashboard
A real-time command centre showing active disruptions, spend at risk, and risk score trends across the supplier network. Drag-and-drop layout adapts to each user's workflow.

### 2. Supply Chain Map
An interactive geospatial view of every supplier node and shipment lane, with live risk overlays (weather, transport, geopolitical) plotted on top.

### 3. Supplier Intelligence
A 360° supplier profile for every vendor: risk score, active purchase orders, spend exposure, SLA performance, and financial health indicators — all in one place.

### 4. Risk Intelligence
ML-powered risk scoring that monitors supplier financial signals, news feeds, weather events, and trade lane disruptions and predicts risk escalation before it materialises.

### 5. Alert Center
A structured workflow for triaging, acknowledging, assigning, and resolving risk alerts — with per-alert notes and a full audit trail, so nothing falls through the cracks.

### 6. Reports & Analytics
On-demand and scheduled exports of spend concentration, supplier performance scorecards, risk trend analysis, and lead time reports — in PDF, CSV, or XLSX.

---

## Architecture

```
frontend/          Next.js 16 (App Router, Turbopack)
services/
  iam/             Identity & Access Management (FastAPI)
  supplier-management/   Supplier CRUD, scoring (FastAPI)
  risk-intelligence/     ML risk engine (FastAPI + XGBoost/LightGBM)
  visibility/      Shipment tracking & IoT ingestion (FastAPI)
  alert-engine/    Alert rules, routing, notifications (FastAPI)
  integration/     ERP & carrier connector adapters (FastAPI)
shared/            Shared Python library (pydantic-settings, DB, auth)
infra/             Kubernetes manifests, Terraform
```

**Infrastructure (local dev):**
- PostgreSQL 15 + Citus — multi-tenant relational store
- Redis 7 — caching, rate limiting, session store
- Kafka (Confluent) — event streaming between services
- MinIO — S3-compatible object storage for documents and ML artifacts
- Mailhog — local SMTP for email alerts

---

## Getting Started

### Prerequisites
- Docker Desktop
- Node.js 20+
- Python 3.12+
- Poetry

### 1. Start infrastructure

```bash
docker compose -f docker-compose.dev.yml up -d
```

### 2. Configure environment

The root `.env` is pre-configured for local Docker services. Only external credentials need filling in:

```bash
# .env — third-party (optional for local dev)
SLACK_BOT_TOKEN=          # https://api.slack.com/apps
PAGERDUTY_ROUTING_KEY=    # https://app.pagerduty.com

# frontend/.env.local — map tiles (optional — uses free OSM by default)
NEXT_PUBLIC_MAPBOX_TOKEN= # https://account.mapbox.com (leave empty for free MapLibre tiles)
```

### 3. Run the frontend

```bash
cd frontend
npm install
npm run dev
# → http://localhost:3000
```

### 4. Run a backend service

Each service shares the root `.env` via symlink.

```bash
source .venv/bin/activate
cd services/iam
uvicorn src.main:app --reload --port 8000
```

Run all services at once (Makefile target coming in v1.1):
```bash
make dev-services
```

---

## Key Environment Variables

| Variable | Category | Description |
|---|---|---|
| `DB_HOST`, `DB_PASSWORD` | Local infra | PostgreSQL — matched to docker-compose |
| `REDIS_HOST`, `REDIS_PASSWORD` | Local infra | Redis — matched to docker-compose |
| `KAFKA_BOOTSTRAP_SERVERS` | Local infra | Kafka broker address |
| `JWT_PRIVATE_KEY_PATH` | Generated | RSA-4096 key in `certs/` — auto-generated |
| `WEBHOOK_SECRET` | Generated | Random hex secret for inbound webhooks |
| `SLACK_BOT_TOKEN` | Third-party | Slack alerts integration |
| `PAGERDUTY_ROUTING_KEY` | Third-party | PagerDuty on-call escalation |
| `ERP_API_KEY` | Enterprise | ERP system connector |
| `CARRIER_API_KEY` | Enterprise | Carrier tracking API |
| `ENVIRONMENT`, `LOG_LEVEL` | Static config | Runtime environment settings |

See [`.env.example`](.env.example) for the full list.

---

## Security

- All secrets live in `.env` (git-ignored). Never commit real credentials.
- JWT signed with RS256 (4096-bit RSA). Keys live in `certs/` (git-ignored).
- Multi-tenant data isolation via PostgreSQL row-level security.
- All API endpoints require a valid JWT. Role-based access: `admin`, `analyst`, `viewer`.

---

## License

Proprietary — SCVRI Business Projects. All rights reserved.
