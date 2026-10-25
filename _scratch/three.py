import csv
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


truth = load(os.path.join(ROOT, "dataset", "sample_output.csv"))
pred = load(os.path.join(ROOT, "code", "evaluation", "sample_predictions.csv"))

for case in ("case_26", "case_27", "case_28"):
    t = json.loads(truth[case]["steps_json"])
    p = json.loads(pred[case]["steps_json"])
    tk = {(s["operation"], s["resource_id"]) for s in t}
    pk = {(s["operation"], s["resource_id"]) for s in p}
    print(case)
    print("  extra  :", sorted(pk - tk))
    print("  missing:", sorted(tk - pk))
