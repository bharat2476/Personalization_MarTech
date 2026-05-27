"""
Autonomous MarTech Campaign Orchestration Engine (Agentic RAG).

LangGraph ReAct agent with OpenAI function-calling over CDP tools:
  get_customer_profile, evaluate_guardrails, search_inventory, queue_notification

Requires: Python 3.11/3.12 (.venv-cdp), .env with SUPABASE_* and OPENAI_API_KEY.
"""

from __future__ import annotations

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from langchain_core.messages import AIMessage, HumanMessage, SystemMessage, ToolMessage
from langchain_core.tools import tool
from langchain_openai import ChatOpenAI
from langgraph.prebuilt import create_react_agent

from cdp_pipeline import (
    CDPConsumerNotFoundError,
    CDPPipelineError,
    _load_dotenv,
    get_supabase_client,
    semantic_product_search,
    stitch_golden_record,
)

_load_dotenv()

logger = logging.getLogger(__name__)

ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts" / "campaign_runs"
QUEUE_DIR = Path(__file__).resolve().parent / "artifacts" / "notification_queue"

SYSTEM_PROMPT = """You are the Autonomous MarTech Campaign Orchestration Engine — a precise, \
compliance-first marketing strategist for a performance retail CDP.

## Mission
Analyze customer signals, enforce operational guardrails, retrieve valid product alternatives \
via vector search, and produce tailored promotional copy only when policy allows outreach.

## Mandatory workflow (strict order — do not skip steps)
1. `get_customer_profile(user_id)` — load golden CDP record and recent behavior.
2. `evaluate_guardrails(user_id)` — read suppression windows and frequency caps BEFORE any recommendation.
3. Shoe suppression rule (CRITICAL): If the customer bought shoes within the suppression window \
(e.g. 14 days ago) OR `shoe_promotions_suppressed` is true, you MUST refuse to suggest, promote, \
or message about footwear (shoes, sneakers, `Footwear` product_type) — even when the trigger \
event shows repeated shoe views or explicit shoe search intent.
4. `search_inventory(query, user_id)` — vector search for allowed alternatives only \
(accessories, hydration, apparel layers) aligned to declared interests and the trigger.
5. If and only if `outreach_allowed` is true, call `queue_notification(user_id, message)` with \
final copy citing a real SKU from search results.
6. If blocked, report which guardrail fired and the best non-footwear alternative without queueing.

## Copy standards
- Cite concrete SKU, product name, and match rationale (0-party interests + 1-party behavior).
- Tone: expert endurance retail partner; no hype spam.
- Never invent inventory, prices, or discounts not returned by tools.

## Final response format
Guardrail Status | Recommended SKU (or NONE) | Rationale | Final Message (or SUPPRESSED + reason)
"""

__all__ = [
    "execute_autonomous_campaign",
    "execute_autonomous_campaign_demo",
    "get_customer_profile",
    "search_inventory",
    "evaluate_guardrails",
    "queue_notification",
    "MARTECH_TOOLS",
    "MarTechAgentError",
    "SYSTEM_PROMPT",
]


class MarTechAgentError(Exception):
    """Agent orchestration failure."""


def _json_payload(data: Any) -> str:
    return json.dumps(data, indent=2, default=str)


# ---------------------------------------------------------------------------
# Core tool logic (also invoked by @tool wrappers for the LLM)
# ---------------------------------------------------------------------------

def get_customer_profile(user_id: str) -> dict[str, Any]:
    """Fetch unified CDP golden record (profile + last 10 behavioral events)."""
    try:
        return stitch_golden_record(user_id.strip())
    except CDPConsumerNotFoundError as exc:
        return {"error": str(exc), "external_id": user_id}
    except CDPPipelineError as exc:
        raise MarTechAgentError(f"get_customer_profile failed: {exc}") from exc


def search_inventory(
    query: str,
    user_id: str | None = None,
    *,
    match_count: int | None = None,
) -> list[dict[str, Any]]:
    """
    Semantic vector search over Supabase `products` via match_products RPC.

    When user_id is provided, footwear is excluded if shoe suppression is active.
    match_count maps to eval classification factor top_k when set.
    """
    exclude_footwear = False
    if user_id:
        try:
            guardrails = evaluate_guardrails(user_id)
            exclude_footwear = bool(guardrails.get("shoe_promotions_suppressed"))
        except MarTechAgentError:
            pass

    try:
        return semantic_product_search(
            query.strip(),
            exclude_footwear=exclude_footwear,
            match_count=match_count,
        )
    except CDPPipelineError as exc:
        raise MarTechAgentError(f"search_inventory failed: {exc}") from exc


def evaluate_guardrails(user_id: str) -> dict[str, Any]:
    """Return shoe suppression windows, frequency caps, consent, and outreach eligibility."""
    try:
        golden = stitch_golden_record(user_id.strip())
        guardrails = golden.get("guardrails", {})
        consent = golden.get("consent", {})
        touches_sent = guardrails.get("touches_sent_this_week", 0) or 0
        max_touches = guardrails.get("max_weekly_touches", 3) or 3
        frequency_cap_hit = touches_sent >= max_touches
        shoe_suppressed = bool(guardrails.get("shoe_promotions_suppressed"))
        marketing_allowed = bool(
            consent.get("consent_marketing") and consent.get("email_opt_in")
        )
        outreach_allowed = marketing_allowed and not frequency_cap_hit

        blocked_reasons: list[str] = []
        if not marketing_allowed:
            blocked_reasons.append("marketing_consent_or_opt_in_false")
        if frequency_cap_hit:
            blocked_reasons.append("weekly_frequency_cap_reached")
        if shoe_suppressed:
            blocked_reasons.append("shoe_promotion_suppression_active")

        return {
            "external_id": golden.get("external_id"),
            "consumer_id": golden.get("consumer_id"),
            "guardrails": guardrails,
            "consent": consent,
            "shoe_promotions_suppressed": shoe_suppressed,
            "footwear_promotions_allowed": not shoe_suppressed,
            "frequency_cap_hit": frequency_cap_hit,
            "weekly_touches": f"{touches_sent}/{max_touches}",
            "outreach_allowed": outreach_allowed,
            "blocked_reasons": blocked_reasons,
            "policy_notes": (
                "14-day (or configured) post-shoe-purchase window: no footwear promos; "
                "use accessories/apparel vector matches instead."
            ),
        }
    except CDPConsumerNotFoundError as exc:
        return {"error": str(exc), "external_id": user_id, "outreach_allowed": False}
    except CDPPipelineError as exc:
        raise MarTechAgentError(f"evaluate_guardrails failed: {exc}") from exc


def queue_notification(user_id: str, message: str) -> dict[str, Any]:
    """Log finalized promotional outreach to Supabase behavioral_logs + local queue."""
    if not message or not message.strip():
        return {"queued": False, "error": "message must be non-empty"}

    external_id = user_id.strip()
    timestamp = datetime.now(timezone.utc).isoformat()
    queue_entry: dict[str, Any] = {
        "external_id": external_id,
        "message": message.strip(),
        "queued_at": timestamp,
        "channel": "push",
        "status": "QUEUED",
    }

    try:
        golden = stitch_golden_record(external_id)
        consumer_id = golden["consumer_id"]
        client = get_supabase_client()

        try:
            client.table("behavioral_logs").insert(
                {
                    "consumer_id": consumer_id,
                    "event_type": "push_sent",
                    "target_id": "campaign_orchestrator",
                    "target_category": "Marketing",
                    "session_propensity_score": golden.get("behavior_aggregates", {}).get(
                        "avg_session_propensity"
                    ),
                    "event_metadata": {
                        "message": message.strip(),
                        "queued_by": "martech_agent",
                        "queued_at": timestamp,
                    },
                    "occurred_at": timestamp,
                }
            ).execute()
            queue_entry["supabase_logged"] = True
        except Exception as exc:
            logger.warning("Supabase queue log failed, using local fallback: %s", exc)
            queue_entry["supabase_logged"] = False
            queue_entry["supabase_error"] = str(exc)

        QUEUE_DIR.mkdir(parents=True, exist_ok=True)
        safe_id = external_id.replace("/", "_")
        queue_file = (
            QUEUE_DIR
            / f"{safe_id}_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.json"
        )
        queue_file.write_text(_json_payload(queue_entry), encoding="utf-8")
        queue_entry["local_queue_file"] = str(queue_file)
        queue_entry["queued"] = True
        return queue_entry

    except CDPPipelineError as exc:
        return {"queued": False, "error": str(exc), "external_id": external_id}


# ---------------------------------------------------------------------------
# LangChain @tool wrappers (exact names exposed to OpenAI function calling)
# ---------------------------------------------------------------------------

@tool
def get_customer_profile_tool(user_id: str) -> str:
    """Load unified CDP golden record: zero-party profile + last 10 behavioral events."""
    return _json_payload(get_customer_profile(user_id))


@tool
def search_inventory_tool(query: str, user_id: str = "") -> str:
    """
    Vector search Supabase product catalog. Pass user_id to auto-exclude Footwear when suppressed.
    """
    uid = user_id.strip() or None
    return _json_payload(search_inventory(query, user_id=uid))


@tool
def evaluate_guardrails_tool(user_id: str) -> str:
    """Return shoe suppression window, frequency caps, consent flags, outreach_allowed."""
    return _json_payload(evaluate_guardrails(user_id))


@tool
def queue_notification_tool(user_id: str, message: str) -> str:
    """Queue finalized tailored promotional message for delivery."""
    return _json_payload(queue_notification(user_id, message))


# Register tools under canonical names for the LLM
get_customer_profile_tool.name = "get_customer_profile"
search_inventory_tool.name = "search_inventory"
evaluate_guardrails_tool.name = "evaluate_guardrails"
queue_notification_tool.name = "queue_notification"

MARTECH_TOOLS = [
    get_customer_profile_tool,
    search_inventory_tool,
    evaluate_guardrails_tool,
    queue_notification_tool,
]


def _build_llm(
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    model: str | None = None,
) -> ChatOpenAI:
    """Build ChatOpenAI; optional overrides support model-eval classification factor sweeps."""
    api_key = os.environ.get("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise MarTechAgentError(
            "OPENAI_API_KEY is not set. Add it to .env or your environment."
        )
    resolved_model = model or os.environ.get("OPENAI_MODEL", "gpt-4o-mini")
    resolved_temp = (
        temperature
        if temperature is not None
        else float(os.environ.get("OPENAI_TEMPERATURE", "0.1"))
    )
    kwargs: dict[str, Any] = {
        "model": resolved_model,
        "temperature": resolved_temp,
        "api_key": api_key,
    }
    if top_p is not None:
        kwargs["model_kwargs"] = {"top_p": top_p}
    return ChatOpenAI(**kwargs)


def _build_agent(
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    model: str | None = None,
):
    """LangGraph ReAct agent with OpenAI tool-calling bound to MARTECH_TOOLS."""
    llm = _build_llm(temperature=temperature, top_p=top_p, model=model)
    return create_react_agent(
        llm,
        MARTECH_TOOLS,
        prompt=SystemMessage(content=SYSTEM_PROMPT),
    )


def _format_reasoning_chain(messages: list[Any]) -> str:
    lines = ["## Agent reasoning chain", ""]
    step = 0

    for msg in messages:
        if isinstance(msg, HumanMessage):
            lines.append("### Task input")
            lines.append(str(msg.content))
            lines.append("")
        elif isinstance(msg, AIMessage):
            step += 1
            lines.append(f"### Step {step} — Assistant")
            if msg.content:
                lines.append(str(msg.content))
            if msg.tool_calls:
                for call in msg.tool_calls:
                    name = call.get("name", "unknown")
                    args = call.get("args", {})
                    lines.append(f"- **Tool call:** `{name}`")
                    lines.append(f"  - **Args:** `{json.dumps(args)}`")
            lines.append("")
        elif isinstance(msg, ToolMessage):
            lines.append(f"### Tool result — `{msg.name}`")
            content = str(msg.content)
            if len(content) > 4000:
                content = content[:4000] + "\n... (truncated)"
            lines.append(f"```json\n{content}\n```")
            lines.append("")

    return "\n".join(lines)


def _extract_final_outcome(messages: list[Any]) -> str:
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content and not msg.tool_calls:
            return str(msg.content)
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return str(msg.content)
    return "No final assistant message produced."


def _save_campaign_artifact(user_id: str, report: str) -> Path:
    ARTIFACTS_DIR.mkdir(parents=True, exist_ok=True)
    safe_id = user_id.strip().replace("/", "_")
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    path = ARTIFACTS_DIR / f"{safe_id}_{stamp}.md"
    path.write_text(report, encoding="utf-8")
    return path


def execute_autonomous_campaign_demo(user_id: str, trigger_event_summary: str) -> str:
    """Deterministic tool-chain runner (no OpenAI quota). Same policy order as the LLM agent."""
    external_id = str(user_id).strip()
    trigger = str(trigger_event_summary).strip()
    steps: list[str] = ["## Agent reasoning chain (demo mode — no LLM)", ""]

    profile = get_customer_profile(external_id)
    steps.extend(
        [
            "### Step 1 — get_customer_profile",
            f"```json\n{_json_payload(profile)}\n```",
            "",
        ]
    )

    guardrails = evaluate_guardrails(external_id)
    steps.extend(
        [
            "### Step 2 — evaluate_guardrails",
            f"```json\n{_json_payload(guardrails)}\n```",
            "",
        ]
    )

    search_query = (
        "hydration vest marathon trail running accessories"
        if guardrails.get("shoe_promotions_suppressed")
        else "running gear marathon trail"
    )
    inventory = search_inventory(search_query, user_id=external_id)
    steps.extend(
        [
            "### Step 3 — search_inventory",
            f"- **Query:** {search_query}",
            f"```json\n{_json_payload(inventory)}\n```",
            "",
        ]
    )

    outreach_ok = bool(guardrails.get("outreach_allowed"))
    shoe_blocked = bool(guardrails.get("shoe_promotions_suppressed"))
    top = inventory[0] if inventory else None

    if outreach_ok and top:
        msg = (
            f"Hi {external_id}, ready for your next long run? "
            f"Based on your marathon and trail interests, we picked the "
            f"{top.get('name')} (SKU {top.get('sku')}) — "
            f"{'a smart alternative while shoe promos are paused' if shoe_blocked else 'matched to your goals'}."
        )
        queued = queue_notification(external_id, msg)
        steps.extend(
            [
                "### Step 4 — queue_notification",
                f"```json\n{_json_payload(queued)}\n```",
                "",
            ]
        )
        outcome = (
            f"**Guardrail status:** Shoe suppression={'ACTIVE' if shoe_blocked else 'inactive'}; "
            f"outreach={'ALLOWED' if outreach_ok else 'BLOCKED'}\n\n"
            f"**Recommended SKU:** `{top.get('sku')}` — {top.get('name')}\n\n"
            f"**Final message:** {msg}"
        )
    else:
        reason = guardrails.get("blocked_reasons") or ["outreach_not_allowed_or_no_inventory"]
        sku_line = (
            f"`{top.get('sku')}` — {top.get('name')}"
            if top
            else "NONE (backfill product embeddings in Supabase)"
        )
        outcome = (
            f"**SUPPRESSED** — {', '.join(reason)}.\n\n"
            f"**Recommended SKU:** {sku_line}\n\n"
            "No notification queued."
        )

    report = "\n".join(
        [
            "# Autonomous MarTech Campaign Run (Demo Mode)",
            "",
            f"- **User ID:** `{external_id}`",
            f"- **Executed at (UTC):** {datetime.now(timezone.utc).isoformat()}",
            f"- **Trigger:** {trigger}",
            "",
            "\n".join(steps),
            "## Final campaign outcome",
            "",
            outcome,
            "",
        ]
    )
    path = _save_campaign_artifact(external_id, report)
    report += f"\n---\n**Artifact saved:** `{path}`\n"
    return report


def execute_autonomous_campaign(
    user_id: str,
    trigger_event_summary: str,
    *,
    temperature: float | None = None,
    top_p: float | None = None,
    model: str | None = None,
) -> str:
    """
    Execute the autonomous MarTech agent loop.

    Optional temperature / top_p / model override eval classification factors (phase 2).

    Returns:
        Markdown report with step-by-step reasoning chain and final campaign outcome.
        Persisted to artifacts/campaign_runs/{user_id}_{timestamp}.md.
    """
    if not user_id or not str(user_id).strip():
        raise MarTechAgentError("user_id is required")
    if not trigger_event_summary or not str(trigger_event_summary).strip():
        raise MarTechAgentError("trigger_event_summary is required")

    external_id = str(user_id).strip()
    trigger = str(trigger_event_summary).strip()

    user_task = (
        f"Execute an autonomous campaign for consumer `{external_id}`.\n\n"
        f"**Trigger event summary:** {trigger}\n\n"
        "Follow the mandatory workflow. If shoe suppression applies, refuse footwear promos "
        "and search_inventory with user_id for compliant alternatives. "
        "Queue notification only when outreach_allowed is true."
    )

    try:
        agent = _build_agent(temperature=temperature, top_p=top_p, model=model)
        result = agent.invoke({"messages": [HumanMessage(content=user_task)]})
        messages = result.get("messages", [])
        reasoning = _format_reasoning_chain(messages)
        final_outcome = _extract_final_outcome(messages)

        report = "\n".join(
            [
                "# Autonomous MarTech Campaign Run",
                "",
                f"- **User ID:** `{external_id}`",
                f"- **Executed at (UTC):** {datetime.now(timezone.utc).isoformat()}",
                f"- **Trigger:** {trigger}",
                "",
                reasoning,
                "## Final campaign outcome",
                "",
                final_outcome,
                "",
            ]
        )

        artifact_path = _save_campaign_artifact(external_id, report)
        report += f"\n---\n**Artifact saved:** `{artifact_path}`\n"
        return report

    except MarTechAgentError:
        raise
    except Exception as exc:
        err = str(exc).lower()
        if "insufficient_quota" in err or "429" in err:
            raise MarTechAgentError(
                "OpenAI quota exceeded. Add billing at https://platform.openai.com/settings/billing "
                "or run: python martech_agent.py --demo USER_7721 \"<trigger>\""
            ) from exc
        raise MarTechAgentError(f"execute_autonomous_campaign failed: {exc}") from exc


if __name__ == "__main__":
    import sys

    logging.basicConfig(level=logging.INFO)
    args = [a for a in sys.argv[1:] if a != "--demo"]
    demo_mode = "--demo" in sys.argv or os.environ.get("MARTECH_DEMO_MODE", "").lower() in (
        "1",
        "true",
        "yes",
    )
    uid = args[0] if args else "USER_7721"
    trigger_text = (
        args[1]
        if len(args) > 1
        else (
            "Viewed AeroGlow Shoes 3x in 10 minutes; shoe purchase 14 days ago. "
            "Interests: Marathon Training, Trail Running."
        )
    )
    runner = execute_autonomous_campaign_demo if demo_mode else execute_autonomous_campaign
    print(runner(uid, trigger_text))
