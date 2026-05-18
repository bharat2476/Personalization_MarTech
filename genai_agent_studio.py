"""
Tab 8 — GenAI Agent Studio UI for Agentic RAG / martech_agent orchestration.
"""

from __future__ import annotations

import json
import os
import re
from datetime import datetime, timezone
from typing import Any

import streamlit as st

# CDP agent stack (Python 3.11/3.12 + Supabase); graceful fallback for Streamlit on 3.14
_AGENT_IMPORT_ERROR: str | None = None
try:
    from martech_agent import (
        MarTechAgentError,
        evaluate_guardrails,
        execute_autonomous_campaign,
        get_customer_profile,
        queue_notification,
        search_inventory,
    )

    _CDP_AGENT_AVAILABLE = True
except Exception as exc:  # noqa: BLE001 — surface any import/config failure in UI
    _CDP_AGENT_AVAILABLE = False
    _AGENT_IMPORT_ERROR = str(exc)

from ranking import shoe_email_status


def init_genai_studio_session(session_state) -> None:
    session_state.setdefault("agent_messages", [])
    session_state.setdefault("agent_telemetry", [])
    session_state.setdefault("last_queued_notification", None)
    session_state.setdefault("agent_studio_user_id", "USER_7721")


def _infer_search_query(user_prompt: str, shoe_suppressed: bool) -> str:
    prompt = user_prompt.lower()
    if shoe_suppressed or any(k in prompt for k in ("shoe", "sneaker", "footwear")):
        return "hydration vest marathon trail running accessories"
    if "hydration" in prompt:
        return "hydration pack vest marathon trail accessories"
    if "high-value" in prompt or "fitness" in prompt:
        return "premium running accessories marathon training"
    return user_prompt[:240] if len(user_prompt) > 20 else "running accessories apparel marathon"


def _build_assistant_reply(
    user_id: str,
    user_prompt: str,
    profile: dict[str, Any],
    guardrails: dict[str, Any],
    inventory: list[dict[str, Any]],
    queued: dict[str, Any] | None,
) -> str:
    shoe_blocked = bool(guardrails.get("shoe_promotions_suppressed"))
    outreach = bool(guardrails.get("outreach_allowed"))
    top = inventory[0] if inventory else None

    lines = [
        f"**Campaign orchestration complete** for `{user_id}`.",
        "",
        f"**Your request:** {user_prompt}",
        "",
        "### Guardrail status",
        f"- Shoe promotion suppression: **{'ACTIVE' if shoe_blocked else 'Clear'}**",
        f"- Outreach allowed: **{'Yes' if outreach else 'No'}**",
        f"- Weekly touches: `{guardrails.get('weekly_touches', '—')}`",
    ]
    if guardrails.get("blocked_reasons"):
        lines.append(f"- Blockers: `{', '.join(guardrails['blocked_reasons'])}`")

    lines.extend(["", "### Vector match (inventory)"])
    if top:
        sim = top.get("similarity")
        sim_txt = f"{sim:.3f}" if isinstance(sim, (int, float)) else "—"
        lines.append(
            f"Top SKU: **`{top.get('sku')}`** — {top.get('name')} "
            f"(${top.get('price')}, {top.get('category')}) · similarity {sim_txt}"
        )
    else:
        lines.append(
            "_No vector matches returned. Ensure Supabase migration, seed, and "
            "product embeddings are configured._"
        )

    if queued and queued.get("queued"):
        lines.extend(["", "### Outreach", "Notification **queued** — see alert below."])
    elif not outreach:
        lines.extend(
            [
                "",
                "### Outreach",
                "**SUPPRESSED** — guardrails blocked promotional send. "
                "Non-footwear alternatives are still shown for merchandising.",
            ]
        )
    elif shoe_blocked:
        lines.append(
            "",
            "Footwear was excluded from vector retrieval while suppression is active."
        )

    return "\n".join(lines)


def _run_cdp_instrumented_pipeline(
    user_id: str,
    user_prompt: str,
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    """Execute martech_agent tools; return reply, telemetry steps, optional queue payload."""
    telemetry: list[dict[str, Any]] = []
    queued_payload: dict[str, Any] | None = None

    telemetry.append(
        {
            "step": "cdp_connect",
            "label": "CDP golden record stitch",
            "status": "running",
            "detail": f"Reading consumers + behavioral_logs for {user_id}",
        }
    )
    profile = get_customer_profile(user_id)
    if profile.get("error"):
        telemetry[-1]["status"] = "error"
        telemetry[-1]["detail"] = profile["error"]
        return (
            f"CDP lookup failed: {profile['error']}. "
            "Run `supabase/migrations/...sql` and `supabase/seed_demo.sql` in your project.",
            telemetry,
            None,
        )
    telemetry[-1]["status"] = "complete"
    telemetry[-1]["detail"] = (
        f"Segment={profile.get('identity', {}).get('segment')} · "
        f"Interests={profile.get('zero_party', {}).get('declared_interests')}"
    )

    telemetry.append(
        {
            "step": "guardrails",
            "label": "Guardrail evaluation",
            "status": "running",
            "detail": "Checking shoe suppression window and frequency caps",
        }
    )
    guardrails = evaluate_guardrails(user_id)
    shoe_blocked = bool(guardrails.get("shoe_promotions_suppressed"))
    telemetry[-1]["status"] = "complete"
    if shoe_blocked:
        telemetry[-1]["detail"] = (
            "⚠️ Shoe promotions SUPPRESSED — footwear must not be messaged"
        )
    else:
        telemetry[-1]["detail"] = (
            f"Footwear promos allowed · outreach_allowed={guardrails.get('outreach_allowed')}"
        )

    search_q = _infer_search_query(user_prompt, shoe_blocked)
    telemetry.append(
        {
            "step": "vector_search",
            "label": "Semantic vector retrieval",
            "status": "running",
            "detail": f"match_products RPC · query=\"{search_q}\""
            + (" · excluding Footwear" if shoe_blocked else ""),
        }
    )
    inventory = search_inventory(search_q, user_id=user_id)
    telemetry[-1]["status"] = "complete"
    telemetry[-1]["detail"] = f"{len(inventory)} SKU(s) returned from HNSW index"

    if guardrails.get("outreach_allowed") and inventory:
        top = inventory[0]
        msg = (
            f"Hi {user_id}, your next run is covered — try the {top.get('name')} "
            f"(SKU {top.get('sku')}). "
            f"{'Picked as a hydration-focused alternative while shoe promos are paused.' if shoe_blocked else 'Matched to your training interests.'}"
        )
        telemetry.append(
            {
                "step": "queue_notification",
                "label": "queue_notification tool",
                "status": "running",
                "detail": "Writing to behavioral_logs + local notification queue",
            }
        )
        queued_payload = queue_notification(user_id, msg)
        telemetry[-1]["status"] = (
            "complete" if queued_payload.get("queued") else "error"
        )
        telemetry[-1]["detail"] = queued_payload.get(
            "local_queue_file", queued_payload.get("error", "queued")
        )
    else:
        telemetry.append(
            {
                "step": "queue_notification",
                "label": "queue_notification tool",
                "status": "skipped",
                "detail": "Skipped — outreach blocked or no inventory match",
            }
        )

    reply = _build_assistant_reply(
        user_id, user_prompt, profile, guardrails, inventory, queued_payload
    )
    return reply, telemetry, queued_payload


def _run_simulator_fallback_pipeline(
    user_id: str,
    user_prompt: str,
    session_state,
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    """In-memory orchestration using Tab 1 simulation state when CDP is unavailable."""
    telemetry: list[dict[str, Any]] = []
    user = session_state.get("user")
    if user is None:
        return (
            "Run **Member & Strategy → Run Simulation** in Tab 1 first, "
            "or use CDP mode with `USER_7721` seeded in Supabase.",
            [],
            None,
        )

    telemetry.append(
        {
            "step": "cdp_connect",
            "label": "Simulator profile (fallback)",
            "status": "complete",
            "detail": f"{user.get('customer_name')} · {user.get('lifecycle_stage')}",
        }
    )

    status = shoe_email_status(user)
    shoe_blocked = status.startswith("Suppress shoe")
    telemetry.append(
        {
            "step": "guardrails",
            "label": "Guardrail evaluation",
            "status": "complete",
            "detail": status,
        }
    )

    products_df = session_state.get("products")
    inv_rows: list[dict[str, Any]] = []
    if products_df is not None and not products_df.empty:
        subset = products_df.copy()
        if shoe_blocked:
            subset = subset[subset["product_type"] != "Footwear"]
        subset = subset.sort_values("trend_score", ascending=False).head(5)
        for _, row in subset.iterrows():
            inv_rows.append(
                {
                    "sku": row.get("sku", row.get("product_id")),
                    "name": row["name"],
                    "category": row["category"],
                    "price": float(row["price"]),
                    "similarity": 0.75,
                }
            )

    telemetry.append(
        {
            "step": "vector_search",
            "label": "Catalog ranking (simulator fallback)",
            "status": "complete",
            "detail": f"{len(inv_rows)} products · shoe_blocked={shoe_blocked}",
        }
    )

    guardrails = {
        "shoe_promotions_suppressed": shoe_blocked,
        "outreach_allowed": not status.startswith("Do not") and "Suppress email" not in status,
        "weekly_touches": "simulator",
        "blocked_reasons": ["shoe_promotion_suppression_active"] if shoe_blocked else [],
    }
    profile = {
        "identity": {"segment": user.get("segment"), "lifecycle_stage": user.get("lifecycle_stage")},
        "zero_party": {"declared_interests": user.get("interests", [])},
    }

    queued_payload = None
    if guardrails["outreach_allowed"] and inv_rows:
        top = inv_rows[0]
        msg = (
            f"Hi {user.get('customer_name', user_id)}, check out {top['name']} "
            f"(SKU {top['sku']}) for your next session."
        )
        telemetry.append(
            {
                "step": "queue_notification",
                "label": "queue_notification (simulated)",
                "status": "complete",
                "detail": msg[:120] + "...",
            }
        )
        queued_payload = {
            "queued": True,
            "message": msg,
            "channel": "push",
            "simulated": True,
        }
    else:
        telemetry.append(
            {
                "step": "queue_notification",
                "label": "queue_notification",
                "status": "skipped",
                "detail": "Suppressed by simulator guardrails",
            }
        )

    reply = _build_assistant_reply(user_id, user_prompt, profile, guardrails, inv_rows, queued_payload)
    reply += "\n\n_ℹ️ Simulator fallback mode (CDP agent unavailable on this Python runtime)._"
    return reply, telemetry, queued_payload


def process_agent_chat_turn(
    user_prompt: str,
    user_id: str,
    session_state,
    *,
    use_llm: bool = False,
) -> tuple[str, list[dict[str, Any]], dict[str, Any] | None]:
    """Process one chat turn; returns assistant text, telemetry, optional queue payload."""
    user_prompt = user_prompt.strip()
    user_id = user_id.strip() or "USER_7721"

    if _CDP_AGENT_AVAILABLE:
        try:
            if use_llm and os.environ.get("OPENAI_API_KEY", "").strip():
                telemetry = [
                    {
                        "step": "llm_agent",
                        "label": "LangGraph ReAct agent",
                        "status": "running",
                        "detail": "OpenAI tool-calling over CDP tools",
                    }
                ]
                report = execute_autonomous_campaign(user_id, user_prompt)
                telemetry[0]["status"] = "complete"
                telemetry[0]["detail"] = "Campaign report generated"
                queued = None
                if "Notification **queued**" in report or "QUEUED" in report:
                    match = re.search(r"\*\*Final message:\*\*\s*(.+)", report, re.DOTALL)
                    if match:
                        queued = {"queued": True, "message": match.group(1).strip()[:500]}
                return report[:6000], telemetry, queued
            return _run_cdp_instrumented_pipeline(user_id, user_prompt)
        except MarTechAgentError:
            return _run_simulator_fallback_pipeline(user_id, user_prompt, session_state)
        except Exception as exc:
            return (
                f"Agent error: {exc}",
                [{"step": "error", "label": "Error", "status": "error", "detail": str(exc)}],
                None,
            )

    return _run_simulator_fallback_pipeline(user_id, user_prompt, session_state)


def render_agent_telemetry_expander(telemetry: list[dict[str, Any]]) -> None:
    with st.expander("Agent Reasoning Telemetry Trace", expanded=True):
        if not telemetry:
            st.caption("Telemetry appears after your first agent query.")
            return

        for item in telemetry:
            label = item.get("label", "Step")
            status = item.get("status", "complete")
            detail = item.get("detail", "")
            icon = {"running": "🔄", "complete": "✅", "error": "❌", "skipped": "⏭️"}.get(
                status, "•"
            )
            with st.status(f"{icon} {label}", state="complete" if status != "error" else "error"):
                st.write(detail)
                if item.get("step") == "guardrails" and "SUPPRESSED" in detail:
                    st.warning("Operational constraint: footwear campaigns blocked.")
                if item.get("step") == "vector_search":
                    st.info("HNSW cosine retrieval against `products.description_embedding`.")


def render_genai_agent_studio_tab(session_state) -> None:
    init_genai_studio_session(session_state)

    st.header("Tab 8: GenAI Agent Studio")
    st.markdown(
        """
        **Autonomous operations layer** — natural language replaces brittle manual rules.
        Marketers describe outcomes in plain English; the agent stitches CDP profiles,
        evaluates suppression guardrails, runs vector retrieval, and queues compliant outreach.
        """
    )
    st.caption(
        "Powered by `martech_agent.py` · LangGraph ReAct · Supabase CDP · pgvector `match_products`"
    )

    if not _CDP_AGENT_AVAILABLE and _AGENT_IMPORT_ERROR:
        st.warning(
            f"CDP agent runtime not loaded ({_AGENT_IMPORT_ERROR[:120]}…). "
            "Using **simulator fallback** when Tab 1 simulation is active, or install `.venv-cdp`."
        )

    ctrl1, ctrl2, ctrl3 = st.columns([2, 2, 1])
    with ctrl1:
        user_id = st.text_input(
            "CDP external_id",
            value=session_state.get("agent_studio_user_id", "USER_7721"),
            help="e.g. USER_7721 from supabase/seed_demo.sql",
        )
    with ctrl2:
        use_llm = st.toggle(
            "Use full LLM agent (OpenAI)",
            value=False,
            help="Requires OPENAI_API_KEY and billing; otherwise instrumented tool trace runs locally.",
        )
    with ctrl3:
        if st.button("Clear chat", use_container_width=True):
            session_state["agent_messages"] = []
            session_state["agent_telemetry"] = []
            session_state["last_queued_notification"] = None
            st.rerun()

    session_state["agent_studio_user_id"] = user_id

    for msg in session_state.get("agent_messages", []):
        with st.chat_message(msg.get("role", "assistant")):
            st.markdown(msg.get("content", ""))

    if session_state.get("last_queued_notification"):
        n = session_state["last_queued_notification"]
        st.success(
            f"**Simulated push notification queued**\n\n"
            f"**To:** `{n.get('external_id', user_id)}` · **Channel:** {n.get('channel', 'push')}\n\n"
            f"_{n.get('message', '')}_",
            icon="📣",
        )

    example = (
        "Find high-value fitness members who passed our engagement threshold, "
        "check guardrails, and build a hydration accessory campaign."
    )
    if prompt := st.chat_input(f"Ask the MarTech agent… (e.g. {example[:60]}…)"):
        session_state["agent_messages"].append({"role": "user", "content": prompt})
        with st.spinner("Orchestrating campaign…"):
            reply, telemetry, queued = process_agent_chat_turn(
                prompt,
                user_id,
                session_state,
                use_llm=use_llm,
            )
        session_state["agent_messages"].append(
            {
                "role": "assistant",
                "content": reply,
                "ts": datetime.now(timezone.utc).isoformat(),
            }
        )
        session_state["agent_telemetry"] = telemetry
        if queued and queued.get("queued"):
            session_state["last_queued_notification"] = {
                "external_id": user_id,
                "message": queued.get("message", ""),
                "channel": queued.get("channel", "push"),
                "queued_at": datetime.now(timezone.utc).isoformat(),
                "simulated": queued.get("simulated", False),
            }
        st.rerun()

    render_agent_telemetry_expander(session_state.get("agent_telemetry", []))

    with st.expander("Example prompts", expanded=False):
        st.markdown(
            """
            - `USER_7721 viewed AeroGlow Shoes 3x — shoe purchase 14 days ago. Recommend accessories only.`
            - `Check guardrails and queue a hydration vest campaign for marathon trainers.`
            - `Search inventory for trail running layers; suppress footwear promos.`
            """
        )
