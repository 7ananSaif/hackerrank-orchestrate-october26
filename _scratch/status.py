import csv, os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load(path):
    with open(path, encoding="utf-8-sig", newline="") as handle:
        return {row["case_id"]: row for row in csv.DictReader(handle)}


truth = load(os.path.join(ROOT, "dataset", "sample_output.csv"))
pred = load(os.path.join(ROOT, "code", "evaluation", "sample_predictions.csv"))
bad = [(c, truth[c]["deletion_status"], pred[c]["deletion_status"])
       for c in sorted(truth)
       if truth[c]["deletion_status"] != pred[c]["deletion_status"]]
print(len(bad), "status mismatches")
for item in bad:
    print(" ", item)
