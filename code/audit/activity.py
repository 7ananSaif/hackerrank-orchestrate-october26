"""Link a case to its resources through the deletion workflow in the activity stream."""

from __future__ import annotations

from datetime import timedelta
from typing import Dict, List, Optional, Tuple

from .loaders import Activity, Case, Dataset

# Activity target system -> the system id used in the answer steps.
SYSTEM_ALIASES = {
    "account_service": "account_service",
    "account_replication_cluster": "account_service",
    "account_failover_replica": "account_service",
    "search_service": "search_service",
    "analytics_platform": "analytics_platform",
    "support_platform": "support_platform",
    "export_service": "export_service",
    "object_store": "object_storage",
    "object_storage": "object_storage",
    "integration_service": "integration_service",
    "backup_service": "backup_service",
    "security_service": "security_service",
    "archive_service": "security_service",
    "identity_service": "identity_service",
    "marketing_platform": "marketing_platform",
    "email_delivery_service": "email_delivery_service",
    "cache_service": "cache_service",
    "legal_service": "legal_service",
}

WORKFLOW_RESULT = {
    "DELETE_RECORD": "deleted",
    "REDACT_RECORD": "redacted",
    "ANONYMIZE_RECORD": "anonymized",
    "DISABLE_DATA_FLOW": "disabled",
    "BLOCK_RESTORE": "blocked",
    "RETAIN_RECORD": "retained",
    "SYNC_RECORD": "synced",
    "INDEX_RECORD": "indexed",
    "REFRESH_CACHE": "cached",
    "CREATE_EXPORT": "exported",
    "SEND_EMAIL": "emailed",
}

BEFORE = timedelta(minutes=150)
AFTER = timedelta(minutes=60)


def case_window(case: Case) -> Tuple:
    return (case.reported_at - BEFORE, case.reported_at + AFTER)


def candidate_activities(dataset: Dataset, case: Case) -> List[Activity]:
    start, end = case_window(case)
    upper = min(end, case.audit_at)
    return [item for item in dataset.activities if start <= item.event_time <= upper]


def workflow_activities(dataset: Dataset, case: Case) -> List[Activity]:
    """Activities of the deletion workflow only (not unrelated traffic)."""
    return [item for item in candidate_activities(dataset, case)
            if item.source_system == "deletion_worker"]


def resource_system(resource_id: str, target_system: str) -> str:
    return SYSTEM_ALIASES.get(target_system, target_system or prefix_system(resource_id))


def prefix_system(resource_id: str) -> str:
    prefix = resource_id.split("_")[0]
    return {
        "account": "account_service",
        "search": "search_service",
        "analytics": "analytics_platform",
        "support": "support_platform",
        "export": "export_service",
        "object": "object_storage",
        "data": "integration_service",
        "backup": "backup_service",
        "audit": "security_service",
        "tombstone": "identity_service",
        "marketing": "marketing_platform",
        "email": "email_delivery_service",
        "cache": "cache_service",
        "legal": "legal_service",
    }.get(prefix, "unknown")


def resource_prefixes(resource_id: str) -> str:
    return resource_id.split("_")[0]


def last_claim(dataset: Dataset, resource_id: str, audit_at) -> Optional[Activity]:
    """Most recent workflow statement about a resource, at or before audit_at."""
    latest: Optional[Activity] = None
    for item in dataset.activities:
        if item.resource_id != resource_id:
            continue
        if item.event_time > audit_at:
            continue
        if item.event_type not in WORKFLOW_RESULT:
            continue
        if latest is None or item.event_time >= latest.event_time:
            latest = item
    return latest


def claim_state(activity: Activity) -> str:
    return WORKFLOW_RESULT.get(activity.event_type, "present")


def flow_state(dataset: Dataset, resource_id: str, audit_at) -> Optional[bool]:
    """True when an integration flow still copies data at audit_at."""
    relevant = [item for item in dataset.activities
                if item.resource_id == resource_id and item.event_time <= audit_at
                and item.event_type in ("CHECK_DATA_FLOW", "DISABLE_DATA_FLOW")]
    if not relevant:
        return None
    latest = max(relevant, key=lambda item: item.event_time)
    if latest.event_type == "DISABLE_DATA_FLOW":
        return False if latest.reported_result == "SUCCESS" else True
    text = latest.details.lower()
    if "remains enabled" in text:
        return True
    if "disabled" in text or "inactive" in text:
        return False
    return None


def restore_state(dataset: Dataset, resource_id: str, audit_at) -> Optional[bool]:
    """True when a backup can still be restored at audit_at."""
    relevant = [item for item in dataset.activities
                if item.resource_id == resource_id and item.event_time <= audit_at
                and item.event_type in ("CHECK_RESTORE_ACCESS", "BLOCK_RESTORE",
                                        "RESTORE_BACKUP")]
    if not relevant:
        return None
    latest = max(relevant, key=lambda item: item.event_time)
    if latest.event_type == "BLOCK_RESTORE":
        return False if latest.reported_result == "SUCCESS" else True
    if latest.event_type == "RESTORE_BACKUP":
        return True
    text = latest.details.lower()
    if "still be restored" in text:
        return True
    if "blocked" in text or "cannot be restored" in text:
        return False
    return None
