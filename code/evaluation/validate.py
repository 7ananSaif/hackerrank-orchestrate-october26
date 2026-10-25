"""Validate output.csv against the submission contract."""

from __future__ import annotations

import csv
import json
import os
import sys
from typing import Dict, List, Set, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

PHASE_ORDER = {"FINDING": 0, "REMEDIATION": 1, "VERIFICATION": 2}
OPERATION_ORDER = {
    "REPORT_REMAINING_RECORD": 0, "REPORT_EXPOSED_PII": 1,
    "REPORT_ACTIVE_DATA_FLOW": 2, "REPORT_RESTORE_RISK": 3,
    "DISABLE_DATA_FLOW": 0, "BLOCK_RESTORE": 1, "DELETE_RECORD": 2,
    "REDACT_RECORD": 3, "ANONYMIZE_RECORD": 4,
    "VERIFY_RECORD_ABSENT": 0, "VERIFY_RECORD_PRESENT": 1,
    "VERIFY_RECORD_REDACTED": 2, "VERIFY_RECORD_ANONYMIZED": 3,
    "VERIFY_DATA_FLOW_DISABLED": 4, "VERIFY_RESTORE_BLOCKED": 5,
}
ALLOWED = {
    "REPORT_REMAINING_RECORD": ("FINDING", "PRESENT"),
    "REPORT_EXPOSED_PII": ("FINDING", "PRESENT"),
    "REPORT_ACTIVE_DATA_FLOW": ("FINDING", "ACTIVE"),
    "REPORT_RESTORE_RISK": ("FINDING", "ACTIVE"),
    "DISABLE_DATA_FLOW": ("REMEDIATION", "DISABLED"),
    "BLOCK_RESTORE": ("REMEDIATION", "BLOCKED"),
    "DELETE_RECORD": ("REMEDIATION", "ABSENT"),
    "REDACT_RECORD": ("REMEDIATION", "REDACTED"),
    "ANONYMIZE_RECORD": ("REMEDIATION", "ANONYMIZED"),
    "VERIFY_RECORD_ABSENT": ("VERIFICATION", "ABSENT"),
    "VERIFY_RECORD_PRESENT": ("VERIFICATION", "PRESENT"),
    "VERIFY_RECORD_REDACTED": ("VERIFICATION", "REDACTED"),
    "VERIFY_RECORD_ANONYMIZED": ("VERIFICATION", "ANONYMIZED"),
    "VERIFY_DATA_FLOW_DISABLED": ("VERIFICATION", "DISABLED"),
    "VERIFY_RESTORE_BLOCKED": ("VERIFICATION", "BLOCKED"),
}
STEP_FIELDS = {"step_no", "phase", "system_id", "resource_id", "operation", "state",
               "evidence_id"}


def known_evidence_ids() -> Set[str]:
    ids: Set[str] = set()
    with open(os.path.join(ROOT, "dataset", "evidence_files.csv"), encoding="utf-8-sig",
              newline="") as handle:
        for row in csv.DictReader(handle):
            ids.add(row["file_id"])
    with open(os.path.join(ROOT, "dataset", "system_activity.csv"), encoding="utf-8-sig",
              newline="") as handle:
        for row in csv.DictReader(handle):
            ids.add(row["activity_id"])
    with open(os.path.join(ROOT, "dataset", "user_audit_log.csv"), encoding="utf-8-sig",
              newline="") as handle:
        for row in csv.DictReader(handle):
            ids.add(row["audit_id"])
    return ids


def expected_case_ids() -> List[str]:
    with open(os.path.join(ROOT, "dataset", "deletion_requests.csv"),
              encoding="utf-8-sig", newline="") as handle:
        return sorted(row["case_id"] for row in csv.DictReader(handle))
def validate(path: str) -> Tuple[List[str], Dict[str, object]]:
    """Return (errors, summary). An empty error list means the file is valid."""
    errors: List[str] = []
    known = known_evidence_ids()
    expected = expected_case_ids()
    summary: Dict[str, object] = {"rows": 0, "steps": 0, "statuses": {}}

    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        if reader.fieldnames != ["case_id", "deletion_status", "steps_json"]:
            errors.append(f"header mismatch: {reader.fieldnames}")
        rows = list(reader)

    summary["rows"] = len(rows)
    if len(rows) != 518:
        errors.append(f"expected 518 data rows, found {len(rows)}")

    case_ids = [row["case_id"] for row in rows]
    if case_ids != sorted(case_ids):
        errors.append("rows are not sorted by case_id")
    if case_ids != expected:
        missing = set(expected) - set(case_ids)
        extra = set(case_ids) - set(expected)
        if missing:
            errors.append(f"missing case_ids: {sorted(missing)[:5]}")
        if extra:
            errors.append(f"unknown case_ids: {sorted(extra)[:5]}")

    statuses: Dict[str, int] = {}
    total_steps = 0
    for row in rows:
        case_id = row["case_id"]
        status = row["deletion_status"]
        statuses[status] = statuses.get(status, 0) + 1
        if status not in ("COMPLETE", "INCOMPLETE", "NOT_APPLICABLE"):
            errors.append(f"{case_id}: bad status {status}")
        try:
            steps = json.loads(row["steps_json"])
        except json.JSONDecodeError as exc:
            errors.append(f"{case_id}: invalid JSON ({exc})")
            continue
        if not isinstance(steps, list):
            errors.append(f"{case_id}: steps_json is not an array")
            continue
        total_steps += len(steps)
        if status == "NOT_APPLICABLE" and steps:
            errors.append(f"{case_id}: NOT_APPLICABLE must have no steps")
        if status == "COMPLETE":
            for step in steps:
                if step.get("phase") != "VERIFICATION":
                    errors.append(f"{case_id}: COMPLETE has non-verification step")
                if not step.get("evidence_id"):
                    errors.append(f"{case_id}: COMPLETE step without evidence")
        errors.extend(_check_steps(case_id, status, steps, known))
    summary["steps"] = total_steps
    summary["statuses"] = statuses
    return errors, summary


def _check_steps(case_id: str, status: str, steps: List[dict], known: Set[str]
                 ) -> List[str]:
    errors: List[str] = []
    previous = None
    for index, step in enumerate(steps, start=1):
        if set(step) != STEP_FIELDS:
            errors.append(f"{case_id} step {index}: wrong fields {sorted(step)}")
            continue
        if step["step_no"] != index:
            errors.append(f"{case_id} step {index}: step_no {step['step_no']}")
        operation = step["operation"]
        if operation not in ALLOWED:
            errors.append(f"{case_id} step {index}: unknown operation {operation}")
            continue
        phase, expected_state = ALLOWED[operation]
        if step["phase"] != phase or step["state"] != expected_state:
            errors.append(f"{case_id} step {index}: phase/state for {operation}")
        current = (PHASE_ORDER[phase], OPERATION_ORDER[operation], step["system_id"],
                   step["resource_id"])
        if previous is not None and current < previous:
            errors.append(f"{case_id} step {index}: out of order")
        previous = current
        evidence = step["evidence_id"]
        finding_or_complete = phase == "FINDING" or (
            phase == "VERIFICATION" and status == "COMPLETE")
        if finding_or_complete and not evidence:
            errors.append(f"{case_id} step {index}: missing evidence id")
        if not finding_or_complete and evidence:
            errors.append(f"{case_id} step {index}: expected empty evidence id")
        if evidence and evidence not in known:
            errors.append(f"{case_id} step {index}: unknown evidence {evidence}")
    return errors


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    path = argv[0] if argv else os.path.join(ROOT, "output.csv")
    errors, summary = validate(path)
    print(f"file    {path}")
    print(f"rows    {summary['rows']}")
    print(f"steps   {summary['steps']}")
    print(f"status  {summary['statuses']}")
    if errors:
        print(f"FAILED with {len(errors)} problems:")
        for problem in errors[:40]:
            print("  -", problem)
        return 1
    print("OK: every contract check passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
