# SCVRI environment profile

This frontend/backend workspace is configured to use the `development` profile by default (`ENVIRONMENT=development`).

## Manual configuration still required (cannot be auto-completed by Codex)

- Production/staging secrets: database password, Kafka SASL credentials, AWS account and keys, SMTP credentials, Slack token, PagerDuty routing key, ERP and carrier API keys.
- RSA JWT keys in `certs/jwt_private.pem` and `certs/jwt_public.pem`.
- `NEXT_PUBLIC_MAPBOX_TOKEN` for rendering the Supply Chain Map with Mapbox.
- Environment-specific service names/ports for each microservice deployment.
- Any cloud KMS key ARNs and hardened webhook secrets.

Use `SCVRI_Platform/.env.example` as the baseline and create environment-specific `.env` files outside source control.
