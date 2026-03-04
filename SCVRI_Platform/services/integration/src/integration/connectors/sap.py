"""SAP S/4HANA OData v4 REST connector."""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any
from uuid import UUID

from integration.connectors.base import BaseERPConnector, ConnectorAuthError
from integration.schemas.erp import (
    ERPConnectionConfig,
    ERPEntityType,
    ERPRawEvent,
    ERPSystem,
)

logger = logging.getLogger(__name__)

# SAP OData entity set paths
_ENTITY_PATHS: dict[ERPEntityType, str] = {
    ERPEntityType.SUPPLIER: "/API_BUSINESS_PARTNER/A_BusinessPartner",
    ERPEntityType.PURCHASE_ORDER: "/API_PURCHASEORDER_PROCESS_SRV/A_PurchaseOrder",
    ERPEntityType.INVOICE: "/API_SUPPLIERINVOICE_PROCESS_SRV/A_SupplierInvoice",
    ERPEntityType.GOODS_RECEIPT: "/API_MATERIAL_DOCUMENT_SRV/A_MaterialDocItem",
    ERPEntityType.DELIVERY: "/API_OUTBOUND_DELIVERY_SRV/A_OutbDeliveryHeader",
}

# SAP source-ID field per entity type
_ID_FIELDS: dict[ERPEntityType, str] = {
    ERPEntityType.SUPPLIER: "BusinessPartner",
    ERPEntityType.PURCHASE_ORDER: "PurchaseOrder",
    ERPEntityType.INVOICE: "SupplierInvoice",
    ERPEntityType.GOODS_RECEIPT: "MaterialDocumentItem",
    ERPEntityType.DELIVERY: "DeliveryDocument",
}

# SAP modified-since field per entity type
_MODIFIED_FIELDS: dict[ERPEntityType, str] = {
    ERPEntityType.SUPPLIER: "LastChangeDateTime",
    ERPEntityType.PURCHASE_ORDER: "LastChangeDateTime",
    ERPEntityType.INVOICE: "LastChangeDateTime",
    ERPEntityType.GOODS_RECEIPT: "PostingDate",
    ERPEntityType.DELIVERY: "LastChangedDateTime",
}


class SAPConnector(BaseERPConnector):
    """
    SAP S/4HANA connector using OAuth 2.0 client_credentials + OData v4.

    Authentication: SAP BTP XSUAA token endpoint at
    ``{base_url}/oauth/token``.
    """

    system = ERPSystem.SAP

    async def authenticate(self) -> None:
        client = self._require_client()
        response = await client.post(
            "/oauth/token",
            data={
                "grant_type": "client_credentials",
                "client_id": self.config.client_id,
                "client_secret": self.config.client_secret,
            },
        )
        if not response.is_success:
            raise ConnectorAuthError(
                f"SAP auth failed [{response.status_code}]: {response.text[:200]}"
            )
        self._access_token = response.json().get("access_token")
        if not self._access_token:
            raise ConnectorAuthError("SAP auth response missing access_token")
        logger.debug("SAPConnector authenticated for tenant %s", self.config.tenant_id)

    async def fetch_entities(
        self,
        entity_type: ERPEntityType,
        since: datetime | None = None,
        page: int = 1,
        page_size: int = 100,
    ) -> list[dict[str, Any]]:
        path = _ENTITY_PATHS.get(entity_type)
        if path is None:
            logger.warning("SAPConnector: unsupported entity_type %s", entity_type)
            return []

        params: dict[str, Any] = {
            "$format": "json",
            "$top": page_size,
            "$skip": (page - 1) * page_size,
        }
        if since:
            modified_field = _MODIFIED_FIELDS.get(entity_type, "LastChangeDateTime")
            params["$filter"] = f"{modified_field} gt datetime'{since.isoformat()}'"

        data = await self._get(path, params=params)
        records: list[dict[str, Any]] = data.get("value", [])
        logger.debug(
            "SAPConnector: fetched %d %s records (page %d)",
            len(records), entity_type, page,
        )
        return records

    def normalise(
        self,
        entity_type: ERPEntityType,
        raw: dict[str, Any],
    ) -> ERPRawEvent:
        id_field = _ID_FIELDS.get(entity_type, "ID")
        source_id = str(raw.get(id_field, ""))
        modified_field = _MODIFIED_FIELDS.get(entity_type, "LastChangeDateTime")
        occurred_raw = raw.get(modified_field, "")

        try:
            occurred_at = datetime.fromisoformat(
                str(occurred_raw).replace("/Date(", "").replace(")/", "")
                if "/Date(" in str(occurred_raw)
                else str(occurred_raw)
            )
        except (ValueError, TypeError):
            occurred_at = datetime.utcnow()

        return ERPRawEvent(
            source_system=ERPSystem.SAP,
            entity_type=entity_type,
            source_id=source_id,
            tenant_id=self.config.tenant_id,
            occurred_at=occurred_at,
            payload=raw,
        )
