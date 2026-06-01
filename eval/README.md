# Model Evaluation — Complete Runbook

**Deterministic and LLM-based evaluation for the MarTech CDP stack.**

This runbook covers the golden dataset, classification factors (`top_k`, `temperature`, `top_p`), phase 1 (retrieval + guardrails), and phase 2 (autonomous agent). The canonical summary also lives in the root **[README.md → Model evaluation](../README.md#model-evaluation)**.

---

## Why This Eval Framework Exists

The agentic RAG stack makes three decisions on every run: (1) does this user's guardrail state allow outreach, (2) which products does vector retrieval surface, and (3) does the LLM agent respect suppression rules when composing a campaign. Each of these can fail silently — the agent produces a response that looks reasonable but recommends suppressed product types or ignores consent flags.

This framework makes those failures visible and reproducible. Phase 1 evaluates the deterministic layers (guardrails and retrieval) without any LLM cost. Phase 2 evaluates the full agent path with classification factors that let you compare LLM behavior across `temperature`, `top_p`, and `top_k` combinations on a stable golden dataset.

---

## Key Decisions & Trade-offs

| Decision | Why | Trade-off accepted |
|---|---|---|
| **Two-phase structure (deterministic first, LLM second)** | Guardrails and retrieval failures don't need an LLM to detect; phase 1 catches ~80% of issues at zero OpenAI cost | Phase 1 and phase 2 reports must be joined manually on `factor_id` |
| **JSONL golden dataset (not a database)** | Version-controlled, diffable, portable — no additional infra required for the eval layer | Cases must be manually extended; no auto-generation of new scenarios |
| **`factor_id` as the join key across phases** | Allows direct comparison of retrieval behavior vs. agent behavior at identical hyperparameters | `factor_id` string must be stable across refactors; changing format breaks historical joins |
| **`top_k` active in phase 1, temp/top_p recorded only** | Retrieval quality varies with `top_k`; temperature has no effect on deterministic ANN search — recording it aligns reports without pretending it does something it doesn't | Might confuse readers who expect all three factors to be active in phase 1 |
| **`--demo` flag for phase 2 without OpenAI** | Makes CI and local eval possible without billing or quota; deterministic agent path produces comparable structural assertions | `--demo` skips LLM reasoning; genuine policy failures in the LLM path require a full run |
| **Exit code 0 = all assertions passed** | Integrates cleanly into Jenkins/GHA pipelines as a quality gate | Binary pass/fail; partial-pass detail requires reading the JSON report |

---

## Table of Contents

1. [Concepts](#concepts)
2. [Prerequisites — one-time setup](#prerequisites--one-time-setup)
3. [Golden dataset — create and extend](#golden-dataset--create-and-extend)
4. [Classification factors](#classification-factors)
5. [Phase 1 — retrieval + guardrails](#phase-1--retrieval--guardrails)
6. [Phase 2 — LLM agent](#phase-2--llm-agent)
7. [Reports and interpretation](#reports-and-interpretation)
8. [Troubleshooting](#troubleshooting)
9. [Module reference](#module-reference)

---

## Concepts

### Two meanings of "golden"

| Term | What it is | Where |
|------|------------|-------|
| **CDP golden record** | Runtime stitch of profile + behavior for RAG — used live in Tab 8 | `cdp_pipeline.stitch_golden_record()` |
| **Eval golden dataset** | Version-controlled JSONL test cases with expected outcomes — used for regression eval | `eval/golden/*.jsonl` |

These are intentionally separate. CDP golden records are live database reads that change as behavior is logged. Eval golden cases are fixed fixtures that should only change when you deliberately extend the test suite.

### What each phase evaluates

| Layer | Phase | Module | Needs OpenAI |
|-------|-------|--------|-------------|
| Guardrails | 1 | `martech_agent.evaluate_guardrails` | No |
| Vector retrieval | 1 | `martech_agent.search_inventory` | No |
| LLM agent policy | 2 (full) | `martech_agent.execute_autonomous_campaign` | **Yes** |
| Agent (deterministic) | 2 `--demo` | `execute_autonomous_campaign_demo` | No |

### Classification factors

Three hyperparameters treated as **experiment dimensions**. Every result row stores a `factor_id` so runs are comparable:

```
top_k=8|temp=0.1|top_p=0.9
```

| Factor | Phase 1 effect | Phase 2 effect |
|--------|---------------|----------------|
| **`top_k`** | **Active** — controls `semantic_product_search(match_count)` | **Active** — sets `CDP_MATCH_COUNT` env for agent tool calls |
| **`temperature`** | Recorded on report only (retrieval is deterministic) | **Active** — passed to `ChatOpenAI(temperature=...)` |
| **`top_p`** | Recorded on report only | **Active** — passed to `ChatOpenAI(model_kwargs={"top_p": ...})` |

---

## Prerequisites — One-Time Setup

Complete all five steps before running any eval.

### A — CDP Python environment

```powershell
cd c:\Users\agarw\adtech-platform\blank-app
.\scripts\setup-cdp-venv.ps1
.\.venv-cdp\Scripts\Activate.ps1
pip install -r requirements-cdp.txt -r requirements-agent.txt
```

Use **Python 3.11 or 3.12** in `.venv-cdp`. Python 3.14 is not supported for the CDP stack.

### B — Environment variables

Copy `.env.example` → `.env`:

| Variable | Required for | Example |
|----------|-------------|---------|
| `SUPABASE_URL` | Phase 1 & 2 | `https://<ref>.supabase.co` |
| `SUPABASE_KEY` | Phase 1 & 2 | **service_role** secret for local scripts (see note below) |
| `OPENAI_API_KEY` | Phase 2 full LLM only | `sk-...` |
| `OPENAI_MODEL` | Phase 2 (optional) | `gpt-4o-mini` |
| `OPENAI_TEMPERATURE` | Default LLM temperature | `0.1` |
| `EVAL_TOP_K` | Factor sweep via env | `3,5,8` |
| `EVAL_TEMPERATURE` | Factor sweep via env | `0,0.1,0.3` |
| `EVAL_TOP_P` | Factor sweep via env | `0.9,1.0` |

**`SUPABASE_KEY` for local eval:** Use the **service_role** secret from Supabase → Project Settings → API. The migration grants `SELECT` on `consumers` only to `service_role` / `authenticated`, not the anon key; embedding backfill also needs `UPDATE` on `products`. Never commit service_role to git — keep it in `.env` only.

### C — Supabase schema

1. Open Supabase → **SQL Editor**
2. Run `supabase/migrations/20260518120000_cdp_stitched_schema.sql`
3. Run `supabase/seed_demo.sql` — creates `USER_7721`, product `ACC-004`, and behavioral view events

### D — Verify seed (recommended before embeddings)

```powershell
.\.venv-cdp\Scripts\python.exe scripts\verify_supabase_seed.py
```

Expected: `products` ≥ 1, `consumers (USER_7721)` = 1. If counts are 0, see [Troubleshooting](#troubleshooting).

### E — Product embeddings

```powershell
.\.venv-cdp\Scripts\python.exe scripts\backfill_product_embeddings.py
```

Expected output: `Embedded: ACC-004` (and any other SKUs without vectors).

### F — Smoke test

```powershell
.\.venv-cdp\Scripts\python.exe -c "from martech_agent import evaluate_guardrails; print(evaluate_guardrails('USER_7721'))"
```

Expected output: `shoe_promotions_suppressed: True`. If you see `No consumer found`, step C is incomplete.

---

## Golden Dataset — Create and Extend

### The canonical demo persona

All reference cases are built around the same seed scenario. Understanding it first makes every field in the case format self-explanatory.

| Attribute | Value |
|-----------|-------|
| **User** | `USER_7721` — High-Value Runner |
| **Interests** | Marathon Training, Trail Running |
| **Guardrail** | Shoe purchase 14 days ago → `shoe_promotions_suppressed = true` |
| **Behavior** | 3× views on `AeroGlow Shoes` in `behavioral_logs` |
| **Expected retrieval target** | `ACC-004` — HydroStream 2L Hydration Vest |
| **Expected exclusion** | Any `product_type = Footwear` |
| **SQL source** | `supabase/seed_demo.sql` |

### Case format

Golden cases are **JSON Lines** — one JSON object per line, no array wrapper.

- **Phase 1 file:** `eval/golden/cases.jsonl`
- **Phase 2 file:** `eval/golden/agent_cases.jsonl`

### Guardrails-only case (no `search_query`)

Runs the guardrails suite only. Use when you want to assert suppression state without testing retrieval.

```json
{
  "id": "user_7721_guardrails_shoe_suppressed",
  "user_id": "USER_7721",
  "description": "Shoe purchase 14d ago — footwear promos suppressed",
  "expect_guardrails": {
    "shoe_promotions_suppressed": true,
    "footwear_promotions_allowed": false,
    "outreach_allowed": true
  },
  "tags": ["guardrails", "shoe_suppression"]
}
```

### Positive retrieval case (include `search_query`)

Runs guardrails + vector retrieval. Use when you want to assert that the right SKU appears in the top-k results.

```json
{
  "id": "user_7721_retrieval_hydration",
  "user_id": "USER_7721",
  "search_query": "hydration vest marathon trail running accessories",
  "expect_guardrails": { "shoe_promotions_suppressed": true },
  "expect_skus_in_top_k": ["ACC-004"],
  "forbid_product_types_in_top_k": ["Footwear"],
  "tags": ["retrieval"]
}
```

### Negative retrieval case

Same user, shoe-intent query. When suppression is active, footwear must not appear in top-k — even if the query is about shoes.

```json
{
  "id": "user_7721_retrieval_footwear_blocked",
  "user_id": "USER_7721",
  "search_query": "running shoes marathon",
  "expect_guardrails": { "shoe_promotions_suppressed": true },
  "forbid_product_types_in_top_k": ["Footwear"],
  "tags": ["retrieval", "negative"]
}
```

### Agent case (phase 2 only)

Tests the full agent policy: does the LLM follow the guardrail and pivot to the correct product category?

```json
{
  "id": "agent_user_7721_hydration_campaign",
  "user_id": "USER_7721",
  "trigger": "USER_7721 viewed AeroGlow Shoes 3x. Shoe purchase 14 days ago. Hydration campaign — no footwear promos.",
  "expect_guardrails": { "shoe_promotions_suppressed": true },
  "forbid_terms_in_outcome": ["shoe", "sneaker", "footwear"],
  "expect_skus_in_outcome": ["ACC-004"],
  "tags": ["agent"]
}
```

### Field reference

| Field | Suite | Description |
|-------|-------|-------------|
| `id` | All | Unique case identifier |
| `user_id` | All | `consumers.external_id` in Supabase |
| `description` | Optional | Human note — ignored by runner |
| `search_query` | Retrieval | Presence triggers retrieval suite |
| `expect_guardrails` | All | Key-value equality checks on `evaluate_guardrails()` |
| `expect_skus_in_top_k` | Retrieval | SKU must appear in first `top_k` results |
| `forbid_product_types_in_top_k` | Retrieval | Product type (e.g. `Footwear`) must not appear in top_k |
| `trigger` | Agent | Prompt string passed to the agent |
| `forbid_terms_in_outcome` | Agent | Substrings that must not appear in the agent's markdown report |
| `expect_skus_in_outcome` | Agent | SKU that must appear in the agent's markdown report |
| `tags` | Optional | For filtering and documentation |

### Validate new cases

```powershell
python eval/run_retrieval_guardrails.py --golden eval/golden/cases.jsonl --top-k 8
python eval/run_agent.py --demo --top-k 8
```

---

## Classification Factors

### Factor model (`eval/classification_factors.py`)

```python
@dataclass(frozen=True)
class ClassificationFactors:
    top_k: int = 8
    temperature: float | None = None
    top_p: float | None = None
```

- `factor_id` — stable string key for joining reports: `top_k=8|temp=0.1|top_p=0.9`
- `retrieval_kwargs()` → `{"match_count": top_k}`
- `llm_kwargs()` → `{"temperature": ..., "top_p": ...}` when set
- `full_classification_grid(top_k_values, temperatures, top_p_values)` — Cartesian product of all combinations

### What each result row stores

```json
{
  "classification_factors": { "top_k": 8, "temperature": 0.1, "top_p": 0.9 },
  "factor_id": "top_k=8|temp=0.1|top_p=0.9",
  "retrieval_kwargs_applied": { "match_count": 8 },
  "llm_kwargs_applied": { "temperature": 0.1, "top_p": 0.9 }
}
```

### Running factor sweeps

**From the CLI:**

```powershell
# Phase 1 — sweep top_k; temp and top_p recorded
python eval/run_retrieval_guardrails.py --top-k 3,5,8 --temperature 0,0.1 --top-p 0.9,1.0

# Phase 2 — all three factors active
python eval/run_agent.py --top-k 8 --temperature 0,0.1 --top-p 0.95,1.0
```

**From environment variables:**

```powershell
$env:EVAL_TOP_K = "5,8"
$env:EVAL_TEMPERATURE = "0.1"
$env:EVAL_TOP_P = "0.95,1.0"
python eval/run_retrieval_guardrails.py --use-env-grid
```

### Joining phase 1 and phase 2 reports

Use `factor_id` as the join key. A phase 1 report and a phase 2 report with the same `factor_id` were evaluated at identical hyperparameter settings — compare retrieval precision against agent policy compliance at each point in the grid.

---

## Phase 1 — Retrieval + Guardrails

### What runs

For each golden case × each factor combination:

- **Guardrails suite** (no `search_query`): calls `evaluate_guardrails(user_id)` and asserts against `expect_guardrails`
- **Retrieval suite** (has `search_query`): runs guardrails first, then `search_inventory(query, match_count=top_k)` and asserts SKU presence and product type exclusions

### Commands

```powershell
.\.venv-cdp\Scripts\Activate.ps1

# Default run
.\scripts\run-model-eval.ps1

# Equivalent direct call
python eval/run_retrieval_guardrails.py

# With factor sweep
python eval/run_retrieval_guardrails.py --top-k 3,5,8
```

### Output

`artifacts/eval_runs/phase1_<timestamp>.json`

Exit code `0` = all assertions passed. Exit code non-zero = at least one assertion failed — read the report for detail.

### Implementation

| File | Role |
|------|------|
| `eval/run_retrieval_guardrails.py` | CLI entry point |
| `eval/runner.py` | Orchestration and factor loop |
| `eval/metrics.py` | Assertion helpers |
| `eval/golden/cases.jsonl` | Golden test cases |

---

## Phase 2 — LLM Agent

### What runs

For each agent golden case × each factor combination:

1. Sets `CDP_MATCH_COUNT` from `top_k`
2. Invokes the agent with the `trigger` prompt, passing `temperature` / `top_p` (or uses the deterministic demo path with `--demo`)
3. Asserts guardrail state, forbidden terms, and expected SKUs against the agent's markdown report

### Commands

**Deterministic — no OpenAI quota required:**

```powershell
python eval/run_agent.py --demo --top-k 8
```

**Full LLM — requires `OPENAI_API_KEY` in `.env`:**

```powershell
python eval/run_agent.py --top-k 8 --temperature 0.1 --top-p 1.0
```

### Output

- `artifacts/eval_runs/phase2_demo_<timestamp>.json` (demo path)
- `artifacts/eval_runs/phase2_llm_<timestamp>.json` (full LLM path)

### Implementation

| File | Role |
|------|------|
| `eval/run_agent.py` | CLI entry point + factor loop |
| `eval/golden/agent_cases.jsonl` | Agent golden cases |
| `martech_agent.py` | `_build_llm`, `execute_autonomous_campaign`, `execute_autonomous_campaign_demo` |

---

## Reports and Interpretation

### Top-level fields

| Field | Meaning |
|-------|---------|
| `eval_phase` | `1-retrieval-guardrails` or `2-llm-agent` |
| `classification_factor_combos` | Number of factor grid points evaluated |
| `factor_ids` | List of unique `factor_id` strings in this report |
| `overall.success` | `true` if all assertions passed across all case-runs |
| `results[].summary` | Per case-run pass/fail counts |
| `results[].assertions` | Individual assertion results |
| `results[].retrieved_skus` | Phase 1 — actual retrieval slice for that `top_k` |
| `errors` | Exceptions during the run (e.g. missing Supabase seed) |

### Artifacts layout

```
artifacts/
  eval_runs/
    phase1_20260527T165620Z.json
    phase2_demo_20260527T170000Z.json
    phase2_llm_20260527T170500Z.json
  campaign_runs/          ← agent markdown reports
  notification_queue/     ← queued push JSON
```

### How to read a failure

1. Open the phase 1 or phase 2 JSON report
2. Filter `results` by the `factor_id` you care about
3. Look at `results[].assertions` — each entry has `passed`, `assertion_type`, and `detail`
4. Cross-reference `retrieved_skus` (phase 1) or the agent markdown (phase 2) against the golden case `expect_*` fields
5. Common root causes: missing seed data, un-embedded SKUs, or `top_k` too low for the search query

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No products found. Run supabase/seed_demo.sql first` | Run `scripts/verify_supabase_seed.py`. If counts are 0: confirm SQL Editor is on the **same project** as `SUPABASE_URL` in `.env`, re-run migration then `seed_demo.sql` (paste full file — do not run `.sql` paths in PowerShell). Use **service_role** in `SUPABASE_KEY`. |
| `No consumer found for USER_7721` | Run `supabase/seed_demo.sql`; set `SUPABASE_KEY` to **service_role** (anon cannot read `consumers`) |
| Vector search returns `[]` | Run `scripts/backfill_product_embeddings.py` |
| `consumers` table not found | Run migration SQL in Supabase SQL Editor |
| Phase 1 guardrails pass but SKU assertion fails | Confirm `ACC-004` is embedded; try widening `--top-k` or refining `search_query` in the case |
| Phase 2 OpenAI 429 / quota exceeded | Use `python eval/run_agent.py --demo` |
| `Python 3.14 is not supported` | Activate `.venv-cdp` (Python 3.12) before running |
| Assertions show `0/0` (no checks ran) | Case is missing all `expect_*` fields — add at least one assertion field |
| `factor_id` mismatch between phase 1 and phase 2 | Ensure `--top-k`, `--temperature`, and `--top-p` arguments are identical across both runs |

---

## Module Reference

| Path | Purpose |
|------|---------|
| `eval/classification_factors.py` | Factor schema, Cartesian grid, env parsing, `factor_id` generation |
| `eval/golden/cases.jsonl` | Phase 1 golden cases (guardrails + retrieval) |
| `eval/golden/agent_cases.jsonl` | Phase 2 golden cases (agent triggers + outcome checks) |
| `eval/metrics.py` | Assertion helpers for guardrails, SKUs, product types, and outcome terms |
| `eval/runner.py` | Phase 1 orchestration — case loop × factor loop |
| `eval/run_retrieval_guardrails.py` | Phase 1 CLI entry point |
| `eval/run_agent.py` | Phase 2 CLI entry point + factor loop |
| `scripts/run-model-eval.ps1` | Phase 1 PowerShell wrapper for pre-demo and CI use |
| `martech_agent.py` | `evaluate_guardrails`, `search_inventory`, `execute_autonomous_campaign`, `_build_llm` |
| `cdp_pipeline.py` | `semantic_product_search` — reads `CDP_MATCH_COUNT` env |
