"""Parse JSON evidence: snapshot bundles, service exports, connectors, exports."""

from __future__ import annotations

import json
from typing import Dict, List

from ..loaders import parse_time
from ..model import Observation
from .sql_snapshots import _collect, _flatten

# (parent key, system, collection) mappings for the single-purpose JSON probes.
KNOWN_OBJECTS = {
    "connectors": ("integration_service", "connectors"),
    "exports": ("export_service", "customer_exports"),
    "restore_entries": ("backup_service", "backups"),
    "profile_lookups": ("account_service", "customer_profiles"),
    "profiles": ("analytics_platform", "customer_analytics_reports"),
    "index_queries": ("search_service", "customer_search_documents"),
    "audit_records": ("security_service", "security_audit_events"),
    "tickets": ("support_platform", "support_conversations"),
    "records": (None, None),
}


def parse_json_file(path: str, file_id: str, fallback_time, raw: str) -> List[Observation]:
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return []
    out: List[Observation] = []
    if isinstance(payload, dict) and "snapshots" in payload:
        for snapshot in payload.get("snapshots", []):
            system = snapshot.get("data_store") or "unknown"
            collection = snapshot.get("collection") or "unknown"
            stamped = parse_time(snapshot.get("captured_at", "")) or fallback_time
            for record in snapshot.get("records", []):
                out.append(_observation(record, system, collection, file_id, stamped))
        return out
    if isinstance(payload, dict) and "service_exports" in payload:
        for system, kinds in payload["service_exports"].items():
            for kind, entries in kinds.items():
                if not isinstance(entries, list):
                    continue
                collection = KNOWN_OBJECTS.get(kind, (system, kind))[1]
                for entry in entries:
                    out.extend(_entry_observation(entry, system, collection, file_id,
                                                  fallback_time))
        return out
    if isinstance(payload, dict) and isinstance(payload.get("records"), list) \
            and payload.get("collection"):
        system, collection = collection_system(str(payload["collection"]))
        stamped = parse_time(payload.get("captured_at", "")) or fallback_time
        for record in payload["records"]:
            if isinstance(record, dict):
                out.append(_observation(record, system, collection, file_id, stamped))
        return out
    if isinstance(payload, dict):
        out.extend(_generic_records(payload, file_id, fallback_time))
    elif isinstance(payload, list):
        for record in payload:
            out.extend(_generic_records(record, file_id, fallback_time))
    return out


def collection_system(collection: str):
    """Map a collection name to the system that owns it."""
    lowered = collection.lower()
    for prefix, system in (
        ("customer_export", "export_service"),
        ("export", "export_service"),
        ("connector", "integration_service"),
        ("customer_search", "search_service"),
        ("search", "search_service"),
        ("support", "support_platform"),
        ("marketing", "marketing_platform"),
        ("analytics", "analytics_platform"),
        ("customer_analytics", "analytics_platform"),
        ("security_audit", "security_service"),
        ("audit", "security_service"),
        ("legal", "legal_service"),
        ("retained_order", "legal_service"),
        ("backup", "backup_service"),
        ("object", "object_storage"),
        ("email", "email_delivery_service"),
        ("deleted_customer", "identity_service"),
        ("tombstone", "identity_service"),
        ("cache", "cache_service"),
        ("customer_profiles", "account_service"),
    ):
        if lowered.startswith(prefix):
            return (system, collection)
    return ("export_service", collection)


def _entry_observation(entry, system, collection, file_id, fallback_time):
    stamped = parse_time(entry.get("observed_at", "")) or fallback_time
    status = entry.get("status_code")
    if status is not None and int(status) == 404:
        return [
            Observation(
                system=system,
                resource_id=str(entry.get("resource_id", "")),
                collection=collection,
                file_id=file_id,
                observed_at=stamped,
                present=False,
            )
        ]
    if entry.get("profile") is None and status is not None and int(status) == 200:
        return []
    record = dict(entry)
    if isinstance(entry.get("document"), dict):
        record.update(entry["document"])
    if isinstance(entry.get("hits"), dict):
        record.pop("hits", None)
    return [_observation(record, system, collection, file_id, stamped)]


def _generic_records(payload, file_id, fallback_time):
    if not isinstance(payload, dict):
        return []
    out: List[Observation] = []
    stamped = parse_time(payload.get("exported_at", "")) or fallback_time
    for key, value in payload.items():
        if not isinstance(value, list):
            continue
        mapping = KNOWN_OBJECTS.get(key)
        if not mapping or mapping[0] is None:
            continue
        system, collection = mapping
        for record in value:
            if isinstance(record, dict):
                out.extend(_entry_observation(record, system, collection, file_id,
                                              stamped))
    return out


def _observation(record: Dict, system: str, collection: str, file_id: str,
                 stamped) -> Observation:
    flat = _flatten(record)
    flat.setdefault("resource_id", str(record.get("resource_id") or ""))
    identifiers = _collect(flat)
    attributes: Dict[str, str] = {}
    for key in ("account_status", "enabled", "restore_allowed", "last_delivery_status",
                "event_code", "retention_until", "event_name", "connector_name",
                "index_name", "audience_cohort", "message_excerpt", "archive_key",
                "object_key", "ticket_id", "query"):
        value = record.get(key)
        if value not in (None, ""):
            attributes[key] = str(value)
    return Observation(
        system=system,
        resource_id=str(record.get("resource_id") or "").strip(),
        collection=collection,
        file_id=file_id,
        observed_at=stamped,
        present=True,
        user_ids=identifiers.get("user_ids", ()),
        emails=identifiers.get("emails", ()),
        phones=identifiers.get("phones", ()),
        hashes=identifiers.get("hashes", ()),
        names=identifiers.get("names", ()),
        exposed=identifiers.get("exposed", ()),
        attributes=attributes,
    )
