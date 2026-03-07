# SCVRI Frontend — Environment Setup

This Next.js application reads environment variables from `.env.local` (git-ignored).

## Quick Start

```bash
cp .env.local.example .env.local
# Edit .env.local and set your Mapbox token
npm run dev   # → http://localhost:3000
```

## Required Variables

| Variable | Description | Default (local dev) |
|---|---|---|
| `NEXT_PUBLIC_API_BASE_URL` | Backend API gateway URL | `http://localhost:8000` |
| `NEXT_PUBLIC_WS_BASE_URL` | WebSocket URL for real-time alerts | `ws://localhost:8000` |
| `NEXT_PUBLIC_MAPBOX_TOKEN` | Mapbox GL JS token — **required for Supply Chain Map** | — |

## Optional Feature Flags

| Variable | Description | Default |
|---|---|---|
| `NEXT_PUBLIC_ENABLE_AI_RISK_SCORING` | Toggle AI risk scoring UI | `true` |
| `NEXT_PUBLIC_ENABLE_REAL_TIME_TRACKING` | Toggle real-time shipment tracking | `true` |
| `NEXT_PUBLIC_ENABLE_PREDICTIVE_ANALYTICS` | Toggle predictive analytics panel | `false` |

## Getting a Mapbox Token

1. Sign up at https://account.mapbox.com/
2. Create a public token (starts with `pk.`)
3. Add it to `.env.local` as `NEXT_PUBLIC_MAPBOX_TOKEN`

## Backend Environment

See `SCVRI_Platform/.env.example` for the full backend variable reference.
Copy it to `SCVRI_Platform/.env` and fill in secrets before starting backend services.

### RSA JWT keys (required for IAM service)

```bash
mkdir -p certs
openssl genpkey -algorithm RSA -pkeyopt rsa_keygen_bits:4096 -out certs/jwt_private.pem
openssl rsa -in certs/jwt_private.pem -pubout -out certs/jwt_public.pem
```

## Manual Configuration Required

- Database password, Kafka SASL credentials
- AWS account ID, access key, secret key
- SMTP server credentials
- Slack bot token, PagerDuty routing key
- ERP and carrier API keys
- Cloud KMS key ARNs and webhook signing secrets
