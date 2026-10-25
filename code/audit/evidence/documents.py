"""Parse PDF business documents into observations (text layer, no OCR)."""

from __future__ import annotations

import re
from typing import Dict, List, Optional, Tuple

from ..loaders import parse_time
from ..model import Observation

RESOURCE = re.compile(r"\b((?:support|audit_record|object|legal_hold|export|backup|"
                      r"data_flow|account|search|analytics|cache|tombstone|marketing)"
                      r"_[0-9A-Za-z]+)\b")
EMAIL = re.compile(r"[\w.+-]+@[\w-]+\.[\w.]+")
USER_ID = re.compile(r"\buser_\d+\b")
REGISTER_ROW = re.compile(r"(ORD-\d+)\s*\|\s*(user_\d+)\s*\|\s*([^|]+)\|")
RETAIN = re.compile(r"[Rr]etain(?:-| )until\s+([0-9A-Za-z :,-]+)")
STATEMENT = re.compile(r"statement\s+(NST-[0-9-]+)", re.I)

DOCUMENT_SYSTEMS = {
    "delivery_correction_attachment.pdf": ("support_platform", "support_attachments"),
    "support_attachment": ("support_platform", "support_attachments"),
    "account_history_report": ("export_service", "customer_exports"),
    "legal_retention_register": ("legal_service", "retained_order_records"),
    "security_retention_extract": ("security_service", "security_audit_events"),
}


def _system_for(path: str) -> Tuple[str, str]:
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    for prefix, mapping in DOCUMENT_SYSTEMS.items():
        if name.startswith(prefix):
            return mapping
    return ("document_store", "documents")


def _read_text(path: str) -> str:
    try:
        import pdfplumber
    except ImportError:
        return ""
    lines: List[str] = []
    with pdfplumber.open(path) as pdf:
        for page in pdf.pages:
            lines.append(page.extract_text() or "")
    return "\n".join(lines)


def parse_pdf_file(path: str, file_id: str, fallback_time, raw: Optional[str] = None
                   ) -> List[Observation]:
    text = raw if raw is not None else _read_text(path)
    if not text:
        return []
    system, collection = _system_for(path)
    out: List[Observation] = []
    out.extend(_register_rows(text, system, collection, file_id, fallback_time))
    out.extend(_detail_document(text, path, system, collection, file_id, fallback_time))
    return out


def _register_rows(text, system, collection, file_id, fallback_time):
    rows: List[Observation] = []
    for match in REGISTER_ROW.finditer(text):
        order, user_id, reason = match.group(1), match.group(2), match.group(3).strip()
        tail = text[match.end():match.end() + 120]
        retain = RETAIN.search(tail)
        rows.append(
            Observation(
                system=system,
                resource_id="",
                collection=collection,
                file_id=file_id,
                observed_at=fallback_time,
                present=True,
                user_ids=(user_id,),
                attributes={
                    "order_reference": order,
                    "retention_reason": reason,
                    "retention_until": retain.group(1).strip() if retain else "",
                    "event_name": "legal_hold_active",
                },
            )
        )
    return rows


def _detail_document(text, path, system, collection, file_id, fallback_time):
    name = path.replace("\\", "/").rsplit("/", 1)[-1]
    emails = tuple(dict.fromkeys(match.lower() for match in EMAIL.findall(text)))
    users = tuple(dict.fromkeys(USER_ID.findall(text)))
    resources = tuple(dict.fromkeys(RESOURCE.findall(text)))
    statement = STATEMENT.search(text)
    if not (emails or users):
        return []
    if name.startswith("account_history_report"):
        resource_id = ""
        if statement:
            resource_id = "export_" + statement.group(1).rsplit("-", 1)[-1]
        return [
            Observation(
                system=system,
                resource_id=resource_id,
                collection=collection,
                file_id=file_id,
                observed_at=fallback_time,
                present=True,
                user_ids=users,
                emails=emails,
                exposed=("owner_email",) if emails else (),
                attributes={"object_key": statement.group(1) if statement else "",
                            "document": name},
            )
        ]
    resource_id = next((item for item in resources if item.startswith("support_")), "")
    exposed = tuple(
        key for key, present in (
            ("requester_name", bool(re.search(r"Detail\s+[A-Z][a-z]+ [A-Z]", text))),
            ("requester_email", bool(emails)),
            ("requester_phone", bool(re.search(r"Detail\s+\+\d[\d ]+", text))),
        ) if present
    )
    attributes: Dict[str, str] = {"document": name}
    retain = RETAIN.search(text)
    if retain:
        attributes["retention_until"] = retain.group(1).strip()
    event = re.search(r"event\s+([A-Za-z ]+)", text)
    if event:
        attributes["event_name"] = event.group(1).strip()
    audit = next((item for item in resources if item.startswith("audit_record_")), "")
    if audit and not resource_id:
        resource_id = audit
        system, collection = "security_service", "security_audit_events"
    return [
        Observation(
            system=system,
            resource_id=resource_id,
            collection=collection,
            file_id=file_id,
            observed_at=fallback_time,
            present=True,
            user_ids=users,
            emails=emails,
            exposed=exposed if not audit else (),
            attributes=attributes,
        )
    ]
