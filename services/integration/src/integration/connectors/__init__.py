from integration.connectors.base import (
    BaseERPConnector,
    ConnectorAuthError,
    ConnectorFetchError,
)
from integration.connectors.oracle import OracleConnector
from integration.connectors.sap import SAPConnector
from integration.schemas.erp import ERPConnectionConfig, ERPSystem


def get_connector(config: ERPConnectionConfig) -> BaseERPConnector:
    """Factory — return the correct connector for *config.system*."""
    mapping: dict[ERPSystem, type[BaseERPConnector]] = {
        ERPSystem.SAP: SAPConnector,
        ERPSystem.ORACLE: OracleConnector,
    }
    cls = mapping.get(config.system)
    if cls is None:
        raise ValueError(f"No connector registered for ERP system '{config.system}'")
    return cls(config)


__all__ = [
    "BaseERPConnector",
    "ConnectorAuthError",
    "ConnectorFetchError",
    "SAPConnector",
    "OracleConnector",
    "get_connector",
]
