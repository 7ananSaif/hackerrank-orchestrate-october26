"""Entry point: audit every deletion request and write ./output.csv."""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from code.audit import activity, classify, rules, state, steps
from code.audit.catalog import build_catalog
from code.audit.identity import build_subjects
from code.audit.llm import ModelClient
from code.audit.loaders import Case, Dataset, load_dataset

COMPLETE = "COMPLETE"
INCOMPLETE = "INCOMPLETE"
NOT_APPLICABLE = "NOT_APPLICABLE"


def audit_case(dataset: Dataset, catalog, subject, case: Case, client: ModelClient):
    verdict = classify.classify(case.request_text, client)
    if not verdict.is_deletion:
        return NOT_APPLICABLE, []

    # Evidence must name the subject to count. Workflow-only resources are a
    # second pass that measurably hurt precision, so they stay off by default.
    states = state.resolve_states(dataset, catalog, subject, case,
                                  include_workflow=False)
    items = rules.classify_states(states)
    account = state.anchor_account(dataset, case) or ""

    findings = steps.build_findings(items, account)
    is_complete = not findings
    remediation = steps.build_remediation(findings)
    verification = steps.build_verification(items, findings, catalog, case.audit_at,
                                            is_complete)

    if is_complete and not verification and account:
        evidence = steps.probe_file(catalog, "account_service", case.audit_at)
        verification = [
            steps.Step(
                phase="VERIFICATION",
                system_id="account_service",
                resource_id=account,
                operation="VERIFY_RECORD_ABSENT",
                evidence_id=evidence,
            )
        ]

    emitted = steps.serialise(findings + remediation + verification)
    status = COMPLETE if is_complete else INCOMPLETE
    return status, emitted


def run(requests, dataset: Dataset, catalog, client: ModelClient):
    subjects = build_subjects(dataset, requests)
    rows = []
    for case in sorted(requests, key=lambda item: item.case_id):
        subject = subjects[case.case_id]
        status, emitted = audit_case(dataset, catalog, subject, case, client)
        rows.append(
            {
                "case_id": case.case_id,
                "deletion_status": status,
                "steps_json": json.dumps(emitted, ensure_ascii=False),
            }
        )
    return rows


def write_output(rows, path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=["case_id", "deletion_status",
                                                    "steps_json"])
        writer.writeheader()
        for row in rows:
            writer.writerow(row)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Audit deletions and write output.csv")
    parser.add_argument("--samples", action="store_true",
                        help="score the 32 public samples instead of the 518 cases")
    parser.add_argument("--out", default=os.path.join(ROOT, "output.csv"))
    args = parser.parse_args(argv)

    dataset = load_dataset(ROOT)
    client = ModelClient(ROOT)
    catalog = build_catalog(dataset)
    print(f"evidence observations: {len(catalog.observations)}")
    print(f"model provider: {client.provider}")

    requests = dataset.sample_requests if args.samples else dataset.requests
    rows = run(requests, dataset, catalog, client)
    write_output(rows, args.out)
    print(f"wrote {len(rows)} rows to {args.out}")
    summary = client.summary()
    print("usage:", json.dumps(summary))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
