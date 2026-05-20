# Personalization & Marketing Tech Simulator — Pre-Demo Runbook

## One-command health check

```powershell
cd c:\Users\agarw\adtech-platform\blank-app
.\scripts\pre-demo.ps1
```

Start the app after checks pass:

```powershell
.\scripts\pre-demo.ps1 -StartStreamlit
```

Or:

```powershell
.\scripts\run-streamlit.ps1
```

Open **http://localhost:8501**

---

## Before demo — action items

### A. One-time infrastructure (Supabase)

| # | Action | Where |
|---|--------|--------|
| 1 | Enable **pgvector** + create tables | Supabase → SQL Editor → paste `supabase/migrations/20260518120000_cdp_stitched_schema.sql` → **Run** |
| 2 | Seed demo consumer + product | SQL Editor → paste `supabase/seed_demo.sql` → **Run** |
| 3 | Backfill vector embeddings | Terminal: `.\.venv-cdp\Scripts\python.exe scripts\backfill_product_embeddings.py` |

### B. Local environment

| # | Action | Notes |
|---|--------|--------|
| 4 | Copy `.env.example` → `.env` | Never commit `.env` |
| 5 | Set `SUPABASE_URL` | Project URL from Dashboard |
| 6 | Set `SUPABASE_KEY` | Prefer **anon** JWT (`eyJ...`) if `sb_publishable_...` returns 401 |
| 7 | (Optional) `OPENAI_API_KEY` | Only for full LLM agent / Tab 8 toggle |
| 8 | Create CDP venv | `.\scripts\setup-cdp-venv.ps1` (Python 3.12) |

### C. 10 minutes before demo

| # | Action |
|---|--------|
| 9 | Run `.\scripts\pre-demo.ps1` — all checks green or warnings understood |
| 10 | Start Streamlit (see commands above) |
| 11 | **Tab 1** → pick member filters → **Run Simulation** |
| 12 | **Tab 8** → `USER_7721` → send sample prompt (below) |
| 13 | Confirm telemetry trace + green push notification card |

---

## Sample Tab 8 prompt

```text
USER_7721 viewed AeroGlow Shoes 3 times in 10 minutes. Shoe purchase was 14 days ago.
Check guardrails and build a hydration accessory campaign — no footwear promos.
```

---

## Demo script (5–7 min)

1. **Tab 1 — Member & Strategy** — Show segment filters, privacy modes, signals JSON, **Run Simulation**.
2. **Tab 2 — Recommendations** — View/click products; show “Why am I seeing this?” and variant radios.
3. **Tab 3 — Marketing & Ads** — Propensity-gated push; sidebar propensity logs.
4. **Tab 8 — GenAI Agent Studio** — NL query → telemetry (CDP → guardrails → vector → queue) → `st.success` push copy.

**Fallback:** If Supabase is down, Tab 8 uses **simulator fallback** after Tab 1 simulation (banner explains mode).

---

## CLI alternatives (optional)

```powershell
.\.venv-cdp\Scripts\Activate.ps1

# CDP golden record
python -c "from cdp_pipeline import stitch_golden_record; print(stitch_golden_record('USER_7721'))"

# Agent without OpenAI billing
python martech_agent.py --demo USER_7721 "Viewed AeroGlow Shoes 3x; shoe purchase 14 days ago."
```

---

## Troubleshooting

| Symptom | Fix |
|---------|-----|
| `consumers` table not found | Run migration SQL in Supabase |
| `USER_7721` not found | Run `seed_demo.sql` |
| Vector search returns `[]` | Run `backfill_product_embeddings.py` |
| OpenAI 429 / quota | Tab 8: turn **off** “Use full LLM agent”; use instrumented mode |
| Tab 8 CDP warning on 3.14 | Normal — use Tab 1 simulation fallback or run Streamlit from machine with `.venv-cdp` for imports |
| Tabs 3–4 errors | Known `auction.py` seller_id issue — stick to Tabs 1, 2, 8 for demo |

---

## Live Streamlit Cloud (optional)

https://blank-app-zwp52hqbzm2sxhgqckmv6w.streamlit.app/

GenAI Agent Studio requires secrets (`SUPABASE_*`, optional `OPENAI_*`) configured in Streamlit Cloud — local demo is recommended for Tab 8.
