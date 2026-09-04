"""Transactional Outbox event model.

Guarantees at-least-once message delivery from database transactions to Kafka.
Service handlers insert an OutboxEvent row within their business transaction;
an independent relay worker polls for pending records, publishes them to Kafka,
and marks them as published upon successful broker acknowledgement.
"""
from __future__ import annotations

import uuid
from datetime import datetime
from typing import Any

from sqlalchemy import (
    DateTime,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB, UUID
from sqlalchemy.orm import Mapped, mapped_column

from scvri_shared.models.base import Base, TenantMixin, UUIDPrimaryKeyMixin


class OutboxEvent(Base, UUIDPrimaryKeyMixin, TenantMixin):
    """Transactional Outbox record.

    Schema: ``platform.outbox_events`` or default schema ``outbox_events``.
    """

    __tablename__ = "outbox_events"
    __table_args__ = (
        Index("idx_outbox_status_created", "status", "created_at"),
        Index("idx_outbox_tenant_topic", "tenant_id", "topic"),
        {"schema": "platform"},
    )

    topic: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    event_key: Mapped[str | None] = mapped_column(String(255), nullable=True)
    event_type: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    correlation_id: Mapped[str | None] = mapped_column(String(128), nullable=True)
    status: Mapped[str] = mapped_column(String(32), default="pending", nullable=False)
    retry_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    published_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True),
        nullable=True,
    )

    def __init__(self, **kwargs: Any) -> None:
        kwargs.setdefault("status", "pending")
        kwargs.setdefault("retry_count", 0)
        super().__init__(**kwargs)
