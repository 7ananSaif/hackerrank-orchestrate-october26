"""Score predictions against dataset/sample_output.csv."""

from __future__ import annotations

import csv
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Dict, List, Tuple

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def load_rows(path: str) -> Dict[str, dict]:
    with open(path, encoding="utf-8-sig", newline="") as handle:
        rows = {}
        for row in csv.DictReader(handle):
            steps = json.loads(row["steps_json"])
            rows[row["case_id"]] = {"status": row["deletion_status"], "steps": steps}
        return rows


def step_key(step: dict) -> Tuple:
    return (step.get("phase"), step.get("operation"), step.get("system_id"),
            step.get("resource_id"))


def score(expected: Dict[str, dict], actual: Dict[str, dict]) -> Dict[str, object]:
    status_ok = 0
    row_ok = 0
    sequence_ok = 0
    field_hits = 0
    field_total = 0
    step_hits = 0
    step_total = 0
    field_acc: Dict[str, List[int]] = defaultdict(lambda: [0, 0])
    per_case: List[dict] = []

    for case_id, truth in expected.items():
        pred = actual.get(case_id, {"status": None, "steps": []})
        if pred["status"] == truth["status"]:
            status_ok += 1
        truth_keys = [step_key(step) for step in truth["steps"]]
        pred_keys = [step_key(step) for step in pred["steps"]]
        if sorted(truth_keys) == sorted(pred_keys):
            row_ok += 1
        if truth_keys == pred_keys:
            sequence_ok += 1
        step_total += len(truth_keys)
        step_hits += sum((Counter(truth_keys) & Counter(pred_keys)).values())

        truth_by_key = {step_key(step): step for step in truth["steps"]}
        pred_by_key = {step_key(step): step for step in pred["steps"]}
        for key, step in truth_by_key.items():
            for field in ("phase", "system_id", "resource_id", "operation", "state",
                          "evidence_id"):
                field_total += 1
                field_acc[field][1] += 1
                other = pred_by_key.get(key)
                if other is not None and other.get(field) == step.get(field):
                    field_hits += 1
                    field_acc[field][0] += 1
        per_case.append(
            {
                "case_id": case_id,
                "status_match": pred["status"] == truth["status"],
                "row_match": sorted(truth_keys) == sorted(pred_keys),
                "sequence_match": truth_keys == pred_keys,
                "truth_status": truth["status"],
                "pred_status": pred["status"],
                "truth_steps": truth["steps"],
                "pred_steps": pred["steps"],
            }
        )

    total = len(expected)
    return {
        "cases": total,
        "status_accuracy": status_ok / total if total else 0.0,
        "row_accuracy": row_ok / total if total else 0.0,
        "sequence_accuracy": sequence_ok / total if total else 0.0,
        "step_precision": step_hits / step_total if step_total else 0.0,
        "step_recall": step_hits / step_total if step_total else 0.0,
        "field_accuracy": field_hits / field_total if field_total else 0.0,
        "field_breakdown": {key: (val[0], val[1]) for key, val in field_acc.items()},
        "per_case": per_case,
    }


def main(argv=None) -> int:
    argv = argv or sys.argv[1:]
    predictions = argv[0] if argv else os.path.join(
        ROOT, "code", "evaluation", "sample_predictions.csv")
    expected = load_rows(os.path.join(ROOT, "dataset", "sample_output.csv"))
    actual = load_rows(predictions)
    result = score(expected, actual)
    print(f"cases              {result['cases']}")
    print(f"status accuracy    {result['status_accuracy']:.3f}")
    print(f"row accuracy       {result['row_accuracy']:.3f}")
    print(f"sequence accuracy  {result['sequence_accuracy']:.3f}")
    print(f"field accuracy     {result['field_accuracy']:.3f}")
    for field, (hits, total) in sorted(result["field_breakdown"].items()):
        print(f"  {field:<14} {hits}/{total}")
    print()
    for case in result["per_case"]:
        if case["status_match"] and case["sequence_match"]:
            continue
        print(f"--- {case['case_id']} truth={case['truth_status']} "
              f"pred={case['pred_status']}")
        print("  truth:", [(s["operation"], s["system_id"], s["resource_id"],
                           s["evidence_id"]) for s in case["truth_steps"]])
        print("  pred :", [(s["operation"], s["system_id"], s["resource_id"],
                           s["evidence_id"]) for s in case["pred_steps"]])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
