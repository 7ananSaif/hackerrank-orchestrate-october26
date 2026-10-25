import csv, os, sys

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from code.audit.classify import DELETION_PHRASES, NON_DELETION_PHRASES, heuristic

rows = list(csv.DictReader(open(os.path.join(ROOT, "dataset", "deletion_requests.csv"),
                                encoding="utf-8-sig")))
no_stem = [r for r in rows if not any(p in r["request_text"].lower()
                                      for p in DELETION_PHRASES)]
print("cases with no deletion stem:", len(no_stem))
for row in no_stem:
    verdict = heuristic(row["request_text"])
    print(f'{row["case_id"]} del={verdict.is_deletion} :: {row["request_text"][:150]}')
