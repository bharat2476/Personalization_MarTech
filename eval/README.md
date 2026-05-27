# Model evaluation — complete runbook

Deterministic and LLM-based evaluation for the MarTech CDP stack: **golden dataset**, **classification factors** (`top_k`, `temperature`, `top_p`), **phase 1** (retrieval + guardrails), and **phase 2** (autonomous agent).

Canonical copy also lives in the root **[README.md — Model evaluation](../README.md#model-evaluation)** section.

---

## Table of contents

1. [Concepts](#concepts)
2. [Prerequisites (one-time setup)](#prerequisites-one-time-setup)
3. [Golden dataset — create and extend](#golden-dataset--create-and-extend)
4. [Classification factors — temperature, top_p, top_k](#classification-factors--temperature-top_p-top_k)
5. [Phase 1 — retrieval + guardrails](#phase-1--retrieval--guardrails)
6. [Phase 2 — LLM agent](#phase-2--llm-agent)
7. [Reports and interpretation](#reports-and-interpretation)
8. [Troubleshooting](#troubleshooting)
9. [Module reference](#module-reference)

---

## Concepts

### Two meanings of “golden”

| Term | What it is | Where |
|------|------------|--------|
| **CDP golden record** | Runtime stitch of profile + behavior for RAG | `cdp_pipeline.stitch_golden_record()` |
| **Eval golden dataset** | Fixed test cases with expected outcomes | `eval/golden/*.jsonl` |

Eval golden cases are version-controlled fixtures; CDP golden records are live database reads.

### What we evaluate

| Layer | Phase | Module | Needs OpenAI |
|-------|-------|--------|--------------|
| Guardrails | 1 | `martech_agent.evaluate_guardrails` | No |
| Vector retrieval | 1 | `martech_agent.search_inventory` | No |
| LLM agent policy | 2 | `martech_agent.execute_autonomous_campaign` | Yes |
| Agent (deterministic) | 2 `--demo` | `execute_autonomous_campaign_demo` | No |

### Classification factors

Hyperparameters treated as **experiment dimensions**. Every result row includes a `factor_id` so you can compare runs:

```
top_k=8|temp=0.1|top_p=0.9
```

| Factor | Phase 1 | Phase 2 |
|--------|---------|---------|
| **top_k** | Active → `semantic_product_search(match_count)` | Active → `CDP_MATCH_COUNT` env during agent tool calls |
| **temperature** | Recorded on report | Active → `ChatOpenAI(temperature=...)` |
| **top_p** | Recorded on report | Active → `ChatOpenAI(model_kwargs={"top_p": ...})` |

---

## Prerequisites (one-time setup)

Complete these before any eval run.

### Step A — CDP Python environment

```powershell
cd c:\Users\agarw\adtech-platform\blank-app
.\scripts\setup-cdp-venv.ps1
.\.venv-cdp\Scripts\Activate.ps1
pip install -r requirements-cdp.txt -r requirements-agent.txt
```

Use **Python 3.11 or 3.12** in `.venv-cdp` (not 3.14).

### Step B — Environment variables

Copy `.env.example` → `.env`:

| Variable | Required for | Example |
|----------|--------------|---------|
| `SUPABASE_URL` | Phase 1 & 2 | `https://<ref>.supabase.co` |
| `SUPABASE_KEY` | Phase 1 & 2 | anon JWT `eyJ...` |
| `OPENAI_API_KEY` | Phase 2 LLM only | `sk-...` |
| `OPENAI_MODEL` | Phase 2 (optional) | `gpt-4o-mini` |
| `OPENAI_TEMPERATURE` | Default LLM temp | `0.1` |
| `EVAL_TOP_K` | Factor sweep via env | `3,5,8` |
| `EVAL_TEMPERATURE` | Factor sweep via env | `0,0.1,0.3` |
| `EVAL_TOP_P` | Factor sweep via env | `0.9,1.0` |

### Step C — Supabase schema

1. Open Supabase → **SQL Editor**.
2. Run `supabase/migrations/20260518120000_cdp_stitched_schema.sql`.
3. Run `supabase/seed_demo.sql` (creates `USER_7721`, `ACC-004`, behavioral views).

### Step D — Product embeddings

```powershell
.\.venv-cdp\Scripts\python.exe scripts\backfill_product_embeddings.py
```

Expect: `Embedded: ACC-004` (and other SKUs).

### Step E — Smoke test

```powershell
.\.venv-cdp\Scripts\python.exe -c "from martech_agent import evaluate_guardrails; print(evaluate_guardrails('USER_7721'))"
```

Expect: `shoe_promotions_suppressed: True`, not `No consumer found`.

---

## Golden dataset — create and extend

### Step 1 — Understand case format

Golden cases are **JSON Lines** (one JSON object per line, no array wrapper).

**Phase 1 file:** `eval/golden/cases.jsonl`  
**Phase 2 file:** `eval/golden/agent_cases.jsonl`

### Step 2 — Start from the canonical demo persona

Seed data defines the reference scenario:

- **User:** `USER_7721` — High-Value Runner, shoe purchase 14 days ago.
- **Behavior:** 3× views on `AeroGlow Shoes`.
- **Expected retrieval:** `ACC-004` (HydroStream hydration vest), not `Footwear`.
- **SQL source:** `supabase/seed_demo.sql`.

### Step 3 — Add a guardrails-only case

No `search_query` → runs guardrails suite only.

```json
{
  "id": "user_7721_guardrails_shoe_suppressed",
  "user_id": "USER_7721",
  "description": "Shoe purchase 14d ago → footwear promos suppressed",
  "expect_guardrails": {
    "shoe_promotions_suppressed": true,
    "footwear_promotions_allowed": false,
    "outreach_allowed": true
  },
  "tags": ["guardrails", "shoe_suppression"]
}
```

### Step 4 — Add a retrieval case

Include `search_query` → runs retrieval + optional guardrail checks.

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

### Step 5 — Add a negative retrieval case

Same user, shoe-intent query — footwear must not appear in top_k when suppressed.

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

### Step 6 — Add an agent case (phase 2)

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

### Step 7 — Golden case field reference

| Field | Suite | Description |
|-------|-------|-------------|
| `id` | All | Unique case name |
| `user_id` | All | `consumers.external_id` |
| `description` | Optional | Human note (ignored by runner) |
| `search_query` | Retrieval | If set, case runs retrieval suite |
| `expect_guardrails` | Guardrails / retrieval / agent | Key-value equality on `evaluate_guardrails()` |
| `expect_skus_in_top_k` | Retrieval | SKU must appear in first `top_k` results |
| `forbid_product_types_in_top_k` | Retrieval | e.g. `Footwear` must not appear in top_k |
| `trigger` | Agent | Prompt passed to agent |
| `forbid_terms_in_outcome` | Agent | Substrings that must not appear in report |
| `expect_skus_in_outcome` | Agent | SKU must appear in final markdown report |
| `tags` | Optional | Filtering / documentation |

### Step 8 — Validate new cases

```powershell
python eval/run_retrieval_guardrails.py --golden eval/golden/cases.jsonl --top-k 8
python eval/run_agent.py --demo --top-k 8
```

---

## Classification factors — temperature, top_p, top_k

### Step 1 — Define the factor model (implemented)

File: `eval/classification_factors.py`

```python
@dataclass(frozen=True)
class ClassificationFactors:
    top_k: int = 8
    temperature: float | None = None
    top_p: float | None = None
```

- `factor_id` — stable grouping key for reports.
- `retrieval_kwargs()` → `{"match_count": top_k}`.
- `llm_kwargs()` → `{"temperature": ..., "top_p": ...}` when set.
- `full_classification_grid(top_k_values, temperatures, top_p_values)` — Cartesian product.

### Step 2 — Attach factors to every eval row (implemented)

Each result in `artifacts/eval_runs/*.json` includes:

```json
{
  "classification_factors": { "top_k": 8, "temperature": 0.1, "top_p": 0.9 },
  "factor_id": "top_k=8|temp=0.1|top_p=0.9",
  "retrieval_kwargs_applied": { "match_count": 8 },
  "llm_kwargs_applied": { "temperature": 0.1, "top_p": 0.9 }
}
```

### Step 3 — Wire top_k into retrieval (implemented)

`martech_agent.search_inventory(..., match_count=factors.top_k)` → `semantic_product_search`.

Assertions in `eval/metrics.py` slice results to `products[:top_k]`.

### Step 4 — Record temperature and top_p in phase 1 (implemented)

Phase 1 does not change retrieval when you sweep temp/top_p — they are stored so reports align with phase 2 runs using the same grid.

```powershell
python eval/run_retrieval_guardrails.py --top-k 3,5,8 --temperature 0,0.1 --top-p 0.9,1.0
```

### Step 5 — Activate temperature and top_p in phase 2 (implemented)

`martech_agent._build_llm(temperature=..., top_p=...)` and `execute_autonomous_campaign(..., temperature=..., top_p=...)`.

`eval/run_agent.py` loops the factor grid and passes LLM kwargs per combo.

### Step 6 — Wire top_k for agent tool retrieval (implemented)

`eval/run_agent.py` sets `CDP_MATCH_COUNT=<top_k>` for each factor combo before invoking the agent (tools read this in `cdp_pipeline.semantic_product_search`).

### Step 7 — Sweep factors from CLI or environment

**CLI:**

```powershell
python eval/run_retrieval_guardrails.py --top-k 3,5,8 --temperature 0,0.1 --top-p 0.9,1.0
python eval/run_agent.py --top-k 8 --temperature 0,0.1 --top-p 0.95,1.0
```

**Environment:**

```powershell
$env:EVAL_TOP_K = "5,8"
$env:EVAL_TEMPERATURE = "0.1"
$env:EVAL_TOP_P = "0.95,1.0"
python eval/run_retrieval_guardrails.py --use-env-grid
```

### Step 8 — Join phase 1 and phase 2 reports

Use the same `factor_id` string in both `phase1_*.json` and `phase2_*.json` to compare retrieval vs agent behavior at identical hyperparameters.

---

## Phase 1 — retrieval + guardrails

### What runs

For each **golden case** × **classification factor combo**:

1. **Guardrails suite** (no `search_query`): `evaluate_guardrails(user_id)` vs `expect_guardrails`.
2. **Retrieval suite** (has `search_query`): guardrails + `search_inventory(query, match_count=top_k)` vs SKU/type assertions.

### Commands

```powershell
.\.venv-cdp\Scripts\Activate.ps1
.\scripts\run-model-eval.ps1
# equivalent:
python eval/run_retrieval_guardrails.py
python eval/run_retrieval_guardrails.py --top-k 3,5,8
```

### Output

`artifacts/eval_runs/phase1_<timestamp>.json`

Exit code `0` = all assertions passed, no errors.

### Implementation files

| File | Role |
|------|------|
| `eval/run_retrieval_guardrails.py` | CLI entry |
| `eval/runner.py` | Orchestration |
| `eval/metrics.py` | Assertions |
| `eval/golden/cases.jsonl` | Golden labels |

---

## Phase 2 — LLM agent

### What runs

For each **agent golden case** × **factor combo**:

1. Set `CDP_MATCH_COUNT` from `top_k`.
2. Call agent with `temperature` / `top_p` (or `--demo` for deterministic path without OpenAI).
3. Assert guardrails + outcome text (forbidden terms, expected SKUs).

### Commands

**Deterministic (no OpenAI quota):**

```powershell
python eval/run_agent.py --demo --top-k 8
```

**Full LLM:**

```powershell
# Requires OPENAI_API_KEY in .env
python eval/run_agent.py --top-k 8 --temperature 0.1 --top-p 1.0
```

### Output

`artifacts/eval_runs/phase2_demo_<timestamp>.json` or `phase2_llm_<timestamp>.json`

### Implementation files

| File | Role |
|------|------|
| `eval/run_agent.py` | CLI + factor loop |
| `eval/golden/agent_cases.jsonl` | Agent golden cases |
| `martech_agent.py` | `_build_llm`, `execute_autonomous_campaign` overrides |

---

## Reports and interpretation

### Top-level fields

| Field | Meaning |
|-------|---------|
| `eval_phase` | `1-retrieval-guardrails` or `2-llm-agent` |
| `classification_factor_combos` | Number of factor grid points |
| `factor_ids` | List of unique `factor_id` values |
| `overall.success` | All assertions passed |
| `results[].summary` | Per case-run pass/fail counts |

### Example: pivot by factor

Filter `results` where `factor_id == "top_k=5|temp=na|top_p=na"` and inspect `assertions` for failures.

### Artifacts layout

```
artifacts/
  eval_runs/
    phase1_20260527T165620Z.json
    phase2_demo_20260527T170000Z.json
    phase2_llm_20260527T170500Z.json
  campaign_runs/          # agent markdown reports
  notification_queue/     # queued push JSON
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `No consumer found for USER_7721` | Run `supabase/seed_demo.sql` |
| Vector search `[]` | Run `backfill_product_embeddings.py` |
| `consumers` table not found | Run migration SQL |
| Phase 1 passes guardrails but fails SKU | Confirm `ACC-004` embedded; lower `--top-k` or improve query |
| Phase 2 OpenAI 429 | Use `python eval/run_agent.py --demo` |
| `Python 3.14 is not supported` | Use `.venv-cdp` (3.12) |
| Assertions 0/0 | Case missing `expect_*` fields |

---

## Module reference

| Path | Purpose |
|------|---------|
| `eval/classification_factors.py` | Factor schema, grids, env parsing |
| `eval/golden/cases.jsonl` | Phase 1 golden cases |
| `eval/golden/agent_cases.jsonl` | Phase 2 golden cases |
| `eval/metrics.py` | Assertion helpers |
| `eval/runner.py` | Phase 1 orchestration |
| `eval/run_retrieval_guardrails.py` | Phase 1 CLI |
| `eval/run_agent.py` | Phase 2 CLI |
| `scripts/run-model-eval.ps1` | Phase 1 PowerShell wrapper |
