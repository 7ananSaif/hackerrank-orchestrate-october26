"""Custom evaluation cases for the decision core.

Each case builds the minimal inputs the audit needs and asserts the emitted
steps. They cover scenarios the 32 public samples do not: an email that was
renamed before the audit, an account tombstone that must be redacted rather than
deleted, a backup that can still restore the subject, and a maintenance request
that must not be treated as a deletion.
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from code.audit import classify, rules, steps
from code.audit.model import Observation, ResourceState

AUDIT_AT = datetime(2026, 9, 20, 12, 0, tzinfo=timezone.utc)


def _state(system, resource_id, collection, present=True, exposed=(), attributes=None,
           evidence="evidence_99", source="evidence"):
    return ResourceState(
        system=system,
        resource_id=resource_id,
        collection=collection,
        present=present,
        exposed=tuple(exposed),
        observation=None,
        evidence_id=evidence if source == "evidence" else "",
        source=source,
        attributes=attributes or {},
    )


def _emitted(states):
    items = rules.classify_states(states)
    findings = steps.build_findings(items, account_id="")
    complete = not findings
    remediation = steps.build_remediation(findings)
    verification = steps.build_verification(items, findings, _NullCatalog(), AUDIT_AT,
                                            complete)
    return complete, steps.serialise(findings + remediation + verification)


class _NullCatalog:
    observations = []

    def for_resource(self, resource_id):
        return []


def case_history_email():
    """The record still carries the address the subject used before renaming."""
    renamed = Observation(
        system="search_service",
        resource_id="search_7001",
        collection="customer_search_documents",
        file_id="evidence_99",
        observed_at=AUDIT_AT,
        present=True,
        emails=("old.address@example.com",),
        exposed=("email",),
    )
    state = ResourceState(
        system="search_service", resource_id=renamed.resource_id,
        collection=renamed.collection, present=True, exposed=renamed.exposed,
        observation=renamed, evidence_id="evidence_99", source="evidence",
        attributes={},
    )
    complete, emitted = _emitted([state])
    return complete is False and emitted[0]["operation"] == "REPORT_REMAINING_RECORD"


def case_tombstone():
    """A deleted account keeps user_id only: redact, never delete."""
    state = _state("identity_service", "tombstone_70", "deleted_customer_references",
                   present=True, exposed=("email", "phone", "email_hash", "name"))
    complete, emitted = _emitted([state])
    operations = [step["operation"] for step in emitted]
    return (complete is False
            and operations[:2] == ["REPORT_EXPOSED_PII", "REDACT_RECORD"]
            and operations[-1] == "VERIFY_RECORD_REDACTED")


def case_restore_risk():
    """A backup that can still be restored defeats the deletion."""
    state = _state("backup_service", "backup_70", "backups", present=True,
                   attributes={"restore_allowed": "true"})
    complete, emitted = _emitted([state])
    operations = [step["operation"] for step in emitted]
    return (complete is False
            and operations == ["REPORT_RESTORE_RISK", "BLOCK_RESTORE",
                               "VERIFY_RESTORE_BLOCKED"])


def case_not_deletion():
    """A profile-maintenance request must not authorise destruction."""
    text = ("Please change the email address used for this account. "
            "I want to continue using the service.")
    verdict = classify.heuristic(text)
    return verdict.is_deletion is False


CASES = (
    ("history_email_still_indexed", case_history_email),
    ("tombstone_redacted_not_deleted", case_tombstone),
    ("backup_restore_risk_real", case_restore_risk),
    ("maintenance_request_not_applicable", case_not_deletion),
)


def main() -> int:
    failures = 0
    for name, check in CASES:
        passed = bool(check())
        failures += 0 if passed else 1
        print(f"{'PASS' if passed else 'FAIL'}  {name}")
    print(f"{len(CASES) - failures}/{len(CASES)} custom cases passed")
    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
