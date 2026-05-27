# AGENTS.md

## Cursor Cloud specific instructions

### Overview

This is a single-process Python/Streamlit web app — a **Marketplace Personalization & Ad Targeting Simulator**. There are no external services, databases, or caches; all data is generated in-memory at runtime.

### Running the app

**Streamlit only** (Python 3.10–3.14; system Python is fine):

```
pip install -r requirements.txt
streamlit run streamlit_app.py --server.enableCORS false --server.enableXsrfProtection false --server.headless true
```

Or: `.\scripts\run-streamlit.ps1`

The app serves on port **8501**. See `README.md` for the canonical setup steps.

### CDP pipeline (`cdp_pipeline.py`)

Requires **Python 3.11 or 3.12** (not 3.14 — `supabase` / `sentence-transformers` lack wheels on Windows).

```
.\scripts\setup-cdp-venv.ps1
.\.venv-cdp\Scripts\Activate.ps1
```

Set `SUPABASE_URL` and `SUPABASE_KEY`, then use `requirements-cdp.txt` in that venv only.

### Known issues

- The auction module (`auction.py`) has a `KeyError: 'seller_id'` bug when merging DataFrames in `run_auction()`. This causes Tabs 3 (Ads & Auction) and 4 (Metrics Dashboard) to fail at runtime. Tabs 1 (Simulation Config) and 2 (Personalized Results) work correctly.

### Model eval

Phase 1: `.\scripts\run-model-eval.ps1` — retrieval + guardrails (`eval/golden/cases.jsonl`).  
Phase 2: `python eval/run_agent.py` (LLM) or `--demo` (no OpenAI).  
Factors: `top_k`, `temperature`, `top_p`. Full steps: `README.md#model-evaluation` and `eval/README.md`.

### Lint / Test / Build

- **No pytest suite** — phase-1 eval is `eval/run_retrieval_guardrails.py`.
- To verify modules load correctly: `python3 -c "import streamlit_app"`
- The app has no build step — run it directly with `streamlit run`.
