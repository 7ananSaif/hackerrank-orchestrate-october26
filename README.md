# HackerRank Orchestrate - October 2026

## Ghost Data Still Exists

Build an AI agent that audits whether a user's personal data was actually deleted.

A deletion workflow may report **Complete** while data still exists in databases, logs, support attachments, exports, search indexes, archives, or backups. Sync and restore processes may also bring deleted data back.

For each request, the agent must first determine whether deletion was actually requested. It then returns `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`, reports any remaining data or recreation risk, and produces the ordered remediation and verification steps required to finish an authorized deletion safely.

Read [`problem_statement.md`](./problem_statement.md) for the complete challenge contract.

---

## Solution

`code/main.py` is a deterministic deletion-audit agent. It reads `dataset/`, treats
every reported workflow status as a claim, reconstructs the real state of each
resource at `audit_at` from the supplied evidence, and writes `output.csv`.

### Setup

Python 3.10+ on Windows, macOS or Linux. One optional dependency:

```powershell
python -m pip install pdfplumber        # only for the PDF evidence files
```

`pdfplumber` is used when present; without it the PDF reader returns nothing and the
pipeline still runs (the PDFs are the smallest part of the evidence set). Model
access is optional and off by default (see "Model layer" below).

### Run

```powershell
python code/main.py                     # writes ./output.csv for all 518 cases
python code/main.py --samples --out code/evaluation/sample_predictions.csv
python code/evaluation/main.py          # scores the sample predictions
python code/evaluation/validate.py output.csv   # contract checks
python code/evaluation/custom_cases.py          # 4 custom decision cases
```

`python code/main.py` needs no arguments, no key and no network.

### Architecture

```
code/
  main.py                entry point: one row per case, sorted by case_id
  audit/
    loaders.py           CSV loading, timestamp parsing, Dataset/Case records
    identity.py          current + historical identifiers for each request
    catalog.py           in-memory index of every evidence observation
    evidence/            one parser per evidence family
      sql_snapshots.py   SQLite execution of each .sql capture (primary and replicas)
      json_records.py    snapshot bundles, service exports, connector/export probes
      logs.py            key=value probes and pipe-delimited handover sheets
      documents.py       PDF text-layer extraction (retention registers, attachments)
      images.py          image evidence manifest and captions
    state.py             per-resource state at audit_at, attribute to subject
    rules.py             applies deletion_rules.csv to each resolved state
    steps.py             finding/remediation/verification emission and ordering
    classify.py          is this request a deletion request?
    llm.py               optional cached model client with token accounting
  evaluation/
    main.py              accuracy scoring against sample_output.csv
    validate.py          submission contract validator
    custom_cases.py      four hand-built decision cases
    evaluation_report.md results, custom cases, failures, improvements
    usage_report.md      provider/model/token/cost accounting for the final run
```

The separation matters more than the file count: **evidence parsing** knows nothing
about policy, **rules** know nothing about evidence formats, and **steps** know
nothing about either. Adding a new evidence family means adding one parser; adding
a data category means adding one row to `deletion_rules.csv`.

### How a case is decided

1. **Classify the request.** `classify.py` looks for deletion stems in ~15
   languages (`delet`, `eras`, `remov`, `supprim`, `elimin`, `exclus`, `削除`, …)
   and for maintenance/access wording that explicitly asks to keep the account
   ("leave the account active", "continue using the service", "portable format").
   Only the second family produces `NOT_APPLICABLE`, with `steps_json = []`.
2. **Resolve identity.** `user_identities.csv` gives the current email, phone,
   `email_hash` and `user_id`; `user_audit_log.csv` gives every historical value, so
   a record keyed on the address the person *used to have* is still attributed to
   them.
3. **Parse every evidence file** into `Observation` records: system, resource,
   collection, capture time, identifiers found, PII fields exposed, attributes
   (`enabled`, `restore_allowed`, `archive_present`, `account_status`, …). SQL
   captures are executed with `sqlite3`, so primary, regional, reporting and
   failover replicas are all read and drift is visible.
4. **Attribute by identifier, not by time.** A resource joins the case only if an
   observation carries one of the subject's identifiers, plus the single account
   record the workflow targeted. This is what keeps neighbouring customers' records
   (and the decoys placed in the same capture) out of the answer.
5. **Apply policy.** `deletion_rules.csv` maps each data category to `DELETE`,
   `REDACT`, `ANONYMIZE`, `RETAIN`, `BLOCK_RESTORE` or `DISABLE_FLOW`. A tombstone
   may keep `user_id` but must lose name, email, phone and hash. Records the policy
   retains (security audit, legal hold) are verified **present**, not deleted.
6. **Emit steps** in the required order: `FINDING` (with an evidence id) →
   `REMEDIATION` (empty evidence id) → `VERIFICATION` (empty for future checks,
   evidence-bearing for `COMPLETE` proofs). Within a phase, operation order, then
   `system_id`, then `resource_id`.

`COMPLETE` is only emitted when no finding survives, which means every
delete-required record was proven absent and every retained record proven present.

### Model layer

The model is optional and used only where code is weakest: classifying
`request_text`, and reading evidence with no text layer. Nothing else calls it.

```powershell
$env:AUDIT_LLM_PROVIDER = "none"          # force the offline, fully deterministic path
$env:ANTHROPIC_API_KEY  = "<key>"         # or OPENAI_API_KEY with provider "openai"
$env:AUDIT_MODEL        = "claude-sonnet-4-5"   # optional; provider default otherwise
```

A `.env` file in the repo root is read as a convenience and never overrides a
variable already set in the real environment. Calls are cached on disk in
`code/cache/llm_cache.json` (keyed by `sha256(kind | model | prompt)`), so re-runs cost
nothing, and each successful call appends one line to
`code/evaluation/usage_log.jsonl` with provider, model and token counts. After three
consecutive provider failures the client disables model calls for the run, warns once
and falls back — which is exactly what happened for the submitted `output.csv`: the
configured key was rejected, so every case was decided deterministically at zero cost.
See `code/evaluation/usage_report.md` for the full accounting.

### Reproducing output.csv

```powershell
python code/main.py --out output.csv
python code/evaluation/validate.py output.csv
```

The run is deterministic: the same dataset produces a byte-identical `output.csv`.
The validator checks the header, the 518 sorted rows, JSON validity, consecutive
`step_no`, allowed phase/operation/state triples, ordering, the evidence-id rules per
status, and that every cited id exists in `evidence_files.csv`,
`system_activity.csv` or `user_audit_log.csv`.

Measured on the 32 public samples: case-level status accuracy **0.875** (28/32), row
and sequence accuracy **0.250**, step-level accuracy **0.767**, field accuracy
**0.764**; all four custom cases pass. On the full set the submission is 296
INCOMPLETE, 212 COMPLETE and 10 NOT_APPLICABLE over 2282 steps, and the validator
accepts every constraint. Details, the four remaining known failures and what I would
fix next are in `code/evaluation/evaluation_report.md`.

---

## Quick Start

Clone the repository and move into the project directory:

```bash
git clone https://github.com/interviewstreet/hackerrank-orchestrate-october26.git
cd hackerrank-orchestrate-october26
```

Start your AI coding tool from the **repository root** so it automatically reads [`AGENTS.md`](./AGENTS.md) and logs your session turns to `log.txt` in the root directory.

Build your solution in `code/main.py`, or use another language and document its setup and run command clearly in your README.

Your solution must:

- Read the input files from `dataset/`
- Generate one prediction row for every request in `dataset/deletion_requests.csv`
- Write the final predictions to `output.csv` in the repository root

Run the starter Python entry point with:

```bash
python3 code/main.py
```

The blank template at `dataset/output.csv` is provided as a reference. Your final generated file for submission must be the root-level `output.csv`.


## Dataset

All participant-facing files are in `dataset/`:

| File | Contents |
| --- | --- |
| `deletion_requests.csv` | 518 requests |
| `sample_deletion_requests.csv` | 32 sample requests |
| `sample_output.csv` | Correct sample answers |
| `user_identities.csv` | Current user identities |
| `user_audit_log.csv` | Historical identity changes |
| `system_activity.csv` | Activity across services and data processes |
| `deletion_rules.csv` | Required treatment for each data category |
| `evidence_files.csv` | Manifest of supplied evidence files |
| `output.csv` | Blank output template |

Evidence is stored under `dataset/evidence/` and may include PDFs, images, logs, JSON, plain text, or SQL snapshot exports. SQL captures may contain a primary database, regional replicas, a reporting replica, or a failover replica so replication drift can be investigated directly. The `.sql` files are readable as text and executable with SQLite.

Only `deletion_requests.csv` requires answers. The other files provide evidence and context.

---

## Output

Create `output.csv` with these columns in this exact order:

```text
case_id,deletion_status,steps_json
```

Produce exactly one row per request. `deletion_status` is `COMPLETE`, `INCOMPLETE`, or `NOT_APPLICABLE`. `steps_json` is an ordered JSON array containing findings, remediation actions, and verification checks. Use an empty array (`[]`) for `NOT_APPLICABLE`. Evidence references may be a `file_id`, `activity_id`, or `audit_id`. Determine the resource state at `audit_at` from the available evidence; reported workflow statuses and operation results are claims. Use `dataset/sample_output.csv` as the format reference.

The final file must contain 518 data rows sorted by `case_id` (plus the header row). The grader parses `steps_json` as JSON, so object-key order and whitespace do not matter; array order does. Order findings, remediation, and verification in that phase order. Within a phase, follow the operation order in the problem statement, then sort by `system_id` and `resource_id`.

---

## Evaluation

`output.csv` will be compared with hidden canonical answers. Scoring considers:

- deletion assessment accuracy;
- current and historical identity resolution;
- discovery of remaining data and recreation risks;
- correct policy application and evidence references; and
- completeness and ordering of remediation and verification steps.

Your `code.zip` must include:

```text
code/evaluation/evaluation_report.md
code/evaluation/usage_report.md
```

- `evaluation_report.md` must cover case, row, field, and sequence accuracy, at least three additional evaluation cases created by you, failures found, and improvements made.
- `usage_report.md` must cover the final full-dataset run, including model providers and names, model calls, input and output tokens, total and average tokens per request, and estimated total and per-request cost. Include per-model and overall totals when using multiple models.

**Important:** Place `evaluation_report.md` and `usage_report.md` inside `code/evaluation/` (matching `code/evaluation/main.py` in this starter layout), write your complete evaluation metrics, custom evaluation test cases, and token/cost breakdowns directly inside those Markdown files, and keep prompts in source code or Markdown files. Automated code evaluation ignores raw data files (`.csv`, `.tsv`, `.json`, `.jsonl`, `.sql`, `.log`), so content stored only in those formats will not be visible to the code judge or AI interviewer.

---

## Chat Transcript

This repository includes [`AGENTS.md`](./AGENTS.md), which instructs compatible AI coding tools to append conversation summaries to `log.txt` in the repository root:

| Platform | Path |
| --- | --- |
| macOS / Linux | `<repo root>/log.txt` |
| Windows | `<repo root>\log.txt` |

- Always launch your AI coding agent from the repository root (or explicitly ask it to read `./AGENTS.md` first) so every turn is logged to `log.txt` with the required `User Prompt`, `Agent Response Summary`, `Actions`, and `Context` sections.
- Upload `log.txt` directly as your `chat_transcript` submission on HackerRank.
- Do not include API keys, tokens, credentials, or secrets in prompts, code, configuration, or `log.txt`.

---

## Packaging `code.zip` and Submission

| Item | Description |
| --- | --- |
| `code.zip` | Runnable solution, prompts, configuration, `README.md`, and `evaluation/` reports |
| `output.csv` | One answer row for each of the 518 requests in `dataset/deletion_requests.csv` |
| `chat_transcript` | The root `log.txt` file generated by your coding agent |
| AI interview | Live explanation of your architecture, approach, and evaluation |

You may use any programming language, model, framework, or retrieval approach. Include clear setup and execution instructions in `README.md` inside `code.zip`.

To package `code.zip` from the repository root without bundling the dataset:

**macOS / Linux:**

```bash
zip -r code.zip README.md code -x "*/__pycache__/*" "*/.venv/*" "*/venv/*" "*/node_modules/*" "*/.git/*" "*/.DS_Store"
```

**Windows (PowerShell):**

```powershell
Compress-Archive -Path README.md, code -DestinationPath code.zip -Force
```

When packaging `code.zip`:

- Keep your evaluation reports in `code/evaluation/` so they are bundled automatically with `code` (or add `evaluation` to the archive command above if you placed them in a top-level `evaluation/` directory).
- Do **not** include `dataset/`, virtual environments (`.venv`, `venv`, `node_modules`), or build caches (`__pycache__`). On Windows, keep `.venv` at the repository root (outside `code/`) and remove any `code/__pycache__` folders before running `Compress-Archive`.
- Do **not** include nested archives (`.zip`, `.tar`, `.gz`, `.tgz`, `.7z`, `.rar`) inside `code.zip` — submissions containing nested archive files will be rejected.

Before submitting, confirm that:

- `output.csv` has the exact header `case_id,deletion_status,steps_json` and contains all 518 data rows sorted by `case_id`;
- every `steps_json` value is a valid JSON array with consecutive step numbers starting at `1`;
- findings cite valid evidence IDs, and `COMPLETE` verification steps cite evidence proving the current state;
- proposed remediation and future verification steps use an empty `evidence_id` (`""`);
- `code.zip` includes your runnable code, `README.md`, `code/evaluation/evaluation_report.md`, and `code/evaluation/usage_report.md`;
- `log.txt` follows the `AGENTS.md` turn format and is uploaded to the `chat_transcript` slot; and
- no API keys, credentials, real personal data, or sensitive configuration values are included.
