# Evaluation report — Ghost Data Still Exists

Every number below comes from the frozen pipeline:

```powershell
python code/main.py --samples --out code/evaluation/sample_predictions.csv
python code/evaluation/main.py code/evaluation/sample_predictions.csv
python code/evaluation/custom_cases.py
python code/main.py --out output.csv
python code/evaluation/validate.py output.csv
```

## 1. Headline results on the 32 public samples

| Metric | Value | Count |
|---|---|---|
| Case-level status accuracy | **0.875** | 28 / 32 |
| Row accuracy (same step set, any order) | **0.250** | 8 / 32 |
| Sequence accuracy (same steps, same order) | **0.250** | 8 / 32 |
| Step-level accuracy (matched `phase+operation+system+resource`) | **0.767** | 148 / 193 |
| Field-level accuracy over expected steps | **0.764** | 885 / 1158 |

Field breakdown over the 193 expected steps:

| Field | Hits / expected |
|---|---|
| phase | 148 / 193 |
| operation | 148 / 193 |
| system_id | 148 / 193 |
| resource_id | 148 / 193 |
| state | 148 / 193 |
| evidence_id | 145 / 193 |

The five structural fields are identical because a step counts once its
`phase+operation+system+resource` key matches. Reading both rows together: when the
pipeline finds the right record it almost always produces the right operation, state
and citation (145 of 148). The remaining error mass is **which records exist**
(4 status + 45 step misses), not how they are described or ordered.

## 2. Validation of the submitted file

`python code/evaluation/validate.py output.csv` → **OK: every contract check passed**

| Check | Result |
|---|---|
| Header exactly `case_id,deletion_status,steps_json` | pass |
| 518 data rows | pass (518) |
| Sorted by `case_id`, ids match `deletion_requests.csv` | pass |
| Every `steps_json` parses as a JSON array | pass (2282 steps) |
| `step_no` consecutive from 1 | pass |
| Allowed phase/operation/state combinations | pass |
| Phase order FINDING → REMEDIATION → VERIFICATION, then operation, then system, then resource | pass |
| `NOT_APPLICABLE` rows have `steps_json = []` | pass (10 cases) |
| `COMPLETE` steps are VERIFICATION only and cite evidence | pass (212 cases) |
| FINDING steps cite an existing `file_id` / `activity_id` / `audit_id` | pass |
| REMEDIATION and future VERIFICATION steps carry `evidence_id == ""` | pass |

Status distribution over the 518 cases: INCOMPLETE 296, COMPLETE 212,
NOT_APPLICABLE 10.

## 3. Custom cases (beyond the public samples)

`python code/evaluation/custom_cases.py` → **4/4 passed**.

1. **`history_email_still_indexed`** — a search document still carrying the address
   the subject used *before* renaming. Historical identifier resolution attributes it
   to the subject, so it is reported as `REPORT_REMAINING_RECORD` instead of missed.
2. **`tombstone_redacted_not_deleted`** — an account tombstone holding name, email,
   phone and hash. Expected `REPORT_EXPOSED_PII` → `REDACT_RECORD` →
   `VERIFY_RECORD_REDACTED`; the stable `user_id` survives, the direct identifiers do
   not, and the tombstone is never deleted.
3. **`backup_restore_risk_real`** — a backup whose `restore_allowed` is true. Exactly
   `REPORT_RESTORE_RISK`, `BLOCK_RESTORE`, `VERIFY_RESTORE_BLOCKED`: recovery risk is a
   live defect, not a note.
4. **`maintenance_request_not_applicable`** — "change the email address … I want to
   continue using the service". Expected `NOT_APPLICABLE` with no steps; this guards
   the failure mode where an eager classifier destroys data for a correction request.

## 4. Failures found and what was fixed

Each fix came from diffing a real mismatch; none special-cases a `case_id`.

| Symptom | Root cause | Fix |
|---|---|---|
| Almost every request classified as non-deletion | keywords were whole words, so `deleting`/`deleted` never matched `delete` | language stems (`delet`, `eras`, `remov`, `supprim`, `elimin`, `exclus`, …) |
| Zero `NOT_APPLICABLE` across 518 cases | maintenance wording ("keep the account", "portable format") was not recognised | explicit keep-the-account phrase family; the default is now "deletion authorised" because blocking a real request leaves data in place |
| Other customers' records appeared in a case | any resource in the activity window was adopted | attribution requires an observation carrying one of the subject's own current or historical identifiers |
| Handover sheets and replica probes produced nothing | two evidence formats were never parsed | pipe-delimited `ts \| system \| resource \| category \| state \| subject` parser plus `match_key` / `matched_value` / `correlation_key` support |
| Support records deleted when they should be redacted, and vice versa | one category for all support data | the record's own category drives it: `SUPPORT_ATTACHMENT` → delete, `SUPPORT_MESSAGE` → redact, replica contact rows → delete; a conversation with no identifier left verifies as already redacted |
| Analytics records remediated with `REDACT_RECORD` | remediation ignored the policy action | remediation follows the action (`ANONYMIZE_RECORD` for analytics) and each `VERIFY_*` follows the remediation actually planned |
| Wrong account id in many cases | anchor chosen by "closest to `reported_at`" across all customers | candidates restricted to accounts listed in the evidence files that already name the subject |
| Backup/search records missing from findings | evidence files whose table names were unseen were skipped | table/collection → system inference by prefix |
| A submitted delete kept the case open | absence required a `SUCCESS` result | with no contradicting evidence a submitted delete counts as effective; only evidence may show a surviving record |
| Citations pointed at bulk bundles instead of the probe that proved the fact | "newest file that mentions the system" | `preference.py` ranks evidence by origin (readback log / service export > system capture > bundle) then recency; this moved evidence accuracy from 109/193 to 145/193 |

## 5. Remaining known failures (honest list)

Four of the 32 samples still get the status wrong, all in the same direction — a real
violation is not found, so the case is called COMPLETE:

| Case | Expected | Predicted | Why |
|---|---|---|---|
| case_10 | INCOMPLETE | COMPLETE | the support replica row is found but carries no PII field, so no finding fires |
| case_12 | INCOMPLETE | COMPLETE | the analytics row is identified only by a salted `correlation_key`, which cannot be tied to the subject |
| case_15 | INCOMPLETE | COMPLETE | the active connector for this case never names the subject |
| case_17 | INCOMPLETE | COMPLETE | the backup listing for this case carries no identifier to match |

These are one trade-off, not four bugs: strict identifier matching (precision) versus
recall on records whose probe line carries only a hash or nothing at all. The build
chooses precision, because a false INCOMPLETE invents remediation work that does not
exist, while a missed finding is at least consistent. Row accuracy (0.250) is bounded
by the same thing plus record selection inside a capture: one extra or one missing
record changes the step set even when every operation is right.

## 6. What I would do next

1. **Attribute hashed probes.** `correlation_key` looks like a salted email hash;
   recovering the salt per capture would turn the case_12 class of failures into
   findings without weakening precision.
2. **Assign records inside a capture.** Several captures are generated per case family;
   assigning resources by the generator's ordering would fix most remaining
   `resource_id` mismatches and lift row accuracy.
3. **Tie-break citations on the delete attempt.** Prefer the capture that holds the
   subject's own delete attempt over any later capture that merely mentions the system.
4. **Let the model resolve the residue only.** The keyed path is wired and cached; with
   a working key the four ambiguous classifications above are exactly the cases worth
   spending a call on.
