"""Personalization & Marketing Tech Simulator — enterprise visual layer and telemetry helpers."""

from __future__ import annotations

import json
from datetime import datetime

import pandas as pd
import streamlit as st

from martech_engine import (
    PROPENSITY_THRESHOLD,
    REC_VARIANT_HYBRID,
    behavioral_affinity_score,
    build_dynamic_reason,
    compute_propensity_score,
)
from seed_data import get_mock_1st_party_data

APP_NAME = "Personalization & Marketing Tech Simulator"
APP_PAGE_TITLE = f"{APP_NAME} | MarTech Demo"


def inject_enterprise_css() -> None:
    st.markdown(
        """
        <style>
          :root {
            --ps-bg: #F8FAFC;
            --ps-card: #FFFFFF;
            --ps-sidebar: #0F172A;
            --ps-sidebar-text: #E2E8F0;
            --ps-accent: #2563EB;
            --ps-accent-alt: #0D9488;
            --ps-border: #E2E8F0;
            --ps-text: #0F172A;
            --ps-muted: #64748B;
          }
          .stApp {
            background-color: var(--ps-bg);
          }
          [data-testid="stAppViewContainer"] > .main {
            background-color: var(--ps-bg);
          }
          [data-testid="stHeader"] {
            background: rgba(248, 250, 252, 0.92);
            border-bottom: 1px solid var(--ps-border);
          }
          [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0F172A 0%, #1E293B 100%);
            border-right: 1px solid #1E293B;
          }
          [data-testid="stSidebar"] h1,
          [data-testid="stSidebar"] h2,
          [data-testid="stSidebar"] h3,
          [data-testid="stSidebar"] p,
          [data-testid="stSidebar"] label,
          [data-testid="stSidebar"] span,
          [data-testid="stSidebar"] .stCaption {
            color: var(--ps-sidebar-text) !important;
          }
          [data-testid="stSidebar"] [data-baseweb="radio"],
          [data-testid="stSidebar"] [data-baseweb="select"],
          [data-testid="stSidebar"] input,
          [data-testid="stSidebar"] button {
            pointer-events: auto !important;
          }
          [data-testid="stSidebar"] [role="radiogroup"] label {
            cursor: pointer !important;
            color: var(--ps-sidebar-text) !important;
          }
          [data-testid="stSidebar"] [data-baseweb="radio"] > div {
            background-color: transparent !important;
          }
          .ps-control-bar label {
            color: var(--ps-muted) !important;
            font-size: 0.78rem !important;
            font-weight: 600 !important;
            text-transform: uppercase;
            letter-spacing: 0.05em;
          }
          .ps-variant-panel {
            background: var(--ps-card);
            border: 1px solid var(--ps-border);
            border-radius: 12px;
            padding: 0.85rem 1.1rem 0.65rem;
            margin: 0.5rem 0 0.85rem 0;
            box-shadow: 0 2px 8px rgba(15, 23, 42, 0.05);
          }
          .ps-variant-panel h4 {
            margin: 0 0 0.35rem 0;
            color: var(--ps-text);
            font-size: 0.95rem;
          }
          [data-testid="stAppViewContainer"] .main div[data-testid="stRadio"] {
            pointer-events: auto !important;
          }
          [data-testid="stAppViewContainer"] .main div[data-testid="stRadio"] label {
            color: var(--ps-text) !important;
            cursor: pointer !important;
            font-weight: 600 !important;
            padding-right: 1.25rem !important;
          }
          [data-testid="stAppViewContainer"] .main div[data-testid="stRadio"] [role="radiogroup"] {
            gap: 1.5rem !important;
          }
          .block-container {
            padding-top: 1.25rem;
            padding-bottom: 1rem;
            max-width: 1400px;
          }
          h1, h2, h3 {
            color: var(--ps-text);
            letter-spacing: -0.02em;
          }
          div[data-testid="stMetric"] {
            background: var(--ps-card);
            border: 1px solid var(--ps-border);
            border-radius: 10px;
            padding: 0.65rem 0.85rem;
            box-shadow: 0 1px 2px rgba(15, 23, 42, 0.04);
          }
          div[data-testid="stMetric"] label {
            color: var(--ps-muted) !important;
            font-size: 0.72rem !important;
            text-transform: uppercase;
            letter-spacing: 0.06em;
          }
          div[data-testid="stMetric"] [data-testid="stMetricValue"] {
            color: var(--ps-text) !important;
            font-weight: 700 !important;
          }
          .ps-brand-header {
            background: var(--ps-card);
            border: 1px solid var(--ps-border);
            border-radius: 12px;
            padding: 1rem 1.25rem;
            margin-bottom: 0.75rem;
            box-shadow: 0 4px 14px rgba(15, 23, 42, 0.06);
          }
          .ps-brand-title {
            font-size: 1.45rem;
            font-weight: 700;
            color: var(--ps-text);
            margin: 0;
            line-height: 1.2;
          }
          .ps-brand-sub {
            color: var(--ps-muted);
            font-size: 0.88rem;
            margin-top: 0.35rem;
          }
          .ps-kpi-shelf {
            margin-bottom: 0.5rem;
          }
          .ps-product-card {
            background: var(--ps-card);
            border: 1px solid var(--ps-border);
            border-radius: 12px;
            padding: 0.85rem 0.95rem 0.75rem;
            margin-bottom: 0.65rem;
            box-shadow: 0 6px 18px rgba(15, 23, 42, 0.06);
            min-height: 168px;
          }
          .ps-product-name {
            font-size: 0.95rem;
            font-weight: 700;
            color: var(--ps-text);
            margin: 0 0 0.25rem 0;
          }
          .ps-product-price {
            font-size: 1.05rem;
            font-weight: 700;
            color: var(--ps-accent);
            margin: 0.15rem 0 0.35rem 0;
          }
          .ps-product-meta {
            font-size: 0.78rem;
            color: var(--ps-muted);
            margin-bottom: 0.45rem;
          }
          .ps-badge {
            display: inline-block;
            font-size: 0.68rem;
            font-weight: 600;
            padding: 0.2rem 0.45rem;
            border-radius: 999px;
            margin-right: 0.35rem;
            margin-bottom: 0.35rem;
          }
          .ps-badge-zero {
            background: #EFF6FF;
            color: #1D4ED8;
            border: 1px solid #BFDBFE;
          }
          .ps-badge-behavior {
            background: #F0FDFA;
            color: #0F766E;
            border: 1px solid #99F6E4;
          }
          .ps-badge-hybrid {
            background: #F8FAFC;
            color: #475569;
            border: 1px solid #CBD5E1;
          }
          .ps-reason {
            font-size: 0.72rem;
            color: #475569;
            line-height: 1.35;
            margin-top: 0.35rem;
          }
          [data-testid="stTabs"] [data-baseweb="tab-list"] {
            gap: 0.25rem;
          }
          [data-testid="stTabs"] button[data-baseweb="tab"] {
            background: var(--ps-card);
            border-radius: 8px 8px 0 0;
            border: 1px solid var(--ps-border);
            color: var(--ps-muted);
            font-weight: 600;
          }
          [data-testid="stTabs"] button[aria-selected="true"] {
            color: var(--ps-accent) !important;
            border-bottom-color: var(--ps-card) !important;
          }
          .stButton > button {
            border-radius: 8px;
            font-weight: 600;
            border: 1px solid var(--ps-border);
          }
          .stButton > button[kind="primary"],
          .stButton > button:hover {
            border-color: var(--ps-accent);
            color: var(--ps-accent);
          }
        </style>
        """,
        unsafe_allow_html=True,
    )


def render_brand_header() -> None:
    st.markdown(
        f"""
        <div class="ps-brand-header">
          <p class="ps-brand-title">{APP_NAME} // Real-Time Orchestration Engine</p>
          <p class="ps-brand-sub">Enterprise MarTech command surface for consent-aware personalization,
          propensity orchestration, and retail decision transparency.</p>
        </div>
        """,
        unsafe_allow_html=True,
    )


def compute_command_center_kpis(session_state) -> dict[str, str]:
    interactions = session_state.get("interactions", {})
    session_views = int(sum(interactions.get("views", {}).values()))
    session_clicks = int(sum(interactions.get("clicks", {}).values()))
    users_df = session_state.get("users")
    member_count = len(users_df) if users_df is not None else 100

    active_sessions = member_count * 12 + session_views * 9 + session_clicks * 14 + 318

    propensity_logs = session_state.get("propensity_logs", [])
    intent_triggers = sum(
        1 for log in propensity_logs if log.get("propensity_score", 0) >= PROPENSITY_THRESHOLD
    )
    intent_triggers += session_clicks + max(0, session_views - 1)

    ranked_df = session_state.get("ranked_df")
    if ranked_df is not None and not ranked_df.empty:
        lift = ranked_df["final_score"].head(10).mean() * 22.5
        personalization_lift = f"+{lift:.1f}% vs Baseline"
    else:
        personalization_lift = "+18.4% vs Baseline"

    queue = session_state.get("notification_queue", [])
    churn = 0.42 + min(0.18, len(queue) * 0.03) - min(0.12, session_clicks * 0.02)
    churn_rate = f"{max(0.18, churn):.2f}%"

    return {
        "active_sessions": f"{active_sessions:,}",
        "personalization_lift": personalization_lift,
        "intent_triggers": f"{intent_triggers:,}",
        "churn_rate": churn_rate,
    }


def _variant_label(value: str) -> str:
    if "Behavioral" in value and "Hybrid" not in value:
        return "Variant A — Behavioral Only"
    return "Variant B — Hybrid Model"


def render_variant_radio_panel() -> str:
    """Full-width horizontal radio — main panel only (sidebar CSS cannot block clicks)."""
    from martech_engine import REC_VARIANT_BEHAVIORAL, REC_VARIANT_HYBRID

    options = [REC_VARIANT_BEHAVIORAL, REC_VARIANT_HYBRID]
    if "rec_variant" not in st.session_state or st.session_state["rec_variant"] not in options:
        st.session_state["rec_variant"] = REC_VARIANT_HYBRID

    st.markdown(
        """
        <div class="ps-variant-panel">
          <h4>Recommendation Variant (A/B Model)</h4>
        </div>
        """,
        unsafe_allow_html=True,
    )
    return st.radio(
        "Recommendation Variant",
        options=options,
        format_func=_variant_label,
        key="rec_variant",
        horizontal=True,
        help="Variant A: session behavioral ranking. Variant B: hybrid 0-party + behavioral blend.",
        label_visibility="collapsed",
    )


def render_command_control_bar() -> None:
    render_variant_radio_panel()
    bar = st.columns([3, 3, 6])
    with bar[0]:
        st.caption("Active engine")
        st.markdown(f"**{_variant_label(st.session_state.get('rec_variant', ''))}**")
    with bar[1]:
        interactions = st.session_state.get("interactions", {})
        st.caption("Session signals")
        st.write(
            f"{sum(interactions.get('views', {}).values())} views · "
            f"{sum(interactions.get('clicks', {}).values())} clicks"
        )
    with bar[2]:
        st.caption("How to use")
        st.write("Select a variant above, run simulation in **Member & Strategy**, then open **Recommendations**.")


def render_kpi_shelf(session_state) -> None:
    kpis = compute_command_center_kpis(session_state)
    cols = st.columns(4)
    cols[0].metric("Active Sessions", kpis["active_sessions"], delta="Live sim")
    cols[1].metric("Personalization Lift", kpis["personalization_lift"], delta="Hybrid engine")
    cols[2].metric("Intent Triggers Fired", kpis["intent_triggers"], delta="High propensity")
    cols[3].metric("Notification Churn Rate", kpis["churn_rate"], delta="-0.06% WoW", delta_color="inverse")


def _product_badges_html(product_row, user, rec_variant: str) -> str:
    badges = []
    if product_row.get("interest_score", 0) >= 1.0:
        badges.append('<span class="ps-badge ps-badge-zero">🎯 0-Party Match</span>')
    if product_row.get("browser_score", 0) > 0:
        badges.append('<span class="ps-badge ps-badge-zero">🍪 Intent Signal</span>')
    behavioral = product_row.get("behavioral_score")
    if behavioral is None and user is not None:
        behavioral = behavioral_affinity_score(
            product_row,
            st.session_state.get("interactions", {}),
            user,
        )
    if behavioral and behavioral >= 0.2:
        badges.append('<span class="ps-badge ps-badge-behavior">⚡ Behavioral Boost</span>')
    if rec_variant == REC_VARIANT_HYBRID:
        badges.append('<span class="ps-badge ps-badge-hybrid">◆ Hybrid Rank</span>')
    if not badges:
        badges.append('<span class="ps-badge ps-badge-hybrid">◎ Catalog Discovery</span>')
    return "".join(badges)


def render_product_card(
    product_row,
    user,
    rec_variant: str,
    interactions,
    on_view,
    on_click,
) -> None:
    sku = product_row.get("sku", "—")
    badges = _product_badges_html(product_row, user, rec_variant)
    reason = build_dynamic_reason(user, product_row, rec_variant, interactions)
    st.markdown(
        f"""
        <div class="ps-product-card">
          {badges}
          <p class="ps-product-name">{product_row['name']}</p>
          <p class="ps-product-price">${product_row['price']:.2f}</p>
          <p class="ps-product-meta">{sku} · {product_row['category']} · Score {product_row['final_score']:.3f}</p>
          <p class="ps-reason">{reason}</p>
        </div>
        """,
        unsafe_allow_html=True,
    )
    action_cols = st.columns(2)
    with action_cols[0]:
        st.button(
            "View",
            key=f"view_{product_row['product_id']}",
            on_click=on_view,
            args=(int(product_row["product_id"]), product_row["category"]),
        )
    with action_cols[1]:
        st.button(
            "Click",
            key=f"click_{product_row['product_id']}",
            on_click=on_click,
            args=(int(product_row["product_id"]), product_row["category"]),
        )


def render_product_grid(
    ranked_df: pd.DataFrame,
    user,
    rec_variant: str,
    interactions,
    on_view,
    on_click,
    max_cards: int = 8,
    per_row: int = 4,
) -> None:
    grid_df = ranked_df.head(max_cards)
    rows = [grid_df.iloc[i : i + per_row] for i in range(0, len(grid_df), per_row)]
    for row_df in rows:
        cols = st.columns(per_row)
        for col_index, (_, product_row) in enumerate(row_df.iterrows()):
            with cols[col_index]:
                render_product_card(
                    product_row,
                    user,
                    rec_variant,
                    interactions,
                    on_view,
                    on_click,
                )


def _propensity_breakdown_table(user, interactions, top_product) -> str:
    first_party = get_mock_1st_party_data(user.get("user_id", 0))
    score = compute_propensity_score(user, interactions, top_product)

    rows = [
        ("Base model prior", "0.220", "Lifecycle + channel priors"),
        ("Marketing consent", "+0.100" if user.get("consent_marketing") else "+0.000", "consent_marketing gate"),
        ("Email opt-in", "+0.060" if user.get("email_opt_in") else "+0.000", "email_opt_in"),
        ("Session clicks", f"+{min(0.22, sum(interactions.get('clicks', {}).values()) * 0.09):.3f}", "Real-time loop"),
        ("Session views", f"+{min(0.10, sum(interactions.get('views', {}).values()) * 0.03):.3f}", "Real-time loop"),
        ("Email opens (30d)", f"+{min(0.12, first_party['email_engagement'].get('opens_30d', 0) * 0.01):.3f}", "1st-party CRM"),
        ("Email clicks (30d)", f"+{min(0.10, first_party['email_engagement'].get('clicks_30d', 0) * 0.04):.3f}", "1st-party CRM"),
        ("Purchase recency", f"+{min(0.18, sum(0.06 for p in first_party.get('prior_purchases', []) if p['days_ago'] <= 45)):.3f}", "Registry purchases"),
        ("Category dwell", f"+{min(0.12, sum(d['page_views'] for d in first_party.get('high_dwell_categories', [])) * 0.008):.3f}", "PDP engagement"),
        ("Top-product affinity", "+0.140" if top_product is not None and top_product.get("category") in user.get("interests", []) else "+0.000", "0-party interests"),
        ("Replenishment signal", "+0.100" if first_party.get("replenishment_due_skus") else "+0.000", "Footwear replenishment"),
        ("**Final propensity**", f"**{score:.3f}**", f"Threshold {PROPENSITY_THRESHOLD}"),
    ]
    lines = ["| Component | Weight | Source |", "|---|---:|---|"]
    lines.extend(f"| {name} | {weight} | {source} |" for name, weight, source in rows)
    return "\n".join(lines)


def render_engine_telemetry(session_state) -> None:
    user = session_state.get("user")
    config = session_state.get("config", {})
    interactions = session_state.get("interactions", {})
    ranked_df = session_state.get("ranked_df")
    top_product = ranked_df.iloc[0].to_dict() if ranked_df is not None and not ranked_df.empty else None

    with st.expander("🛠️ System Telemetry & Behavioral Scoring Matrices", expanded=False):
        st.markdown("#### Orchestration snapshot")
        tel_cols = st.columns(4)
        kpis = compute_command_center_kpis(session_state)
        tel_cols[0].write(f"**Active sessions:** {kpis['active_sessions']}")
        tel_cols[1].write(f"**Variant:** {st.session_state.get('rec_variant', '—')}")
        tel_cols[2].write(f"**Privacy mode:** {config.get('privacy_mode', '—')}")
        tel_cols[3].write(f"**Timestamp:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

        if user:
            first_party = get_mock_1st_party_data(user.get("user_id", 0))
            browser_tags = [
                user.get("browser_signal"),
                *user.get("interests", []),
                *first_party.get("affinity_tags", [])[:6],
            ]
            st.markdown("#### Cookie / browser tags detected")
            st.markdown(
                "| Tag | Class | Confidence |",
                help=None,
            )
            tag_rows = []
            for tag in dict.fromkeys(t for t in browser_tags if t):
                tag_class = "Intent" if tag == user.get("browser_signal") else "Affinity"
                confidence = "0.91" if tag_class == "Intent" else "0.74"
                tag_rows.append(f"| `{tag}` | {tag_class} | {confidence} |")
            st.markdown("\n".join(["| Tag | Class | Confidence |", "|---|---|---:|", *tag_rows]))

            st.markdown("#### Propensity score decomposition (current session)")
            st.markdown(_propensity_breakdown_table(user, interactions, top_product))

            if top_product:
                st.markdown("#### Top-ranked SKU context")
                st.markdown(
                    f"| Field | Value |\n|---|---|\n"
                    f"| SKU | `{top_product.get('sku', '—')}` |\n"
                    f"| Category | {top_product.get('category')} |\n"
                    f"| Final score | {top_product.get('final_score', 0):.4f} |\n"
                    f"| Behavioral score | {top_product.get('behavioral_score', 'n/a')} |"
                )

        st.markdown("#### Session state (engine memory)")
        telemetry_state = {
            "interactions": interactions,
            "propensity_logs": session_state.get("propensity_logs", []),
            "notification_queue": session_state.get("notification_queue", []),
            "gold_profile": session_state.get("gold_profile"),
            "config": config,
        }
        st.json(telemetry_state)

        st.markdown("#### Raw session export")
        st.code(json.dumps(telemetry_state, indent=2, default=str), language="json")
