"""Dataset loaders: CSV tables, timestamps and shared dataclasses."""

from __future__ import annotations

import csv
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional


def parse_time(value: str) -> Optional[datetime]:
    """Parse an ISO-8601 UTC timestamp such as 2026-09-03T11:30:00Z."""
    if not value:
        return None
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        stamp = datetime.fromisoformat(text)
    except ValueError:
        return None
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=timezone.utc)
    return stamp.astimezone(timezone.utc)


def read_csv(path: str) -> List[Dict[str, str]]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return [
            {(k or "").strip(): (v or "").strip() for k, v in row.items()}
            for row in csv.DictReader(handle)
        ]


def normalise(value: str) -> str:
    return (value or "").strip().lower()


@dataclass
class Case:
    case_id: str
    email: str
    requested_at: datetime
    reported_status: str
    reported_at: datetime
    audit_at: datetime
    request_text: str
    is_new: bool = True


@dataclass
class Identity:
    user_id: str
    name: str
    email: str
    phone: str
    email_hash: str
    updated_at: Optional[datetime]


@dataclass
class AuditEntry:
    audit_id: str
    user_id: str
    event_time: datetime
    field_name: str
    old_value: str
    new_value: str


@dataclass
class Activity:
    activity_id: str
    event_time: datetime
    event_type: str
    source_system: str
    target_system: str
    resource_id: str
    reported_result: str
    details: str


@dataclass
class EvidenceFile:
    file_id: str
    file_path: str
    origin: str
    captured_at: datetime


@dataclass
class Dataset:
    root: str
    requests: List[Case] = field(default_factory=list)
    sample_requests: List[Case] = field(default_factory=list)
    identities: Dict[str, Identity] = field(default_factory=dict)
    identity_by_email: Dict[str, str] = field(default_factory=dict)
    audit_log: List[AuditEntry] = field(default_factory=list)
    activities: List[Activity] = field(default_factory=list)
    rules: List[Dict[str, str]] = field(default_factory=list)
    evidence: List[EvidenceFile] = field(default_factory=list)

    @property
    def dataset_dir(self) -> str:
        return os.path.join(self.root, "dataset")

    @property
    def evidence_dir(self) -> str:
        return os.path.join(self.dataset_dir, "evidence")
def _to_cases(rows: List[Dict[str, str]], is_new: bool) -> List[Case]:
    cases: List[Case] = []
    for row in rows:
        requested = parse_time(row.get("requested_at", ""))
        reported = parse_time(row.get("reported_at", ""))
        audit = parse_time(row.get("audit_at", ""))
        if requested is None or reported is None or audit is None:
            continue
        cases.append(
            Case(
                case_id=row["case_id"],
                email=row["email"],
                requested_at=requested,
                reported_status=row["reported_status"],
                reported_at=reported,
                audit_at=audit,
                request_text=row.get("request_text", ""),
                is_new=is_new,
            )
        )
    return cases


def load_dataset(root: str) -> Dataset:
    """Load every CSV table the audit needs from <root>/dataset."""
    data = Dataset(root=root)
    base = data.dataset_dir

    data.requests = _to_cases(read_csv(os.path.join(base, "deletion_requests.csv")), True)
    data.sample_requests = _to_cases(
        read_csv(os.path.join(base, "sample_deletion_requests.csv")), False
    )

    for row in read_csv(os.path.join(base, "user_identities.csv")):
        identity = Identity(
            user_id=row["user_id"],
            name=row["name"],
            email=row["email"],
            phone=row["phone"],
            email_hash=row["email_hash"],
            updated_at=parse_time(row["updated_at"]),
        )
        data.identities[identity.user_id] = identity
        if identity.email:
            data.identity_by_email.setdefault(normalise(identity.email), identity.user_id)

    for row in read_csv(os.path.join(base, "user_audit_log.csv")):
        stamp = parse_time(row["event_time"])
        if stamp is None:
            continue
        data.audit_log.append(
            AuditEntry(
                audit_id=row["audit_id"],
                user_id=row["user_id"],
                event_time=stamp,
                field_name=row["field_name"],
                old_value=row["old_value"],
                new_value=row["new_value"],
            )
        )
    data.audit_log.sort(key=lambda entry: (entry.event_time, entry.audit_id))

    for row in read_csv(os.path.join(base, "system_activity.csv")):
        stamp = parse_time(row["event_time"])
        if stamp is None:
            continue
        data.activities.append(
            Activity(
                activity_id=row["activity_id"],
                event_time=stamp,
                event_type=row["event_type"],
                source_system=row["source_system"],
                target_system=row["target_system"],
                resource_id=row["resource_id"],
                reported_result=row["reported_result"],
                details=row["details"],
            )
        )
    data.activities.sort(key=lambda item: (item.event_time, item.activity_id))
    data.rules = read_csv(os.path.join(base, "deletion_rules.csv"))

    for row in read_csv(os.path.join(base, "evidence_files.csv")):
        stamp = parse_time(row["captured_at"])
        if stamp is None:
            continue
        data.evidence.append(
            EvidenceFile(
                file_id=row["file_id"],
                file_path=row["file_path"],
                origin=row["origin"],
                captured_at=stamp,
            )
        )
    data.evidence.sort(key=lambda item: (item.captured_at, item.file_id))
    return data


def offset(base: datetime, minutes: float) -> datetime:
    return base + timedelta(minutes=minutes)
