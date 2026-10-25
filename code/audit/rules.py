"""Apply deletion_rules.csv to a resolved resource state."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .model import ResourceState

DELETE = "DELETE"
REDACT = "REDACT"
ANONYMIZE = "ANONYMIZE"
RETAIN = "RETAIN"
BLOCK_RESTORE = "BLOCK_RESTORE"
DISABLE_FLOW = "DISABLE_FLOW"

# (system, collection substring) -> data category from deletion_rules.csv
CATEGORY_RULES = [
    (("account_service", ""), "USER_PROFILE"),
    (("search_service", ""), "SEARCH_INDEX_ENTRY"),
    (("cache_service", ""), "CACHE_ENTRY"),
    (("support_platform", "attachment"), "SUPPORT_ATTACHMENT"),
    (("object_storage", "attachment"), "SUPPORT_ATTACHMENT"),
    (("support_platform", "support_contacts"), "SECONDARY_IDENTIFIER"),
    (("support_platform", "support_conversations"), "SUPPORT_MESSAGE"),
    (("support_platform", ""), "SUPPORT_ATTACHMENT"),
    (("object_storage", ""), "SUPPORT_ATTACHMENT"),
    (("analytics_platform", ""), "ANALYTICS_PROFILE"),
    (("marketing_platform", ""), "MARKETING_PROFILE"),
    (("export_service", ""), "USER_EXPORT"),
    (("email_delivery_service", ""), "EMAIL_DELIVERY_LOG"),
    (("security_service", ""), "SECURITY_AUDIT_LOG"),
    (("legal_service", ""), "LEGAL_HOLD_RECORD"),
    (("backup_service", ""), "BACKUP_ARCHIVE"),
    (("identity_service", ""), "ACCOUNT_TOMBSTONE"),
    (("integration_service", ""), "SECONDARY_IDENTIFIER"),
]

CATEGORY_ACTION = {
    "USER_PROFILE": DELETE,
    "SECONDARY_IDENTIFIER": DELETE,
    "SEARCH_INDEX_ENTRY": DELETE,
    "CACHE_ENTRY": DELETE,
    "SUPPORT_MESSAGE": REDACT,
    "SUPPORT_ATTACHMENT": DELETE,
    "ANALYTICS_PROFILE": ANONYMIZE,
    "PRODUCT_TELEMETRY": ANONYMIZE,
    "MARKETING_PROFILE": DELETE,
    "USER_EXPORT": DELETE,
    "EMAIL_DELIVERY_LOG": REDACT,
    "SECURITY_AUDIT_LOG": RETAIN,
    "LEGAL_HOLD_RECORD": RETAIN,
    "BACKUP_ARCHIVE": BLOCK_RESTORE,
    "ACCOUNT_TOMBSTONE": REDACT,
}

# Systems whose retention records are verified present in every case.
RETAINED_SYSTEMS = ("security_service", "legal_service")


@dataclass
class PolicyItem:
    system: str
    resource_id: str
    category: str
    action: str
    state: ResourceState


def category_for(system: str, collection: str) -> str:
    if system == "integration_service":
        return "SECONDARY_IDENTIFIER"
    for (rule_system, needle), category in CATEGORY_RULES:
        if rule_system != system:
            continue
        if needle and needle not in (collection or ""):
            continue
        return category
    return "SECONDARY_IDENTIFIER"


def action_for(system: str, collection: str) -> str:
    category = category_for(system, collection)
    action = CATEGORY_ACTION.get(category, DELETE)
    if system == "backup_service":
        return BLOCK_RESTORE
    if system == "integration_service":
        return DISABLE_FLOW
    return action


def classify_states(states: List[ResourceState]) -> List[PolicyItem]:
    items: List[PolicyItem] = []
    for state in states:
        category = category_for(state.system, state.collection)
        action = action_for(state.system, state.collection)
        # A workflow that tried to delete the record shows the treatment wanted.
        if state.attributes.get("claim") == "DELETE_RECORD":
            category = "USER_PROFILE" if state.system == "account_service" else category
            action = DELETE
        items.append(
            PolicyItem(
                system=state.system,
                resource_id=state.resource_id,
                category=category,
                action=action,
                state=state,
            )
        )
    return items


def flow_active(item: PolicyItem) -> bool:
    value = (item.state.attributes.get("enabled") or "").lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    return item.state.present


def restore_open(item: PolicyItem) -> bool:
    value = (item.state.attributes.get("restore_allowed") or "").lower()
    if value in ("true", "1", "yes"):
        return True
    if value in ("false", "0", "no"):
        return False
    return item.state.present


def is_retained(item: PolicyItem) -> bool:
    return item.action == RETAIN
