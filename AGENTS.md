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

### Lint / Test / Build

- **No automated test suite or linter configuration exists in this repo.** There are no `pytest`, `flake8`, `mypy`, or similar configs.
- To verify modules load correctly: `python3 -c "import streamlit_app"`
- The app has no build step — run it directly with `streamlit run`.
