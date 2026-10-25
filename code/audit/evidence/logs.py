"""Parse key=value log evidence into observations.

Structured logs carry the probe that produced them in `lookup_key`, which is the
identifier under investigation. The matching `*_completed` line states the
result (rows, http_status, result, archive_present) for one resource.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

from ..loaders import parse_time
from ..model import Observation

LINE_TIME = re.compile(r"^(\d{4}-\d{2}-\d{2}T[0-9:]+Z)\s+")
PAIR = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)=(\"[^\"]*\"|\S+)")

PIPE_ROW = re.compile(
    r"^\s*-\s*(\d{4}-\d{2}-\d{2}T[0-9:]+Z)\s*\|\s*([a-z_]+)\s*\|\s*([A-Za-z0-9_]+)\s*"
    r"\|\s*([A-Za-z_]+)\s*\|\s*([A-Za-z_]+)\s*\|\s*(.+?)\s*$")

ABSENT_STATES = {"NOT_FOUND", "ABSENT", "DELETED", "MISSING", "PURGED"}
CLEAN_STATES = {"ANONYMIZED", "REDACTED", "TOMBSTONED", "NO_PII"}

PROBE_SYSTEMS = {
    "support_replica": "support_platform",
    "legacy_contact_index": "support_platform",
    "account_service": "account_service",
    "analytics_platform": "analytics_platform",
    "integration_service": "integration_service",
    "backup_service": "backup_service",
    "search_service": "search_service",
    "support_platform": "support_platform",
    "security_service": "security_service",
    "export_service": "export_service",
    "notification_service": "email_delivery_service",
    "object_storage": "object_storage",
    "identity_service": "identity_service",
    "marketing_platform": "marketing_platform",
    "archive_service": "archive_service",
    "legal_service": "legal_service",
    "cache_service": "cache_service",
}

PII_KEYS = ("email", "requester_email", "customer_email", "owner_email", "phone",
            "requester_phone", "owner_phone", "email_hash", "full_name", "name",
            "requester_name", "display_name")

USER_KEYS = ("customer_reference", "subject_reference", "user_id")

SYSTEM_COLLECTIONS = {
    "account_service": "customer_profiles",
    "analytics_platform": "customer_analytics_reports",
    "integration_service": "connectors",
    "backup_service": "backups",
    "search_service": "customer_search_documents",
    "support_platform": "support_conversations",
    "security_service": "security_audit_events",
    "export_service": "customer_exports",
    "email_delivery_service": "email_deliveries",
    "object_storage": "object_storage_objects",
    "identity_service": "deleted_customer_references",
    "marketing_platform": "marketing_profiles",
    "archive_service": "security_audit_events",
    "legal_service": "retained_order_records",
    "cache_service": "cache_entries",
}

NULLISH = {"null", "none", "None", "", "false", "0"}


def parse_log_file(path: str, file_id: str, fallback_time, raw: str) -> List[Observation]:
    out: List[Observation] = []
    pending: Dict[str, Dict[str, str]] = {}
    for line in raw.splitlines():
        pipe = PIPE_ROW.match(line)
        if pipe:
            observation = _pipe_observation(pipe, file_id, fallback_time)
            if observation is not None:
                out.append(observation)
            continue
        if "=" not in line:
            continue
        stamp_match = LINE_TIME.match(line)
        stamped = parse_time(stamp_match.group(1)) if stamp_match else fallback_time
        fields = _pairs(line)
        if not fields:
            continue
        service = fields.get("service", "")
        if service in ("readback_collector", "observability", "collector"):
            continue
        system = PROBE_SYSTEMS.get(service)
        if system is None:
            continue
        event = fields.get("event", "")
        trace = fields.get("trace_id", "")
        resource_id = fields.get("resource_id", "").strip('"')
        if not resource_id:
            continue
        if event.endswith("_started"):
            pending[trace] = {"lookup_key": fields.get("lookup_key")
                              or fields.get("match_key", "")}
            continue
        lookup = (fields.get("lookup_key") or fields.get("match_key")
                  or pending.get(trace, {}).get("lookup_key", ""))
        # A replica/legacy contact index is a standalone contact row, not a
        # conversation: it is deleted outright rather than redacted in place.
        contact_index = service in ("support_replica", "legacy_contact_index")
        observation = _build(system, resource_id, fields, lookup, file_id, stamped,
                             "support_contacts" if contact_index else "")
        if observation is not None:
            out.append(observation)
    return out


def _pairs(line: str) -> Dict[str, str]:
    fields: Dict[str, str] = {}
    for match in PAIR.finditer(line):
        fields[match.group(1)] = match.group(2).strip('"')
    return fields


def _build(system, resource_id, fields, lookup, file_id, stamped,
           collection_override: str = "") -> Optional[Observation]:
    collection = collection_override or SYSTEM_COLLECTIONS.get(system, system)
    state = _presence(fields)
    if state is None:
        return None
    exposed = [key for key in PII_KEYS
               if fields.get(key) not in (None, "null", "None", "")]
    identifiers = {
        "user_ids": [fields[key] for key in USER_KEYS
                     if fields.get(key) not in (None, "null", "None", "")],
        "emails": [fields[key].lower() for key in ("email", "requester_email",
                                                   "customer_email", "owner_email")
                   if fields.get(key) not in (None, "null", "None", "")],
        "phones": [fields[key] for key in ("phone", "requester_phone", "owner_phone")
                   if fields.get(key) not in (None, "null", "None", "")],
        "hashes": [fields[key].lower() for key in ("email_hash",)
                   if fields.get(key) not in (None, "null", "None", "")],
        "names": [fields[key] for key in ("full_name", "name", "requester_name")
                  if fields.get(key) not in (None, "null", "None", "")],
    }
    for candidate in (lookup, fields.get("matched_value", "")):
        if not candidate or candidate in ("null", "None"):
            continue
        if candidate.startswith("user_"):
            identifiers["user_ids"].append(candidate)
        elif "@" in candidate:
            identifiers["emails"].append(candidate.lower())
            exposed.append("matched_value")
    correlation = fields.get("correlation_key", "")
    if len(correlation) >= 32:
        identifiers["hashes"].append(correlation.lower())
    attributes: Dict[str, str] = {}
    for key in ("enabled", "restore_allowed", "archive_present", "last_delivery_status",
                "event_code", "retention_until", "event_name", "connector_name",
                "index", "audience_cohort", "http_status", "rows", "result"):
        if fields.get(key) not in (None, "null", "None", ""):
            attributes[key] = fields[key]
    return Observation(
        system=system,
        resource_id=resource_id,
        collection=collection,
        file_id=file_id,
        observed_at=stamped,
        present=state,
        user_ids=tuple(dict.fromkeys(identifiers["user_ids"])),
        emails=tuple(dict.fromkeys(identifiers["emails"])),
        phones=tuple(dict.fromkeys(identifiers["phones"])),
        hashes=tuple(dict.fromkeys(identifiers["hashes"])),
        names=tuple(dict.fromkeys(identifiers["names"])),
        exposed=tuple(sorted(set(exposed))) if state else (),
        attributes=attributes,
    )


def _presence(fields) -> Optional[bool]:
    if "http_status" in fields:
        return fields["http_status"] != "404"
    if "rows" in fields:
        return fields["rows"] not in ("0", "")
    if "result" in fields:
        return fields["result"] == "hit"
    if "archive_present" in fields:
        return fields["archive_present"] not in ("false", "0")
    if "enabled" in fields:
        return True
    if "resource_id" in fields:
        return True
    return None
def _pipe_observation(match, file_id, fallback_time) -> Optional[Observation]:
    """Handover sheets: `- ts | system | resource | category | state | subject`."""
    stamped = parse_time(match.group(1)) or fallback_time
    system = match.group(2)
    resource_id = match.group(3)
    category = match.group(4).upper()
    state = match.group(5).upper()
    subject = match.group(6).strip()
    collection = SYSTEM_COLLECTIONS.get(system, system)
    if "ATTACHMENT" in category:
        collection = "support_attachments"
    elif "MESSAGE" in category or "CONVERSATION" in category:
        collection = "support_conversations"
    present = state not in ABSENT_STATES
    emails = (subject.lower(),) if "@" in subject else ()
    user_ids = (subject,) if subject.startswith("user_") else ()
    exposed = ("email",) if emails and present and state not in CLEAN_STATES else ()
    attributes: Dict[str, str] = {"state": state}
    if system == "backup_service":
        attributes["restore_allowed"] = "true" if state == "ACTIVE" else "false"
    if system == "integration_service":
        attributes["enabled"] = "false" if state in ("DISABLED", "STOPPED") else "true"
    return Observation(
        system=system,
        resource_id=resource_id,
        collection=collection,
        file_id=file_id,
        observed_at=stamped,
        present=present,
        user_ids=user_ids,
        emails=emails,
        exposed=exposed,
        attributes=attributes,
    )
