"""Unit tests for Transactional Outbox pattern and Kafka protocols."""
from __future__ import annotations

import uuid
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scvri_shared.models.outbox import OutboxEvent
from scvri_shared.outbox_relay import OutboxRelay, schedule_outbox_event


class TestOutboxModel:
    def test_outbox_event_creation(self) -> None:
        tenant_id = uuid.uuid4()
        event = OutboxEvent(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            topic="supplier.events",
            event_key="sup-123",
            event_type="supplier.created",
            payload={"name": "Acme Corp"},
            status="pending",
        )
        assert event.topic == "supplier.events"
        assert event.event_key == "sup-123"
        assert event.status == "pending"
        assert event.retry_count == 0


@pytest.mark.asyncio
class TestScheduleOutboxEvent:
    async def test_schedule_adds_event_to_session(self) -> None:
        db = MagicMock()
        tenant_id = uuid.uuid4()

        event = await schedule_outbox_event(
            db=db,
            tenant_id=tenant_id,
            topic="visibility.events",
            event_type="shipment.delayed",
            payload={"shipment_id": "sh-001", "delay_hours": 4},
            event_key="sh-001",
            correlation_id="corr-123",
        )

        assert isinstance(event, OutboxEvent)
        assert event.tenant_id == tenant_id
        assert event.topic == "visibility.events"
        assert event.event_type == "shipment.delayed"
        assert event.correlation_id == "corr-123"
        assert event.status == "pending"
        db.add.assert_called_once_with(event)


@pytest.mark.asyncio
class TestOutboxRelay:
    async def test_process_batch_publishes_and_marks_published(self) -> None:
        tenant_id = uuid.uuid4()
        mock_event = OutboxEvent(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            topic="supplier.events",
            event_key="sup-1",
            event_type="supplier.created",
            payload={"supplier_id": "sup-1"},
            status="pending",
            retry_count=0,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_event]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        relay = OutboxRelay(batch_size=10)
        relay._producer = AsyncMock()

        with patch("scvri_shared.outbox_relay.AsyncSessionLocal", return_value=mock_ctx):
            count = await relay.process_batch()

        assert count == 1
        assert mock_event.status == "published"
        assert mock_event.published_at is not None
        relay._producer.publish.assert_awaited_once_with(
            topic="supplier.events",
            key="sup-1",
            value={"supplier_id": "sup-1"},
            event_type="supplier.created",
            tenant_id=str(tenant_id),
            correlation_id="-",
        )
        mock_session.commit.assert_awaited_once()

    async def test_process_batch_handles_publish_failure_with_retry(self) -> None:
        tenant_id = uuid.uuid4()
        mock_event = OutboxEvent(
            id=uuid.uuid4(),
            tenant_id=tenant_id,
            topic="supplier.events",
            event_key="sup-1",
            event_type="supplier.created",
            payload={"supplier_id": "sup-1"},
            status="pending",
            retry_count=0,
        )

        mock_result = MagicMock()
        mock_result.scalars.return_value.all.return_value = [mock_event]

        mock_session = AsyncMock()
        mock_session.execute.return_value = mock_result
        mock_session.commit = AsyncMock()

        mock_ctx = MagicMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_session)
        mock_ctx.__aexit__ = AsyncMock(return_value=None)

        relay = OutboxRelay(batch_size=10, max_retries=3)
        relay._producer = AsyncMock()
        relay._producer.publish.side_effect = RuntimeError("Kafka cluster broker timeout")

        with patch("scvri_shared.outbox_relay.AsyncSessionLocal", return_value=mock_ctx):
            count = await relay.process_batch()

        assert count == 1
        assert mock_event.retry_count == 1
        assert mock_event.status == "pending"  # Still pending because retry_count (1) < max_retries (3)
        assert "Kafka cluster broker timeout" in str(mock_event.last_error)
        mock_session.commit.assert_awaited_once()


@pytest.mark.asyncio
class TestSCVRIConsumerProtocols:
    async def test_consumer_context_manager_and_iterator(self) -> None:
        from scvri_shared.kafka import SCVRIConsumer

        consumer = SCVRIConsumer(
            topics=["test.topic"],
            group_id="test-group",
        )

        mock_raw_consumer = AsyncMock()
        mock_msg = MagicMock(topic="test.topic", partition=0, offset=1, value={"key": "val"})

        # Mock anext
        mock_raw_consumer.__anext__ = AsyncMock(side_effect=[mock_msg, StopAsyncIteration()])
        mock_raw_consumer.start = AsyncMock()
        mock_raw_consumer.stop = AsyncMock()
        mock_raw_consumer.commit = AsyncMock()

        with patch.object(consumer, "_build_consumer", return_value=mock_raw_consumer):
            async with consumer:
                received = []
                async for msg in consumer:
                    received.append(msg)
                await consumer.commit()

        assert len(received) == 1
        assert received[0].value == {"key": "val"}
        mock_raw_consumer.start.assert_awaited_once()
        mock_raw_consumer.stop.assert_awaited_once()
        mock_raw_consumer.commit.assert_awaited_once()
