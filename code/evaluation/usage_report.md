# Usage report — final full-dataset run

This report describes **only** the run that produced the submitted `output.csv`:

```powershell
python code/main.py --out output.csv     # 518 cases
```

## 1. Configuration of that run

| Item | Value |
|---|---|
| Provider configured | `anthropic` (from `.env`) |
| Model configured | `claude-sonnet-4-5` (from `AUDIT_MODEL`) |
| Provider reachable | no — the key was rejected with HTTP 401 |
| Model calls completed | **0** |
| Behaviour | after 3 consecutive failures the client disabled model calls for the run and every classification used the deterministic matcher |

## 2. Totals for the final run

| Item | Value |
|---|---|
| Input tokens | 0 |
| Output tokens | 0 |
| Total tokens | 0 |
| Requests (cases) | 518 |
| Average tokens per request | 0 |
| Estimated total cost | $0.000000 |
| Average cost per request | $0.000000 |

## 3. Per-model and overall totals

| Provider | Model | Calls | Input tokens | Output tokens | Total tokens | Cost (USD) |
|---|---|---|---|---|---|---|
| anthropic | claude-sonnet-4-5 | 0 | 0 | 0 | 0 | 0.000000 |
| **Overall** | — | **0** | **0** | **0** | **0** | **0.000000** |

There is a single provider in this run, so the per-model row and the overall row are
identical.

## 4. Where the numbers come from

`code/audit/llm.py` is the only component that can spend tokens. For each call it
appends one JSON line to `code/evaluation/usage_log.jsonl`:

```json
{"kind": "request", "provider": "anthropic", "model": "claude-sonnet-4-5",
 "input_tokens": 0, "output_tokens": 0, "elapsed_seconds": 0.0}
```

The final run appended **no** lines, because no call completed — consistent with the
`usage:` summary that `python code/main.py` prints:

```json
{"provider": "anthropic", "model": "claude-sonnet-4-5", "calls": 0,
 "input_tokens": 0, "output_tokens": 0, "estimated_cost_usd": 0.0,
 "price_known": true, "disabled": true}
```

The usage log and the answer cache on disk also contain **375 entries from earlier
development runs** made while a working key was available. Those calls are not part
of the submitted run and are excluded from every figure above, and are not shipped in
`code.zip`. The cache is a local convenience only: the pipeline recreates it on the
first call after a key is supplied.

## 5. Why the run needed no model

The task allows a model only where code cannot decide. Two places qualified:
classifying `request_text`, and extracting facts from files with no text layer.
Both have deterministic paths (`code/audit/classify.py` keyword stems in ~15
languages; PDF text-layer parsing and deterministic readers for logs/JSON/SQL), and
on the 32 public samples those paths reach the measured accuracy in
`evaluation_report.md`. So the failed key did not block the submission.

## 6. Projection if the model path completes

A projection, not a measurement. The classifier sends one short request per case
(~600 input tokens including the system prompt) and receives one word (~5 output
tokens):

| Model | Calls | Input tokens | Output tokens | Total tokens | Cost (USD) |
|---|---|---|---|---|---|
| claude-haiku-5-5 class rates ($0.10 / $0.50 per 1M) | 518 | ~310,800 | ~2,590 | ~313,390 | ~$0.032 |
| claude-sonnet-5-5 class rates ($2.00 / $10.00 per 1M) | 518 | ~310,800 | ~2,590 | ~313,390 | ~$0.648 |

Rates are the published ones in the `PRICES` table in `code/audit/llm.py`, which
`AUDIT_PRICE_INPUT` / `AUDIT_PRICE_OUTPUT` can override. At most ~600 tokens per case,
this is the entire model budget of the pipeline: extraction from evidence files is
deterministic, so no vision or long-context call is involved.

## 7. Reproducing the accounting

```powershell
# what was submitted: deterministic, 0 calls, $0.00
python code/main.py --out output.csv

# with a working key: every call is logged and cached
$env:ANTHROPIC_API_KEY = "<key>"      # or OPENAI_API_KEY with AUDIT_LLM_PROVIDER=openai
python code/main.py --out output.csv

# force the offline path regardless of what is configured
$env:AUDIT_LLM_PROVIDER = "none"
python code/main.py --out output.csv
```

With a working key the second command appends to
`code/evaluation/usage_log.jsonl`; summing `input_tokens` and `output_tokens` over
its new lines and applying the configured price reproduces the tables above for the
chosen model. A repeat run replays `code/cache/llm_cache.json` and reports 0 new
calls.
