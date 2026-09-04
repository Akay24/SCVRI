"""Central pydantic-settings configuration for all SCVRI services.

Each service imports `get_settings()` directly.  Service-specific config
classes can inherit from `BaseSettings` and add their own fields.

Usage::

    from scvri_shared.config import settings

    DB_URL = settings.database_url
"""
from __future__ import annotations

import functools
from typing import Literal

from pydantic import AnyUrl, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Platform-wide configuration.

    All values can be overridden via environment variables (case-insensitive)
    or a ``.env`` file placed in the working directory.
    """

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ------------------------------------------------------------------ #
    # Environment
    # ------------------------------------------------------------------ #
    environment: Literal["development", "staging", "production"] = "development"
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    service_name: str = "scvri-service"
    service_version: str = "1.0.0"

    # ------------------------------------------------------------------ #
    # PostgreSQL (Citus-enabled Aurora)
    # ------------------------------------------------------------------ #
    db_host: str = "localhost"
    db_port: int = 5432
    db_name: str = "scvri"
    db_user: str = "scvri_admin"
    db_password: SecretStr = SecretStr("changeme")
    db_pool_size: int = 20
    db_max_overflow: int = 10
    db_pool_timeout: int = 30
    db_pool_recycle: int = 1800         # 30 minutes — avoids stale connections
    db_echo: bool = False

    @property
    def database_url(self) -> str:
        """Sync psycopg2 URL (used by Alembic and synchronous workers)."""
        pw = self.db_password.get_secret_value()
        return (
            f"postgresql+psycopg2://{self.db_user}:{pw}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    @property
    def async_database_url(self) -> str:
        """Async asyncpg URL (used by FastAPI endpoints)."""
        pw = self.db_password.get_secret_value()
        return (
            f"postgresql+asyncpg://{self.db_user}:{pw}"
            f"@{self.db_host}:{self.db_port}/{self.db_name}"
        )

    # ------------------------------------------------------------------ #
    # Redis Cluster (ElastiCache)
    # ------------------------------------------------------------------ #
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_password: SecretStr | None = None
    redis_db: int = 0
    redis_max_connections: int = 100
    redis_socket_timeout: float = 5.0
    redis_socket_connect_timeout: float = 2.0

    @property
    def redis_url(self) -> str:
        pw = self.redis_password
        if pw:
            return f"redis://:{pw.get_secret_value()}@{self.redis_host}:{self.redis_port}/{self.redis_db}"
        return f"redis://{self.redis_host}:{self.redis_port}/{self.redis_db}"

    # ------------------------------------------------------------------ #
    # Kafka / MSK
    # ------------------------------------------------------------------ #
    kafka_bootstrap_servers: str = "localhost:9092"
    kafka_security_protocol: str = "PLAINTEXT"
    kafka_sasl_mechanism: str = "SCRAM-SHA-512"
    kafka_sasl_username: str = ""
    kafka_sasl_password: SecretStr = SecretStr("")
    kafka_schema_registry_url: str = "http://localhost:8081"
    kafka_consumer_group_prefix: str = "scvri"
    kafka_default_topic_replicas: int = 3
    kafka_default_topic_partitions: int = 48

    # ------------------------------------------------------------------ #
    # JWT / Authentication
    # ------------------------------------------------------------------ #
    jwt_algorithm: str = "RS256"
    jwt_access_token_expire_minutes: int = 15
    jwt_refresh_token_expire_days: int = 7
    jwt_issuer: str = "https://auth.scvri.io"
    jwt_audience: str = "https://api.scvri.io"
    # KMS key ARN for production; file path for local dev
    jwt_private_key_path: str = "certs/jwt_private.pem"
    jwt_public_key_path: str = "certs/jwt_public.pem"

    # ------------------------------------------------------------------ #
    # AWS
    # ------------------------------------------------------------------ #
    aws_region: str = "us-east-1"
    aws_account_id: str = ""
    s3_supplier_docs_bucket: str = "scvri-supplier-docs-prod"
    s3_report_output_bucket: str = "scvri-report-output-prod"
    s3_ml_artifacts_bucket: str = "scvri-ml-artifacts-prod"
    aws_ses_from_address: str = "noreply@scvri.io"
    kms_rds_key_arn: str = ""
    kms_s3_key_arn: str = ""

    # ------------------------------------------------------------------ #
    # OpenTelemetry
    # ------------------------------------------------------------------ #
    otel_exporter_otlp_endpoint: str = "http://otel-collector:4317"
    otel_enabled: bool = True

    # ------------------------------------------------------------------ #
    # Feature flags
    # ------------------------------------------------------------------ #
    enable_ml_scoring: bool = True
    enable_iot_ingestion: bool = True
    enable_gdpr_masking: bool = True

    # ------------------------------------------------------------------ #
    # CORS (for FastAPI services)
    # ------------------------------------------------------------------ #
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"]
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def parse_cors_origins(cls, v: str | list[str]) -> list[str]:
        if isinstance(v, str):
            return [origin.strip() for origin in v.split(",")]
        return v

    @property
    def s3_supplier_documents_bucket(self) -> str:
        return self.s3_supplier_docs_bucket


@functools.lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return a cached singleton Settings instance."""
    return Settings()


# Module-level singleton for convenience: ``from scvri_shared.config import settings``
settings: Settings = get_settings()
