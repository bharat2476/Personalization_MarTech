r"""
Verify Supabase migration + seed_demo for local CDP / eval setup.

  .\.venv-cdp\Scripts\python.exe scripts\verify_supabase_seed.py
"""

from __future__ import annotations

import sys
from pathlib import Path
from urllib.parse import urlparse

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cdp_pipeline import _load_dotenv, get_supabase_client  # noqa: E402

_load_dotenv()


def _project_ref(url: str) -> str:
    host = urlparse(url).netloc or url
    return host.split(".")[0] if host else "unknown"


def _count(client, table: str, **filters) -> int:
    q = client.table(table).select("*", count="exact")
    for key, value in filters.items():
        q = q.eq(key, value)
    resp = q.limit(1).execute()
    return int(resp.count or 0)


def _key_kind(key: str) -> str:
    if key.startswith("eyJ"):
        try:
            import base64
            import json

            payload = key.split(".")[1]
            payload += "=" * (4 - len(payload) % 4)
            role = json.loads(base64.urlsafe_b64decode(payload)).get("role", "?")
            return f"jwt ({role})"
        except Exception:
            return "jwt (unknown role)"
    if key.startswith("sb_publishable"):
        return "publishable (not for local CDP scripts)"
    if key.startswith("sb_secret"):
        return "secret"
    return "unknown"


def main() -> None:
    import os

    url = os.environ.get("SUPABASE_URL", "").strip()
    key = os.environ.get("SUPABASE_KEY", "").strip()
    if not url:
        print("SUPABASE_URL is not set. Copy .env.example to .env and fill in values.")
        sys.exit(1)
    if not key:
        print("SUPABASE_KEY is not set.")
        sys.exit(1)

    print(f"Supabase project: {_project_ref(url)}")
    print(f"URL: {url}")
    kind = _key_kind(key)
    print(f"SUPABASE_KEY: {kind}")
    if kind != "jwt (service_role)":
        print(
            "WARN: Local scripts need service_role (Project Settings -> API). "
            "Save .env (Ctrl+S) — Python reads the file on disk, not unsaved editor text.\n"
        )
    print(
        "Tip: SQL Editor must be open on this same project "
        "(Dashboard URL contains the same ref).\n"
    )

    client = get_supabase_client()

    try:
        products = _count(client, "products")
        active = _count(client, "products", is_active=True)
        consumers = _count(client, "consumers")
        user = _count(client, "consumers", external_id="USER_7721")
    except Exception as exc:
        err = str(exc)
        if "PGRST205" in err or "Could not find the table" in err:
            print("FAIL: CDP tables missing.")
            print("  Run supabase/migrations/20260518120000_cdp_stitched_schema.sql in SQL Editor.")
        elif "401" in err or "Invalid API key" in err:
            print("FAIL: Invalid SUPABASE_KEY for this project.")
        else:
            print(f"FAIL: {exc}")
        sys.exit(1)

    print(f"products (all):              {products}")
    print(f"products (is_active=true):   {active}")
    print(f"consumers (all):             {consumers}")
    print(f"consumers (USER_7721):      {user}")

    ok = True
    if products == 0:
        ok = False
        print(
            "\nNo products visible via API. In SQL Editor on THIS project, run:\n"
            "  SELECT sku, is_active FROM public.products;\n"
            "If that returns rows but this script shows 0, enable service_role in .env "
            "(Project Settings -> API -> service_role secret) or disable RLS on products."
        )
        print(
            "If SQL also returns 0 rows, re-run migration then supabase/seed_demo.sql "
            "(paste full file; confirm success message)."
        )
    if consumers == 0 or user == 0:
        ok = False
        print(
            "\nNo USER_7721 consumer visible via API. The migration grants consumer SELECT "
            "to service_role/authenticated only — use SUPABASE_KEY=service_role in .env "
            "for local scripts, then re-run seed_demo.sql if SQL shows no row."
        )

    if ok:
        print("\nOK: seed data is visible. Next: scripts/backfill_product_embeddings.py")
        sys.exit(0)

    sys.exit(1)


if __name__ == "__main__":
    main()
