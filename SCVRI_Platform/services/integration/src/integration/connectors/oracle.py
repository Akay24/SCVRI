"""Oracle Fusion Cloud REST connector."""
from __future__ import annotations

import base64
import logging
from datetime import datetime
from typing import Any

from integration.connectors.base import BaseERPConnector, ConnectorAuthError
from integration.schemas.erp import (
    ERPConnectionConfig,
    ERPEntityType,
    ERPRawEvent,
    ERPSystem,
)

logger = logging.getLogger(__name__)

# Oracle Fusion REST resource paths
_ENTITY_PATHS: dict[ERPEntityType, str] = {
    ERPEntityType.SUPPLIER: "/fscmRestApi/resources/11.13.18.05/suppliers",
    ERPEntityType.PURCHASE_ORDER: "/fscmRestApi/resources/11.13.18.05/purchaseOrders",
    ERPEntityType.INVOICE: "/fscmRestApi/resources/11.13.18.05/invoices",
    ERPEntityType.GOODS_RECEIPT: "/fscmRestApi/resources/11.13.18.05/receivingTransactions",
    ERPEntityType.DELIVERY: "/fscmRestApi/resources/11.13.18.05/deliveries",
}

_ID_FIELDS: dict[ERPEntityType, str] = {
    ERPEntityType.SUPPLIER: "SupplierId",
    ERPEntityType.PURCHASE_ORDER: "POHeaderId",
    ERPEntityType.INVOICE: "InvoiceId",
    ERPEntityType.GOODS_RECEIPT: "TransactionId",
    ERPEntityType.DELIVERY: "DeliverId",
}

_MODIFIED_FIELDS: dict[ERPEntityType, str] = {
    ERPEntityType.SUPPLIER: "LastUpdateDate",
    ERPEntityType.PURCHASE_ORDER: "LastUpdateDate",
    ERPEntityType.INVOICE: "LastUpdateDate",
    ERPEntityType.GOODS_RECEIPT: "TransactionDate",
    ERPEntityType.DELIVERY: "LastUpdateDate",
}


class OracleConnector(BaseERPConnector):
    """
    Oracle Fusion Cloud connector using HTTP Basic Authentication.

    Oracle Fusion REST APIs use Basic Auth (client_id = username,
    client_secret = password), or optionally OAuth 2.0 JWT Bearer if
    ``config.extra["use_oauth"]`` is truthy.
    """

    system = ERPSystem.ORACLE

    async def authenticate(self) -> None:
        if self.config.extra.get("use_oauth"):
            await self._authenticate_oauth()
        else:
            # Basic auth — encode once, attach to every request via _access_token
            credentials = f"{self.config.client_id}:{self.config.client_secret}"
            encoded = base64.b64encode(credentials.encode()).decode()
            self._access_token = f"Basic {encoded}"
            logger.debug("OracleConnector: using Basic auth for tenant %s", self.config.tenant_id)

    async def _authenticate_oauth(self) -> None:
        client = self._require_client()
        token_url = self.config.extra.get("token_url", "/oauth/token")
        response = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
                "scope": self.config.extra.get("oauth_scope", ""),
            },
        )
        if not response.is_success:
            raise ConnectorAuthError(
                f"Oracle OAuth failed [{response.status_code}]: {response.text[:200]}"
            )
        token = response.json().get("access_token")
        if not token:
            raise ConnectorAuthError("Oracle OAuth response missing access_token")
        self._access_token = token
        logger.debug("OracleConnector: OAuth authenticated for tenant %s", self.config.tenant_id)

    # Override _get to handle both Bearer and Basic auth token formats
    async def _get_with_auth(self, path: str, params: dict[str, Any] | None = None) -> Any:
        client = self._require_client()
        auth_header = self._access_token or ""
        if not auth_header.startswith("Basic "):
            auth_header = f"Bearer {auth_header}"
        response = await client.get(
            path,
            params=params,
            headers={"Authorization": auth_header},
        )
        if response.status_code == 401:
            await self.authenticate()
            auth_header = self._access_token or ""
            if not auth_header.startswith("Basic "):
                auth_header = f"Bearer {auth_header}"
            response = await client.get(
                path,
                params=params,
                headers={"Authorization": auth_header},
            )
        if not response.is_success:
            from integration.connectors.base import ConnectorFetchError
            raise ConnectorFetchError(
                f"GET {path} returned {response.status_code}: {response.text[:200]}"
            )
        return response.json()

    async def fetch_entities(
        self,
        entity_type: ERPEntityType,
        since: datetime | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        path = _ENTITY_PATHS.get(entity_type)
        if path is None:
            logger.warning("OracleConnector: unsupported entity_type %s", entity_type)
            return []

        offset = (page - 1) * page_size
        params: dict[str, Any] = {
            "limit": page_size,
            "offset": offset,
            "orderBy": "LastUpdateDate:desc",
        }
        if since:
            modified_field = _MODIFIED_FIELDS.get(entity_type, "LastUpdateDate")
            params["q"] = f"{modified_field}>={since.strftime('%Y-%m-%dT%H:%M:%S')}"

        data = await self._get_with_auth(path, params=params)
        # Oracle returns {"items": [...], "count": N, "hasMore": bool}
        records: list[dict[str, Any]] = data.get("items", [])
        logger.debug(
            "OracleConnector: fetched %d %s records (page %d)",
            len(records), entity_type, page,
        )
        return records

    def normalise(
        self,
        entity_type: ERPEntityType,
        raw: dict[str, Any],
    ) -> ERPRawEvent:
        id_field = _ID_FIELDS.get(entity_type, "Id")
        source_id = str(raw.get(id_field, ""))
        modified_field = _MODIFIED_FIELDS.get(entity_type, "LastUpdateDate")
        occurred_raw = raw.get(modified_field, "")

        try:
            occurred_at = datetime.fromisoformat(str(occurred_raw))
        except (ValueError, TypeError):
            occurred_at = datetime.utcnow()

        return ERPRawEvent(
            source_system=ERPSystem.ORACLE,
            entity_type=entity_type,
            source_id=source_id,
            tenant_id=self.config.tenant_id,
            occurred_at=occurred_at,
            payload=raw,
        )
