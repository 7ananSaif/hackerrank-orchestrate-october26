"""Parse SQLite-compatible SQL snapshots into observations."""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import datetime
from typing import Dict, List, Optional

from ..loaders import parse_time
from ..model import PII_FIELDS, Observation

# Wide inventory tables -> (origin system, collection) used by the policy table.
INVENTORY_TABLES = {
    "customer_profiles": ("account_service", "customer_profiles"),
    "customer_search_documents": ("search_service", "customer_search_documents"),
    "customer_analytics_profiles": ("analytics_platform", "customer_analytics_reports"),
    "support_records": ("support_platform", "support_conversations"),
    "customer_exports": ("export_service", "customer_exports"),
    "connector_subscriptions": ("integration_service", "connectors"),
    "backup_restore_entries": ("backup_service", "backups"),
    "security_audit_records": ("security_service", "security_audit_events"),
}

ACCOUNT_TABLES = {
    "customer_profiles_primary": "account_service",
    "customer_profiles_failover_replica": "account_service",
    "customer_profiles_regional_replica": "account_service",
    "customer_profiles_read_replica": "account_service",
    "customer_profiles_reporting_replica": "account_service",
}

TABLE_PREFIXES = (
    ("search", "search_service", "customer_search_documents"),
    ("support", "support_platform", "support_conversations"),
    ("marketing", "marketing_platform", "marketing_profiles"),
    ("audit", "security_service", "security_audit_events"),
    ("security", "security_service", "security_audit_events"),
    ("legal", "legal_service", "retained_order_records"),
    ("backup", "backup_service", "backups"),
    ("export", "export_service", "customer_exports"),
    ("connector", "integration_service", "connectors"),
    ("data_flow", "integration_service", "connectors"),
    ("object", "object_storage", "object_storage_objects"),
    ("cache", "cache_service", "cache_entries"),
    ("email", "email_delivery_service", "email_deliveries"),
    ("analytics", "analytics_platform", "customer_analytics_reports"),
    ("customer_profiles", "account_service", "customer_profiles"),
    ("tombstone", "identity_service", "deleted_customer_references"),
)

CAPTURED = re.compile(r"Captured at:\s*([0-9T:\-Z]+)")
SNAPSHOT = re.compile(r"snapshot_completed_at=([0-9T:\-Z]+)")

IDENT_COLUMNS = {
    "customer_reference": "user_ids",
    "subject_reference": "user_ids",
    "user_id": "user_ids",
    "email": "emails",
    "requester_email": "emails",
    "customer_email": "emails",
    "owner_email": "emails",
    "phone": "phones",
    "requester_phone": "phones",
    "owner_phone": "phones",
    "email_hash": "hashes",
    "full_name": "names",
    "requester_name": "names",
    "display_name": "names",
    "name": "names",
}


def table_mapping(table_name: str):
    """Fallback mapping for snapshot table names we have not seen before."""
    lowered = table_name.lower()
    for prefix, system, collection in TABLE_PREFIXES:
        if lowered.startswith(prefix):
            return (system, collection)
    return None


def _captured(text: str, path: str) -> Optional[datetime]:
    match = CAPTURED.search(text) or SNAPSHOT.search(text)
    if match:
        return parse_time(match.group(1))
    return None


def _collect(record: Dict[str, str]) -> Dict[str, tuple]:
    buckets: Dict[str, List[str]] = {"user_ids": [], "emails": [], "phones": [],
                                     "hashes": [], "names": []}
    exposed: List[str] = []
    for key, value in record.items():
        if not value:
            continue
        bucket = IDENT_COLUMNS.get(key)
        if not bucket:
            continue
        if key in PII_FIELDS:
            exposed.append(key)
        if bucket == "user_ids":
            buckets[bucket].append(value.strip())
        elif bucket == "emails":
            buckets[bucket].append(value.strip().lower())
        elif bucket == "hashes":
            buckets[bucket].append(value.strip().lower())
        else:
            buckets[bucket].append(value.strip())
    return {key: tuple(dict.fromkeys(val)) for key, val in buckets.items()} | {
        "exposed": tuple(sorted(set(exposed)))
    }


def _flatten(record: Dict, prefix: str = "") -> Dict[str, str]:
    """Flatten nested JSON (document dicts) into the column names we match on."""
    flat: Dict[str, str] = {}
    for key, value in record.items():
        if isinstance(value, dict):
            flat.update(_flatten(value, key))
        elif isinstance(value, list):
            continue
        elif value is not None:
            flat[key] = str(value)
    return flat


def parse_sql_file(path: str, file_id: str, sql_text: str) -> List[Observation]:
    captured = _captured(sql_text, path)
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(sql_text)
    except sqlite3.Error:
        connection.close()
        return []
    observations: List[Observation] = []
    try:
        tables = [row[0] for row in
                  connection.execute("select name from sqlite_master where type='table'")]
        for table in tables:
            observations.extend(
                _rows_to_observations(connection, table, captured, file_id, sql_text)
            )
    finally:
        connection.close()
    return observations


def _rows_to_observations(connection, table, captured, file_id, sql_text):
    cursor = connection.execute(f'select * from "{table}"')
    columns = [item[0] for item in cursor.description]
    out: List[Observation] = []
    if "record_json" in columns:
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            payload = record.get("record_json") or "{}"
            try:
                data = json.loads(payload)
            except json.JSONDecodeError:
                continue
            flat = _flatten(data)
            flat.setdefault("resource_id", record.get("resource_id", ""))
            system = record.get("origin_system") or "unknown"
            collection = record.get("collection_name") or table
            stamped = parse_time(record.get("updated_at", "")) or captured
            out.append(_make(flat, system, collection, file_id, stamped, table))
        return out
    if table in ACCOUNT_TABLES:
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            out.append(
                _make(record, ACCOUNT_TABLES[table], "customer_profiles", file_id,
                      captured, table)
            )
        return out
    mapping = INVENTORY_TABLES.get(table) or table_mapping(table)
    if mapping:
        system, collection = mapping
        for row in cursor.fetchall():
            record = dict(zip(columns, row))
            stamped = parse_time(record.get("updated_at", "")) or captured
            out.append(_make(record, system, collection, file_id, stamped, table))
    return out


def _make(record, system, collection, file_id, stamped, table) -> Observation:
    identifiers = _collect(record)
    attributes: Dict[str, str] = {}
    for key in ("account_status", "enabled", "restore_allowed", "last_delivery_status",
                "event_code", "retention_until", "event_name", "connector_name",
                "index_name", "audience_cohort", "message_excerpt", "archive_key",
                "object_key", "actor_type"):
        if record.get(key) not in (None, ""):
            attributes[key] = str(record[key])
    attributes["table"] = table
    resource_id = str(record.get("resource_id") or "").strip()
    return Observation(
        system=system,
        resource_id=resource_id,
        collection=collection,
        file_id=file_id,
        observed_at=stamped or datetime.min,
        present=True,
        user_ids=identifiers.get("user_ids", ()),
        emails=identifiers.get("emails", ()),
        phones=identifiers.get("phones", ()),
        hashes=identifiers.get("hashes", ()),
        names=identifiers.get("names", ()),
        exposed=identifiers.get("exposed", ()),
        attributes=attributes,
    )
