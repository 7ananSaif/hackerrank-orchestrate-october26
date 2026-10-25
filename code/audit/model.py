"""Shared value objects for evidence observations and per-case state."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Dict, List, Optional, Tuple

# Field names that count as direct personal identifiers.
PII_FIELDS = ("full_name", "name", "email", "phone", "email_hash", "display_name",
              "requester_name", "requester_email", "requester_phone", "owner_email",
              "owner_phone", "customer_email")


@dataclass
class Observation:
    """One statement, from one evidence file, about one resource."""

    system: str
    resource_id: str
    collection: str
    file_id: str
    observed_at: datetime
    present: bool = True
    user_ids: Tuple[str, ...] = ()
    emails: Tuple[str, ...] = ()
    phones: Tuple[str, ...] = ()
    hashes: Tuple[str, ...] = ()
    names: Tuple[str, ...] = ()
    exposed: Tuple[str, ...] = ()
    attributes: Dict[str, str] = field(default_factory=dict)

    @property
    def has_identifier(self) -> bool:
        return bool(self.emails or self.phones or self.hashes or self.user_ids)

    @property
    def pii_present(self) -> bool:
        return bool(self.exposed)


@dataclass
class ResourceState:
    """Resolved state of one resource at a case's audit_at."""

    system: str
    resource_id: str
    collection: str
    present: bool
    exposed: Tuple[str, ...]
    observation: Optional[Observation]
    evidence_id: str
    source: str  # "evidence" or "activity"
    attributes: Dict[str, str] = field(default_factory=dict)

    @property
    def key(self) -> Tuple[str, str]:
        return (self.system, self.resource_id)

    @property
    def redacted(self) -> bool:
        return self.present and not self.exposed
