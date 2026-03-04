"""Abstract base connector for ERP systems."""
from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from datetime import datetime
from typing import Any

import httpx

from integration.schemas.erp import (
    ERPConnectionConfig,
    ERPEntityType,
    ERPRawEvent,
    ERPSystem,
)

logger = logging.getLogger(__name__)


class ConnectorAuthError(Exception):
    """Raised when the connector fails to authenticate with the ERP."""


class ConnectorFetchError(Exception):
    """Raised when the ERP returns an unexpected / error response."""


class BaseERPConnector(ABC):
    """
    Abstract ERP connector.

    Each concrete subclass implements :meth:`authenticate`,
    :meth:`fetch_entities`, and :meth:`normalise`.
    """

    system: ERPSystem

    def __init__(self, config: ERPConnectionConfig) -> None:
        self.config = config
        self._client: httpx.AsyncClient | None = None
        self._access_token: str | None = None

    # ── HTTP client lifecycle ──────────────────────────────────────────────────

    async def __aenter__(self) -> "BaseERPConnector":
        self._client = httpx.AsyncClient(
            base_url=self.config.base_url,
            timeout=self.config.timeout_seconds,
            headers={"Accept": "application/json"},
        )
        await self.authenticate()
        return self

    async def __aexit__(self, *args: Any) -> None:
        if self._client:
            await self._client.aclose()
        self._client = None
        self._access_token = None

    # ── Mandatory overrides ────────────────────────────────────────────────────

    @abstractmethod
    async def authenticate(self) -> None:
        """Obtain and store access credentials (OAuth 2.0 client_credentials etc.)."""

    @abstractmethod
    async def fetch_entities(
        self,
        entity_type: ERPEntityType,
        since: datetime | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        """Retrieve a page of raw entity records from the ERP."""

    @abstractmethod
    def normalise(
        self,
        entity_type: ERPEntityType,
        raw: dict[str, Any],
    ) -> ERPRawEvent:
        """Convert a raw ERP record into the platform-canonical :class:`ERPRawEvent`."""

    # ── Convenience helpers ────────────────────────────────────────────────────

    async def pull_all(
        self,
        entity_type: ERPEntityType,
        since: datetime | None = None,
        page_size: int = 100,
    ) -> list[ERPRawEvent]:
        """Paginate through all records for *entity_type* and return normalised events."""
        results: list[ERPRawEvent] = []
        page = 1
        while True:
            raw_records = await self.fetch_entities(entity_type, since, page, page_size)
            if not raw_records:
                break
            for raw in raw_records:
                try:
                    event = self.normalise(entity_type, raw)
                    results.append(event)
                except Exception as exc:
                    logger.warning(
                        "Normalisation failed for %s record: %s", entity_type, exc
                    )
            if len(raw_records) < page_size:
                break
            page += 1
        logger.info(
            "Pulled %d %s records from %s",
            len(results), entity_type, self.system,
        )
        return results

    def _require_client(self) -> httpx.AsyncClient:
        if self._client is None:
            raise RuntimeError("Connector not entered via async context manager")
        return self._client

    async def _get(
        self,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> Any:
        """Execute an authenticated GET and return parsed JSON."""
        client = self._require_client()
        headers: dict[str, str] = {}
        if self._access_token:
            headers["Authorization"] = f"Bearer {self._access_token}"
        response = await client.get(path, params=params, headers=headers)
        if response.status_code == 401:
            logger.warning("Access token expired; re-authenticating")
            await self.authenticate()
            headers["Authorization"] = f"Bearer {self._access_token}"
            response = await client.get(path, params=params, headers=headers)
        if not response.is_success:
            raise ConnectorFetchError(
                f"GET {path} returned {response.status_code}: {response.text[:200]}"
            )
        return response.json()
