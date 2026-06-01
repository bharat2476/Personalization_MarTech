r"""
Backfill products.description_embedding in Supabase (384-d MiniLM).
Run inside .venv-cdp after migration + seed_demo.sql.

  .\.venv-cdp\Scripts\python.exe scripts\backfill_product_embeddings.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from cdp_pipeline import embed_text, get_supabase_client


def _compose_text(row: dict) -> str:
    tags = row.get("behavioral_tags") or []
    tag_str = " ".join(tags) if isinstance(tags, list) else str(tags)
    parts = [
        row.get("name") or "",
        row.get("description") or "",
        row.get("category") or "",
        row.get("product_type") or "",
        tag_str,
    ]
    return " ".join(p for p in parts if p).strip()


def main() -> None:
    client = get_supabase_client()
    resp = (
        client.table("products")
        .select("id, sku, name, description, category, product_type, behavioral_tags, description_embedding")
        .eq("is_active", True)
        .execute()
    )
    rows = resp.data or []
    if not rows:
        print("No products found. Run supabase/seed_demo.sql first.")
        sys.exit(1)

    updated = 0
    for row in rows:
        if row.get("description_embedding"):
            print(f"Skip (already embedded): {row.get('sku')}")
            continue
        text = _compose_text(row)
        if not text:
            print(f"Skip (empty text): {row.get('sku')}")
            continue
        vector = embed_text(text)
        client.table("products").update({"description_embedding": vector}).eq("id", row["id"]).execute()
        print(f"Embedded: {row.get('sku')}")
        updated += 1

    print(f"\nDone. Updated {updated} product(s).")


if __name__ == "__main__":
    main()
