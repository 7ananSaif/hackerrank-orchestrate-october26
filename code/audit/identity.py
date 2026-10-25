"""Identity resolution: current and historical identifiers for a case subject."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Set

from .loaders import Case, Dataset, normalise

LINK_EMAIL = re.compile(r"linked\s+(\S+)\s+\([^)]*\)\s+to\s+(\S+)\s+and\s+(user_\d+)")
LINK_ATTACH = re.compile(r"confirmed\s+(\S+)\s+\([^)]*\)\s+belongs only to\s+(\S+)\s+and\s+(user_\d+)")


@dataclass
class Subject:
    """Every identifier that may still point at the person behind a case."""

    case_id: str
    user_id: Optional[str] = None
    emails: Set[str] = field(default_factory=set)
    phones: Set[str] = field(default_factory=set)
    hashes: Set[str] = field(default_factory=set)
    names: Set[str] = field(default_factory=set)
    resolved_via: str = "none"

    def matches(self, user_ids=(), emails=(), phones=(), hashes=()) -> bool:
        """True when any supplied identifier belongs to this subject."""
        ids = {value for value in user_ids if value}
        if self.user_id and self.user_id in ids:
            return True
        mail = {normalise(value) for value in emails if value}
        if mail and self.emails & mail:
            return True
        tel = {value.strip() for value in phones if value}
        if tel and self.phones & tel:
            return True
        digests = {value.strip().lower() for value in hashes if value}
        if digests and self.hashes & digests:
            return True
        return False
def build_subjects(dataset: Dataset, cases: List[Case]) -> Dict[str, Subject]:
    """Map case_id -> Subject using the snapshot plus the identity audit trail."""
    by_email: Dict[str, List[str]] = {}
    for entry in dataset.audit_log:
        if entry.field_name != "email":
            continue
        for value in (entry.old_value, entry.new_value):
            if value:
                by_email.setdefault(normalise(value), []).append(entry.user_id)

    subjects: Dict[str, Subject] = {}
    for case in cases:
        email = normalise(case.email)
        subject = Subject(case_id=case.case_id, emails={email})

        user_id = dataset.identity_by_email.get(email)
        if user_id:
            subject.resolved_via = "current_snapshot"
        elif by_email.get(email):
            user_id = by_email[email][0]
            subject.resolved_via = "audit_log"
        subject.user_id = user_id

        if user_id:
            identity = dataset.identities.get(user_id)
            if identity:
                if identity.email:
                    subject.emails.add(normalise(identity.email))
                if identity.phone:
                    subject.phones.add(identity.phone.strip())
                if identity.email_hash:
                    subject.hashes.add(identity.email_hash.strip().lower())
                if identity.name:
                    subject.names.add(normalise(identity.name))

        for entry in dataset.audit_log:
            if user_id:
                if entry.user_id != user_id:
                    continue
            else:
                known = {normalise(entry.old_value), normalise(entry.new_value)}
                if email not in known:
                    continue
            for value in (entry.old_value, entry.new_value):
                if not value:
                    continue
                if entry.field_name == "email":
                    subject.emails.add(normalise(value))
                elif entry.field_name == "phone":
                    subject.phones.add(value.strip())
                elif entry.field_name == "email_hash":
                    subject.hashes.add(value.strip().lower())

        subject.emails = {value for value in subject.emails if value}
        subject.phones = {value for value in subject.phones if value}
        subjects[case.case_id] = subject
    return subjects


def catalog_links(dataset: Dataset) -> Dict[str, List[dict]]:
    """Resource -> subject links published by the data catalog activity."""
    links: Dict[str, List[dict]] = {}
    for activity in dataset.activities:
        if activity.event_type != "LINK_RESOURCE_IDENTITY":
            continue
        match = LINK_EMAIL.search(activity.details) or LINK_ATTACH.search(activity.details)
        if not match:
            continue
        links.setdefault(match.group(1), []).append(
            {
                "resource_id": match.group(1),
                "email": normalise(match.group(2)),
                "user_id": match.group(3),
                "system": activity.target_system,
                "activity_id": activity.activity_id,
                "at": activity.event_time,
            }
        )
    return links
