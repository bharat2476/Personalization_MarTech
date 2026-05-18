"""
CDP profile stitching and semantic product retrieval for Agentic RAG.

Requires:
  - Python 3.11 or 3.12 (see scripts/setup-cdp-venv.ps1; 3.14 lacks binary wheels)
  - SUPABASE_URL, SUPABASE_KEY (service role or anon with RPC grants)
  - Applied migration: supabase/migrations/20260518120000_cdp_stitched_schema.sql
  - sentence-transformers (default: all-MiniLM-L6-v2, 384-dim embeddings)
"""

from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from functools import lru_cache
from typing import Any

logger = logging.getLogger(__name__)


def _load_dotenv() -> None:
    """Load .env from project root when python-dotenv is available."""
    try:
        from dotenv import load_dotenv
        from pathlib import Path

        env_path = Path(__file__).resolve().parent / ".env"
        load_dotenv(env_path, override=True, encoding="utf-8")
    except ImportError:
        pass


_load_dotenv()

DEFAULT_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"
EMBEDDING_DIMENSION = 384
BEHAVIORAL_LOG_LIMIT = 10
DEFAULT_MATCH_COUNT = 8

_SUPPORTED_PYTHON = ((3, 11), (3, 12))


class CDPPipelineError(Exception):
    """Base error for CDP pipeline operations."""


class CDPConfigurationError(CDPPipelineError):
    """Missing or invalid environment configuration."""


class CDPConsumerNotFoundError(CDPPipelineError):
    """No consumer row for the requested external_id."""


class CDPSupabaseError(CDPPipelineError):
    """Supabase client or PostgREST/RPC failure."""


class CDPEmbeddingError(CDPPipelineError):
    """Text embedding generation failed."""


def _check_python_version() -> None:
    if sys.version_info[:2] in _SUPPORTED_PYTHON:
        return
    if sys.version_info >= (3, 14) or sys.version_info < (3, 11):
        raise CDPConfigurationError(
            f"Python {sys.version_info.major}.{sys.version_info.minor} is not supported for CDP deps. "
            "Create the CDP venv: .\\scripts\\setup-cdp-venv.ps1  (uses Python 3.12 or 3.11)"
        )


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value or not str(value).strip():
        raise CDPConfigurationError(
            f"Environment variable {name!r} is required but not set."
        )
    return str(value).strip()


def get_supabase_client():
    """Build a Supabase client from environment variables."""
    _check_python_version()
    try:
        from supabase import create_client
    except ImportError as exc:
        raise CDPConfigurationError(
            "supabase-py is not installed. Run: pip install supabase"
        ) from exc

    url = _require_env("SUPABASE_URL")
    key = _require_env("SUPABASE_KEY")
    try:
        return create_client(url, key)
    except Exception as exc:
        raise CDPSupabaseError(f"Failed to create Supabase client: {exc}") from exc


@lru_cache(maxsize=1)
def _get_embedding_model():
    """Load the sentence-transformers model once per process."""
    model_name = os.environ.get("EMBEDDING_MODEL_NAME", DEFAULT_EMBEDDING_MODEL)
    try:
        from sentence_transformers import SentenceTransformer
    except ImportError as exc:
        raise CDPConfigurationError(
            "sentence-transformers is not installed. "
            "Run: pip install sentence-transformers"
        ) from exc

    try:
        logger.info("Loading embedding model: %s", model_name)
        return SentenceTransformer(model_name)
    except Exception as exc:
        raise CDPEmbeddingError(f"Could not load embedding model {model_name!r}: {exc}") from exc


def embed_text(query_text: str) -> list[float]:
    """Encode query text to a unit-normalized 384-d vector for match_products RPC."""
    if not query_text or not query_text.strip():
        raise CDPEmbeddingError("query_text must be a non-empty string.")

    try:
        model = _get_embedding_model()
        vector = model.encode(
            query_text.strip(),
            normalize_embeddings=True,
            show_progress_bar=False,
        )
        embedding = vector.tolist()
        if len(embedding) != EMBEDDING_DIMENSION:
            raise CDPEmbeddingError(
                f"Expected {EMBEDDING_DIMENSION}-d embedding, got {len(embedding)}. "
                "Align EMBEDDING_MODEL_NAME with your Supabase vector column dimension."
            )
        return embedding
    except CDPPipelineError:
        raise
    except Exception as exc:
        raise CDPEmbeddingError(f"Embedding failed: {exc}") from exc


def _iso(dt: Any) -> str | None:
    if dt is None:
        return None
    if isinstance(dt, datetime):
        return dt.astimezone(timezone.utc).isoformat()
    return str(dt)


def _fetch_consumer(client, external_id: str) -> dict[str, Any]:
    try:
        response = (
            client.table("consumers")
            .select("*")
            .eq("external_id", external_id)
            .limit(1)
            .execute()
        )
    except Exception as exc:
        err = str(exc)
        if "PGRST205" in err or "Could not find the table" in err:
            raise CDPSupabaseError(
                "Table public.consumers not found. Run supabase/migrations/"
                "20260518120000_cdp_stitched_schema.sql in Supabase SQL Editor, "
                "then supabase/seed_demo.sql."
            ) from exc
        if "Invalid API key" in err or "401" in err:
            raise CDPSupabaseError(
                "Invalid SUPABASE_KEY. Use the anon (eyJ...) or service_role key from "
                "Project Settings -> API (publishable keys may not work for all queries)."
            ) from exc
        raise CDPSupabaseError(f"Consumer lookup failed: {exc}") from exc

    rows = response.data or []
    if not rows:
        raise CDPConsumerNotFoundError(f"No consumer found for external_id={external_id!r}.")
    return rows[0]


def _fetch_recent_behavior(client, consumer_id: str, limit: int = BEHAVIORAL_LOG_LIMIT) -> list[dict[str, Any]]:
    try:
        response = (
            client.table("behavioral_logs")
            .select(
                "id, event_type, target_id, target_category, session_id, "
                "session_propensity_score, event_metadata, occurred_at"
            )
            .eq("consumer_id", consumer_id)
            .order("occurred_at", desc=True)
            .limit(limit)
            .execute()
        )
    except Exception as exc:
        raise CDPSupabaseError(f"Behavioral log fetch failed: {exc}") from exc

    return list(response.data or [])


def _compute_behavior_aggregates(events: list[dict[str, Any]]) -> dict[str, Any]:
    if not events:
        return {
            "event_count": 0,
            "avg_session_propensity": None,
            "event_type_counts": {},
            "distinct_targets": [],
        }

    propensity_values = [
        float(e["session_propensity_score"])
        for e in events
        if e.get("session_propensity_score") is not None
    ]
    type_counts: dict[str, int] = {}
    targets: list[str] = []
    for event in events:
        et = event.get("event_type") or "unknown"
        type_counts[et] = type_counts.get(et, 0) + 1
        tid = event.get("target_id")
        if tid and tid not in targets:
            targets.append(tid)

    return {
        "event_count": len(events),
        "avg_session_propensity": (
            round(sum(propensity_values) / len(propensity_values), 4)
            if propensity_values
            else None
        ),
        "event_type_counts": type_counts,
        "distinct_targets": targets[:10],
    }


def _is_shoe_suppressed(consumer: dict[str, Any]) -> bool:
    """Mirror DB guardrail: suppression active inside shoe_suppression_window."""
    last_purchase = consumer.get("last_shoe_purchase_at")
    if not last_purchase:
        return False

    window_raw = consumer.get("shoe_suppression_window") or "14 days"
    try:
        if isinstance(window_raw, str) and "day" in window_raw:
            days = int(window_raw.split()[0])
        else:
            days = 14
    except (ValueError, TypeError):
        days = 14

    try:
        if isinstance(last_purchase, str):
            anchor = datetime.fromisoformat(last_purchase.replace("Z", "+00:00"))
        else:
            anchor = last_purchase
        if anchor.tzinfo is None:
            anchor = anchor.replace(tzinfo=timezone.utc)
        elapsed_days = (datetime.now(timezone.utc) - anchor).days
        return elapsed_days < days
    except Exception:
        return False


def stitch_golden_record(user_id: str) -> dict[str, Any]:
    """
    Stitch zero-party consumer profile with the latest behavioral telemetry.

    Args:
        user_id: External CDP identifier (consumers.external_id), e.g. USER_7721.

    Returns:
        Unified golden record dict for downstream ranking / RAG agents.
    """
    if not user_id or not str(user_id).strip():
        raise CDPPipelineError("user_id must be a non-empty string.")

    external_id = str(user_id).strip()

    try:
        client = get_supabase_client()
        consumer = _fetch_consumer(client, external_id)
        consumer_uuid = consumer["id"]
        events = _fetch_recent_behavior(client, consumer_uuid, BEHAVIORAL_LOG_LIMIT)
        aggregates = _compute_behavior_aggregates(events)

        shoe_suppressed = _is_shoe_suppressed(consumer)

        return {
            "stitched_at": datetime.now(timezone.utc).isoformat(),
            "external_id": external_id,
            "consumer_id": consumer_uuid,
            "identity": {
                "segment": consumer.get("segment"),
                "lifecycle_stage": consumer.get("lifecycle_stage"),
                "channel_preference": consumer.get("channel_preference"),
            },
            "zero_party": {
                "declared_interests": consumer.get("declared_interests") or [],
                "browser_intent_signal": consumer.get("browser_intent_signal"),
            },
            "demographics": {
                "gender": consumer.get("gender"),
                "age_group": consumer.get("age_group"),
                "location_region": consumer.get("location_region"),
            },
            "consent": {
                "email_opt_in": consumer.get("email_opt_in"),
                "consent_marketing": consumer.get("consent_marketing"),
                "consent_app_usage": consumer.get("consent_app_usage"),
            },
            "guardrails": {
                "last_shoe_purchase_at": _iso(consumer.get("last_shoe_purchase_at")),
                "shoe_suppression_window": consumer.get("shoe_suppression_window"),
                "shoe_promotions_suppressed": shoe_suppressed,
                "max_weekly_touches": consumer.get("max_weekly_touches"),
                "touches_sent_this_week": consumer.get("touches_sent_this_week"),
            },
            "recent_behavior": events,
            "behavior_aggregates": aggregates,
            "metadata": consumer.get("metadata") or {},
        }
    except CDPPipelineError:
        raise
    except Exception as exc:
        raise CDPPipelineError(f"stitch_golden_record failed: {exc}") from exc


def semantic_product_search(
    query_text: str,
    category_filter: str | None = None,
    *,
    match_count: int | None = None,
    exclude_footwear: bool = False,
) -> list[dict[str, Any]]:
    """
    Embed query_text and retrieve products via Supabase match_products RPC.

    Args:
        query_text: Natural-language intent for vector search.
        category_filter: Optional products.category equality filter.
        match_count: Top-k results (default from CDP_MATCH_COUNT env or 8).
        exclude_footwear: When True, passes exclude_product_types=['Footwear'].

    Returns:
        List of product match dicts from PostgREST (sku, name, similarity, ...).
    """
    try:
        embedding = embed_text(query_text)
        client = get_supabase_client()
        k = match_count or int(os.environ.get("CDP_MATCH_COUNT", DEFAULT_MATCH_COUNT))

        rpc_params: dict[str, Any] = {
            "query_embedding": embedding,
            "match_count": k,
            "filter_category": category_filter,
            "active_only": True,
        }
        if exclude_footwear:
            rpc_params["exclude_product_types"] = ["Footwear"]

        try:
            response = client.rpc("match_products", rpc_params).execute()
        except Exception as exc:
            raise CDPSupabaseError(f"match_products RPC failed: {exc}") from exc

        return list(response.data or [])
    except CDPPipelineError:
        raise
    except Exception as exc:
        raise CDPPipelineError(f"semantic_product_search failed: {exc}") from exc


def compile_agent_context(user_id: str, search_query: str) -> str:
    """
    Build Agentic RAG prompt context: golden record + semantic product matches.

    Returns:
        Markdown string suitable for LLM system/context injection.
    """
    if not search_query or not str(search_query).strip():
        raise CDPPipelineError("search_query must be a non-empty string.")

    try:
        golden = stitch_golden_record(user_id)
        exclude_shoes = golden["guardrails"].get("shoe_promotions_suppressed", False)
        interests = golden["zero_party"].get("declared_interests") or []

        products = semantic_product_search(
            search_query,
            exclude_footwear=exclude_shoes,
        )

        lines: list[str] = [
            "# Agent Context — CDP Golden Record",
            "",
            f"**Stitched at (UTC):** {golden['stitched_at']}",
            f"**Consumer ID:** `{golden['external_id']}`",
            "",
            "## Customer Profile",
            "",
            f"- **Segment:** {golden['identity'].get('segment') or '—'}",
            f"- **Lifecycle:** {golden['identity'].get('lifecycle_stage') or '—'}",
            f"- **Declared interests (0-party):** {', '.join(interests) or '—'}",
            f"- **Browser intent:** {golden['zero_party'].get('browser_intent_signal') or '—'}",
            "",
            "## Demographics",
            "",
            f"- **Gender:** {golden['demographics'].get('gender') or '—'}",
            f"- **Age group:** {golden['demographics'].get('age_group') or '—'}",
            f"- **Region:** {golden['demographics'].get('location_region') or '—'}",
            "",
            "## Marketing Guardrails",
            "",
            f"- **Shoe promotions suppressed:** "
            f"{'YES — do not recommend or promote footwear' if exclude_shoes else 'No'}",
            f"- **Last shoe purchase:** {golden['guardrails'].get('last_shoe_purchase_at') or 'None on file'}",
            f"- **Suppression window:** {golden['guardrails'].get('shoe_suppression_window') or '—'}",
            f"- **Weekly touches:** "
            f"{golden['guardrails'].get('touches_sent_this_week', 0)} / "
            f"{golden['guardrails'].get('max_weekly_touches', '—')}",
            "",
            "## Recent Behavior (last "
            f"{golden['behavior_aggregates']['event_count']} events)",
            "",
        ]

        if golden["recent_behavior"]:
            lines.append("| Time (UTC) | Event | Target | Propensity |")
            lines.append("|------------|-------|--------|------------|")
            for event in golden["recent_behavior"]:
                lines.append(
                    f"| {event.get('occurred_at', '—')} | "
                    f"{event.get('event_type', '—')} | "
                    f"`{event.get('target_id', '—')}` | "
                    f"{event.get('session_propensity_score', '—')} |"
                )
        else:
            lines.append("_No behavioral events in the retention window._")

        agg = golden["behavior_aggregates"]
        lines.extend([
            "",
            f"- **Avg session propensity:** {agg.get('avg_session_propensity', '—')}",
            f"- **Event mix:** {agg.get('event_type_counts') or '—'}",
            "",
            "## Semantic Product Matches",
            "",
            f"**Search query:** {search_query.strip()}",
            "",
        ])

        if products:
            for idx, product in enumerate(products, start=1):
                sim = product.get("similarity")
                sim_str = f"{sim:.3f}" if isinstance(sim, (int, float)) else str(sim)
                lines.extend([
                    f"### {idx}. {product.get('name', 'Unknown')}",
                    f"- **SKU:** `{product.get('sku', '—')}`",
                    f"- **Category:** {product.get('category', '—')}",
                    f"- **Type:** {product.get('product_type', '—')}",
                    f"- **Price:** ${product.get('price', '—')}",
                    f"- **Cosine similarity:** {sim_str}",
                    "",
                ])
        else:
            lines.append("_No vector matches returned. Ensure product embeddings are backfilled._")

        lines.extend([
            "## Agent Instructions",
            "",
            "1. Respect shoe suppression — never push footwear promos when suppressed.",
            "2. Prefer semantic matches that align with declared interests and recent behavior.",
            "3. Cite SKU and match rationale when recommending products.",
            "",
        ])

        return "\n".join(lines)
    except CDPPipelineError:
        raise
    except Exception as exc:
        raise CDPPipelineError(f"compile_agent_context failed: {exc}") from exc
