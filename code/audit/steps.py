"""Emit the ordered findings, remediation plan and verification checks."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from . import rules
from .catalog import Catalog
from .model import ResourceState
from .rules import PolicyItem

PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}

OPERATION_ORDER = {
    "REPORT_REMAINING_RECORD": 0,
    "REPORT_EXPOSED_PII": 1,
    "REPORT_ACTIVE_DATA_FLOW": 2,
    "REPORT_RESTORE_RISK": 3,
    "DISABLE_DATA_FLOW": 0,
    "BLOCK_RESTORE": 1,
    "DELETE_RECORD": 2,
    "REDACT_RECORD": 3,
    "ANONYMIZE_RECORD": 4,
    "VERIFY_RECORD_ABSENT": 0,
    "VERIFY_RECORD_PRESENT": 1,
    "VERIFY_RECORD_REDACTED": 2,
    "VERIFY_RECORD_ANONYMIZED": 3,
    "VERIFY_DATA_FLOW_DISABLED": 4,
    "VERIFY_RESTORE_BLOCKED": 5,
}

OPERATION_STATE = {
    "REPORT_REMAINING_RECORD": "PRESENT",
    "REPORT_EXPOSED_PII": "PRESENT",
    "REPORT_ACTIVE_DATA_FLOW": "ACTIVE",
    "REPORT_RESTORE_RISK": "ACTIVE",
    "DISABLE_DATA_FLOW": "DISABLED",
    "BLOCK_RESTORE": "BLOCKED",
    "DELETE_RECORD": "ABSENT",
    "REDACT_RECORD": "REDACTED",
    "ANONYMIZE_RECORD": "ANONYMIZED",
    "VERIFY_RECORD_ABSENT": "ABSENT",
    "VERIFY_RECORD_PRESENT": "PRESENT",
    "VERIFY_RECORD_REDACTED": "REDACTED",
    "VERIFY_RECORD_ANONYMIZED": "ANONYMIZED",
    "VERIFY_DATA_FLOW_DISABLED": "DISABLED",
    "VERIFY_RESTORE_BLOCKED": "BLOCKED",
}

REMEDIATION_FOR = {
    "REPORT_REMAINING_RECORD": "DELETE_RECORD",
    "REPORT_EXPOSED_PII": "REDACT_RECORD",
    "REPORT_ACTIVE_DATA_FLOW": "DISABLE_DATA_FLOW",
    "REPORT_RESTORE_RISK": "BLOCK_RESTORE",
}

VERIFICATION_FOR_ACTION = {
    rules.DELETE: "VERIFY_RECORD_ABSENT",
    rules.REDACT: "VERIFY_RECORD_REDACTED",
    rules.ANONYMIZE: "VERIFY_RECORD_ANONYMIZED",
    rules.RETAIN: "VERIFY_RECORD_PRESENT",
    rules.DISABLE_FLOW: "VERIFY_DATA_FLOW_DISABLED",
    rules.BLOCK_RESTORE: "VERIFY_RESTORE_BLOCKED",
}


@dataclass
class Step:
    phase: str
    system_id: str
    resource_id: str
    operation: str
    evidence_id: str
    action: str = ""

    def as_dict(self, number: int) -> Dict:
        return {
            "step_no": number,
            "phase": self.phase,
            "system_id": self.system_id,
            "resource_id": self.resource_id,
            "operation": self.operation,
            "state": OPERATION_STATE[self.operation],
            "evidence_id": self.evidence_id,
        }


def sort_steps(steps: List[Step]) -> List[Step]:
    return sorted(
        steps,
        key=lambda step: (
            PHASE_ORDER[step.phase],
            OPERATION_ORDER.get(step.operation, 99),
            step.system_id,
            step.resource_id,
        ),
    )


def serialise(steps: List[Step]) -> List[Dict]:
    return [step.as_dict(index + 1) for index, step in enumerate(sort_steps(steps))]
def probe_file(catalog: Catalog, system: str, audit_at) -> str:
    """Most recent evidence file that probed this system at or before audit_at.

    Recency wins here: to prove absence at `audit_at` the strongest citation is the
    latest capture that looked and did not find the record.
    """
    candidates = [item for item in catalog.observations
                  if item.system == system and item.observed_at <= audit_at]
    if not candidates:
        return ""
    best = max(candidates,
               key=lambda item: (item.observed_at, catalog.weight(item.file_id),
                                 item.file_id))
    return best.file_id


def _finding_operation(item: PolicyItem) -> Optional[str]:
    state = item.state
    if item.action == rules.DELETE:
        if state.present:
            return "REPORT_REMAINING_RECORD"
        return None
    if item.action in (rules.REDACT, rules.ANONYMIZE):
        if state.present and state.exposed:
            return "REPORT_EXPOSED_PII"
        return None
    if item.action == rules.DISABLE_FLOW:
        return "REPORT_ACTIVE_DATA_FLOW" if rules.flow_active(item) else None
    if item.action == rules.BLOCK_RESTORE:
        return "REPORT_RESTORE_RISK" if rules.restore_open(item) else None
    return None


def build_findings(items: List[PolicyItem], account_id: str) -> List[Step]:
    steps: List[Step] = []
    for item in items:
        operation = _finding_operation(item)
        if operation is None:
            continue
        evidence = item.state.evidence_id
        if not evidence:
            continue
        steps.append(
            Step(
                phase="FINDING",
                system_id=item.system,
                resource_id=item.resource_id,
                operation=operation,
                evidence_id=evidence,
                action=item.action,
            )
        )
    return steps


def remediation_operation(finding: Step) -> Optional[str]:
    """A remaining record must be deleted; exposed PII follows the policy action."""
    if finding.operation == "REPORT_REMAINING_RECORD":
        return "DELETE_RECORD"
    if finding.operation == "REPORT_EXPOSED_PII":
        if finding.action == rules.ANONYMIZE:
            return "ANONYMIZE_RECORD"
        return "REDACT_RECORD"
    return REMEDIATION_FOR.get(finding.operation)


def build_remediation(findings: List[Step]) -> List[Step]:
    steps: List[Step] = []
    for finding in findings:
        operation = remediation_operation(finding)
        if operation is None:
            continue
        steps.append(
            Step(
                phase="REMEDIATION",
                system_id=finding.system_id,
                resource_id=finding.resource_id,
                operation=operation,
                evidence_id="",
            )
        )
    return steps


def build_verification(items: List[PolicyItem], findings: List[Step],
                       catalog: Catalog, audit_at, complete: bool) -> List[Step]:
    steps: List[Step] = []
    seen = set()
    finding_ops = {finding.resource_id: finding.operation for finding in findings}
    for item in items:
        operation = VERIFICATION_FOR_ACTION.get(item.action)
        if operation is None:
            continue
        state = item.state
        if complete:
            if state.source != "evidence" and not state.present:
                if item.action != rules.DELETE:
                    continue
                evidence = probe_file(catalog, item.system, audit_at)
            else:
                if state.source != "evidence":
                    continue
                if item.action == rules.DELETE and state.present:
                    continue
                if item.action in (rules.REDACT, rules.ANONYMIZE) and state.exposed:
                    continue
                if item.action == rules.RETAIN and not state.present:
                    continue
                if item.action == rules.DISABLE_FLOW and rules.flow_active(item):
                    continue
                if item.action == rules.BLOCK_RESTORE and rules.restore_open(item):
                    continue
                evidence = state.evidence_id
        else:
            evidence = ""
            # A remediation we planned changes the check that must pass.
            finding_op = finding_ops.get(item.resource_id)
            if finding_op == "REPORT_REMAINING_RECORD":
                operation = "VERIFY_RECORD_ABSENT"
            elif finding_op == "REPORT_EXPOSED_PII":
                operation = ("VERIFY_RECORD_ANONYMIZED"
                             if item.action == rules.ANONYMIZE
                             else "VERIFY_RECORD_REDACTED")
        key = (operation, item.system, item.resource_id)
        if key in seen:
            continue
        seen.add(key)
        steps.append(
            Step(
                phase="VERIFICATION",
                system_id=item.system,
                resource_id=item.resource_id,
                operation=operation,
                evidence_id=evidence,
            )
        )
    return steps
