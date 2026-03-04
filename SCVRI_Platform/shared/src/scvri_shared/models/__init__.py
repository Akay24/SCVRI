"""SCVRI shared models — public re-exports.

Import from here to get all models into Alembic's metadata::

    from scvri_shared.models import Base, Supplier, Alert, ...

"""
from scvri_shared.models.base import (
    Base,
    SoftDeleteMixin,
    TenantMixin,
    TimestampMixin,
    UUIDPrimaryKeyMixin,
)
from scvri_shared.models.tenant import Tenant
from scvri_shared.models.auth import (
    RefreshToken,
    Role,
    User,
    UserRole,
)
from scvri_shared.models.supplier import (
    Supplier,
    SupplierCertification,
    SupplierContact,
    SupplierDocument,
    SupplierScorecard,
)
from scvri_shared.models.purchase_order import (
    POLineItem,
    PurchaseOrder,
)
from scvri_shared.models.shipment import (
    IoTTelemetry,
    Shipment,
    ShipmentEvent,
)
from scvri_shared.models.risk import (
    KRIDefinition,
    KRISnapshot,
    RiskRule,
    RiskScoreHistory,
    SupplierRiskScore,
)
from scvri_shared.models.alert import (
    Alert,
    AlertEscalation,
    NotificationLog,
    NotificationSubscription,
    WebhookEndpoint,
)
from scvri_shared.models.compliance import (
    ConsentRecord,
    DataProcessingRecord,
    ErasureRequest,
)
from scvri_shared.models.audit import AuditLog

__all__ = [
    # Base
    "Base",
    "SoftDeleteMixin",
    "TenantMixin",
    "TimestampMixin",
    "UUIDPrimaryKeyMixin",
    # Tenant
    "Tenant",
    # Auth
    "RefreshToken",
    "Role",
    "User",
    "UserRole",
    # Supplier
    "Supplier",
    "SupplierCertification",
    "SupplierContact",
    "SupplierDocument",
    "SupplierScorecard",
    # Purchase Orders
    "POLineItem",
    "PurchaseOrder",
    # Shipments
    "IoTTelemetry",
    "Shipment",
    "ShipmentEvent",
    # Risk
    "KRIDefinition",
    "KRISnapshot",
    "RiskRule",
    "RiskScoreHistory",
    "SupplierRiskScore",
    # Alerts
    "Alert",
    "AlertEscalation",
    "NotificationLog",
    "NotificationSubscription",
    "WebhookEndpoint",
    # Compliance
    "ConsentRecord",
    "DataProcessingRecord",
    "ErasureRequest",
    # Audit
    "AuditLog",
]
