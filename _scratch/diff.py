import csv, json, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


truth = load(os.path.join(ROOT, "dataset", "sample_output.csv"))
pred = load(os.path.join(ROOT, "code", "evaluation", "sample_predictions.csv"))

for case_id in sorted(truth):
    t = json.loads(truth[case_id]["steps_json"])
    p = json.loads(pred[case_id]["steps_json"])
    if truth[case_id]["deletion_status"] == pred[case_id]["deletion_status"] and \
            [(s["operation"], s["resource_id"], s["evidence_id"]) for s in t] == \
            [(s["operation"], s["resource_id"], s["evidence_id"]) for s in p]:
        continue
    print(f'{case_id} {truth[case_id]["deletion_status"]}->{pred[case_id]["deletion_status"]}')
    print("  T", " | ".join(f'{s["operation"][:14]}/{s["resource_id"]}/{s["evidence_id"][-2:]}' for s in t))
    print("  P", " | ".join(f'{s["operation"][:14]}/{s["resource_id"]}/{s["evidence_id"][-2:]}' for s in p))
