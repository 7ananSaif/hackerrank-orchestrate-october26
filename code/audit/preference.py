"""Rank evidence files by how directly they probe a system.

A purpose-built probe (a readback log or a service_resource_export) states the
state of one resource at one moment. A snapshot bundle or a bulk capture is a
side channel: it can confirm presence but is a weaker citation for the same fact.
Ranking by origin lets the audit cite the strongest available proof instead of the
most recent file that happens to mention the system.
"""

from __future__ import annotations

from typing import Dict

# Higher means "more direct evidence for the resource it mentions".
ORIGIN_WEIGHT: Dict[str, int] = {
    "service_readback_logs": 5,
    "service_resource_export": 5,
    "customer_account_failover_replica_capture": 4,
    "customer_search_primary_capture": 4,
    "customer_account_service": 4,
    "support_platform": 4,
    "search_index_service": 4,
    "export_service": 4,
    "analytics_platform": 4,
    "security_service": 4,
    "security_audit_service": 4,
    "identity_service": 4,
    "integration_management_service": 4,
    "downstream_delivery_service": 4,
    "object_storage": 4,
    "backup_service": 4,
    "marketing_platform": 4,
    "account_history_service": 4,
    "legal_retention_service": 4,
    "account_admin_portal": 3,
    "search_index_admin": 3,
    "integration_admin": 3,
    "central_observability_export": 3,
    "customer_data_inventory_capture": 3,
    "customer_data_read_replica_capture": 3,
    "customer_data_regional_replicas_capture": 3,
    "customer_data_reporting_replica_capture": 3,
    "customer_data_failover_replica_capture": 3,
    "records_assurance_snapshot_bundle": 1,
}

DEFAULT_WEIGHT = 2


def origin_weight(origin: str) -> int:
    return ORIGIN_WEIGHT.get((origin or "").strip(), DEFAULT_WEIGHT)
