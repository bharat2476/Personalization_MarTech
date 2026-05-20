import streamlit as st
import pandas as pd
from pathlib import Path

from data_generator import initialize_marketplace
from seed_data import get_mock_1st_party_data, get_product_registry_df
from ranking import (
    add_recommendation_explanations,
    business_impact,
    lifecycle_strategy,
    martech_email_decision,
    privacy_safe_user,
    ribbon_products,
    simulate_experiment,
    shoe_email_status
)
from martech_engine import (
    REC_VARIANT_BEHAVIORAL,
    REC_VARIANT_HYBRID,
    evaluate_push_notification,
    init_martech_session,
    log_propensity_evaluation,
    process_member_signals,
    rank_products_variant,
    record_interaction,
    reset_martech_session,
)
from auction import run_auction
from metrics import (
    compute_ctr,
    compute_conversion,
    compute_roas,
    compute_seller_diversity,
    compute_small_seller_share
)
from personascale_ui import (
    _variant_label,
    inject_enterprise_css,
    render_brand_header,
    render_command_control_bar,
    render_engine_telemetry,
    render_kpi_shelf,
    render_product_grid,
)
from genai_agent_studio import render_genai_agent_studio_tab
from product_guide import render_product_guide_tab

st.set_page_config(
    page_title="PersonaScale AI | Real-Time Orchestration",
    layout="wide",
    initial_sidebar_state="expanded",
)

inject_enterprise_css()
init_martech_session(st.session_state)


def _on_product_view(product_id, category):
    record_interaction(st.session_state, product_id, category, "view")


def _on_product_click(product_id, category):
    record_interaction(st.session_state, product_id, category, "click")


with st.sidebar:
    st.markdown("### PersonaScale AI")
    st.caption("Orchestration control plane")
    st.subheader("Experiment Controls")
    active_variant = st.session_state.get("rec_variant", REC_VARIANT_HYBRID)
    st.markdown(f"**Active variant:** {_variant_label(active_variant)}")
    st.caption("Use the **horizontal radio buttons** in the main panel (below KPI metrics).")
    st.caption("Ranking updates instantly when you view or click products in Recommendations.")
    with st.expander("MarTech Backend: Propensity Logs"):
        propensity_logs = st.session_state.get("propensity_logs", [])
        if propensity_logs:
            st.dataframe(pd.DataFrame(propensity_logs), use_container_width=True, hide_index=True)
        else:
            st.caption("No propensity evaluations yet. Open Marketing & Ads after simulating.")

render_brand_header()
render_kpi_shelf(st.session_state)
render_command_control_bar()

# ---------------------------------------------------------
# INITIALIZE DATA ON FIRST LOAD
# ---------------------------------------------------------

if "users" not in st.session_state:
    marketplace = initialize_marketplace()
    st.session_state["users"] = marketplace["users"]
    st.session_state["sellers"] = marketplace["sellers"]
    st.session_state["products"] = marketplace["products"]
    st.session_state["bids"] = marketplace["bids"]
    st.session_state["product_registry"] = get_product_registry_df()

# ---------------------------------------------------------
# TABS
# ---------------------------------------------------------

tab0, tab1, tab2, tab3, tab4, tab5, tab6, tab7, tab8 = st.tabs([
    "Product Guide",
    "Member & Strategy",
    "Recommendations",
    "Marketing & Ads",
    "Portfolio Metrics",
    "A/B Testing Lab",
    "Trust & Safety",
    "Architecture Diagram",
    "GenAI Agent Studio",
])

# ---------------------------------------------------------
# TAB 0 — PRODUCT GUIDE (NON TECH PERSONA)
# ---------------------------------------------------------

with tab0:
    render_product_guide_tab()

# ---------------------------------------------------------
# TAB 1 — SIMULATION CONFIG
# ---------------------------------------------------------

with tab1:
    st.header("Member & Strategy Configuration")
    users_df = st.session_state["users"]
    products_df = st.session_state["products"]

    metric_cols = st.columns(4)
    metric_cols[0].metric("Demo Products", f"{len(products_df):,}")
    metric_cols[1].metric("Demo Members", f"{len(users_df):,}")
    metric_cols[2].metric("Repeat Customers", int((users_df["customer_type"] == "Repeat").sum()))
    metric_cols[3].metric("New Customers", int((users_df["customer_type"] == "New").sum()))

    st.write(
        "This simulator combines behavioral signals, browser intent, app signals, "
        "customer lifecycle, and merchandising goals into one recommendation platform."
    )
    st.caption(
        "Selection criteria include member segment, customer type, gender, and privacy sharing preference."
    )

    user_segment = st.selectbox("Select Member Segment", sorted(users_df["segment"].unique()))
    customer_type = st.selectbox("Customer Type", ["All", "Repeat", "New"])
    gender = st.selectbox("Member Gender", ["All", "Men", "Women"])
    candidate_users = users_df[users_df["segment"] == user_segment]
    if customer_type != "All":
        candidate_users = candidate_users[candidate_users["customer_type"] == customer_type]
    if gender != "All":
        candidate_users = candidate_users[candidate_users["gender"] == gender]
    if candidate_users.empty:
        st.warning("No member matches this combination. Broaden the filters.")
        st.stop()

    selected_user_id = st.selectbox(
        "Demo Member",
        candidate_users["user_id"].tolist(),
        format_func=lambda user_id: (
            f"{candidate_users[candidate_users['user_id'] == user_id].iloc[0]['customer_name']} "
            f"({candidate_users[candidate_users['user_id'] == user_id].iloc[0]['customer_type']}, "
            f"{candidate_users[candidate_users['user_id'] == user_id].iloc[0]['gender']})"
        )
    )
    selected_user = users_df[users_df["user_id"] == selected_user_id].iloc[0].to_dict()

    roas_fairness = st.slider(
        "ROAS vs Diversity Optimization",
        0, 100, 50
    )

    explore_exploit = st.slider(
        "Explore vs Exploit",
        0, 100, 50
    )

    audience_filter = st.selectbox("Merchandising Audience Dropdown", ["All", "Men", "Women", "Kids"])
    product_type_filter = st.selectbox("Product Dropdown", ["All", "Footwear", "Apparel", "Accessories"])
    privacy_mode = st.radio(
        "Privacy Preference (how much user wants to share)",
        ["Full consent", "Limited consent", "No app usage data"],
        horizontal=True,
        help="Controls which signals are allowed to influence personalization."
    )
    enforce_diversity = st.checkbox("Enforce Channel Diversity Guardrail", value=True)

    st.subheader("Signals Available")
    st.json({
        "lifecycle_stage": selected_user["lifecycle_stage"],
        "behavioral_interests": selected_user["interests"],
        "browser_signal": selected_user["browser_signal"],
        "app_signals": selected_user["app_signals"],
        "run_frequency_per_week": selected_user["run_frequency_per_week"],
        "estimated_monthly_miles": selected_user["estimated_monthly_miles"],
        "last_shoe_purchase_days_ago": selected_user["last_shoe_purchase_days_ago"],
        "email_opt_in": selected_user["email_opt_in"],
        "marketing_consent": selected_user["consent_marketing"],
        "app_usage_consent": selected_user["consent_app_usage"],
        "weekly_email_frequency": (
            f"{selected_user['emails_sent_last_7_days']} / "
            f"{selected_user['email_frequency_cap_per_week']}"
        ),
        "affinity_tags": selected_user.get("affinity_tags", []),
    })

    with st.expander("1st-party historical events (seed_data registry)", expanded=False):
        st.json(get_mock_1st_party_data(selected_user_id))

    with st.expander("Product registry sample (canonical SKUs)", expanded=False):
        st.dataframe(
            st.session_state["product_registry"].head(12)[
                ["sku", "name", "category", "price", "margin", "behavioral_tags"]
            ],
            use_container_width=True,
        )

    if st.button("Run Simulation"):
        reset_martech_session(st.session_state)
        gold_profile, personalized_user = process_member_signals(
            selected_user,
            st.session_state["interactions"],
            privacy_mode,
            privacy_safe_user,
        )
        st.session_state["user"] = personalized_user
        st.session_state["raw_user"] = selected_user
        st.session_state["gold_profile"] = gold_profile
        st.session_state["config"] = {
            "user_segment": user_segment,
            "roas_fairness": roas_fairness,
            "explore_exploit": explore_exploit,
            "audience_filter": audience_filter,
            "product_type_filter": product_type_filter,
            "privacy_mode": privacy_mode,
            "enforce_diversity": enforce_diversity,
            "rec_variant": st.session_state.get("rec_variant", REC_VARIANT_HYBRID),
            "seed": selected_user_id + explore_exploit
        }

        st.success("Simulation saved. Open Recommendations, Marketing & Ads, and Portfolio Metrics.")

# ---------------------------------------------------------
# TAB 2 — PERSONALIZED RESULTS
# ---------------------------------------------------------

with tab2:
    st.header("Personalized Recommendations")
    st.info(
        f"Ranking model: **{_variant_label(st.session_state.get('rec_variant', REC_VARIANT_HYBRID))}** "
        "— change via the radio buttons below the KPI row on the home view."
    )

    if "config" not in st.session_state:
        st.info("Configure the member strategy first in Tab 1.")
    else:
        user = st.session_state["user"]
        config = st.session_state["config"]
        products_df = st.session_state["products"]
        rec_variant = st.session_state.get("rec_variant", config.get("rec_variant", REC_VARIANT_HYBRID))
        interactions = st.session_state["interactions"]

        ranked_df = rank_products_variant(
            user,
            products_df,
            config,
            interactions,
            rec_variant,
        )
        filtered_ranked_df = ranked_df.copy()
        if config["audience_filter"] != "All":
            filtered_ranked_df = filtered_ranked_df[filtered_ranked_df["audience"] == config["audience_filter"]]
        if config["product_type_filter"] != "All":
            filtered_ranked_df = filtered_ranked_df[filtered_ranked_df["product_type"] == config["product_type_filter"]]

        catalog_lookup = products_df.set_index("product_id")
        for col in ("sku", "behavioral_tags", "margin"):
            if col in products_df.columns:
                filtered_ranked_df[col] = filtered_ranked_df["product_id"].map(catalog_lookup[col])

        st.subheader(
            f"{user['customer_name']} | {user['segment']} | "
            f"{user['customer_type']} | {user['lifecycle_stage']}"
        )
        st.write(
            f"Privacy mode: {config['privacy_mode']} | Interests: {user['interests']} | "
            f"Browser: {user['browser_signal']} | Apps: {user['app_signals']}"
        )
        st.caption(
            f"Active variant: **{rec_variant}** | "
            f"Session views: {sum(interactions.get('views', {}).values())} | "
            f"Session clicks: {sum(interactions.get('clicks', {}).values())}"
        )
        if st.session_state.get("gold_profile"):
            with st.expander("Semantic profile (Bronze → Silver → Gold)", expanded=False):
                st.json(st.session_state["gold_profile"])
        st.info(lifecycle_strategy(user))

        ribbon_cols = st.columns(2)
        with ribbon_cols[0]:
            st.subheader("Ribbon: Products on Sale")
            st.dataframe(
                ribbon_products(products_df, "Sale", config["audience_filter"], config["product_type_filter"])
                .head(8)[["name", "category", "audience", "product_type", "price", "discount_pct"]],
                use_container_width=True
            )
        with ribbon_cols[1]:
            st.subheader("Ribbon: Trending Products")
            st.dataframe(
                ribbon_products(products_df, "Trending", config["audience_filter"], config["product_type_filter"])
                .head(8)[["name", "category", "audience", "product_type", "price", "trend_score"]],
                use_container_width=True
            )

        filtered_ranked_df = add_recommendation_explanations(filtered_ranked_df, user)

        st.subheader("Retail Recommendation Shelf")
        st.caption("Enterprise product cards · 4-up grid · live View/Click re-ranking")
        render_product_grid(
            filtered_ranked_df,
            user,
            rec_variant,
            interactions,
            _on_product_view,
            _on_product_click,
            max_cards=8,
            per_row=4,
        )

        st.subheader("Recommended Products with Explainability")
        display_cols = [
            "sku", "name", "category", "audience", "product_type", "price",
            "is_on_sale", "discount_pct", "trend_score", "interest_score",
            "browser_score", "app_score", "final_score", "why_recommended",
        ]
        if "behavioral_tags" in filtered_ranked_df.columns:
            display_cols.insert(2, "behavioral_tags")
        st.dataframe(
            filtered_ranked_df.head(20)[[c for c in display_cols if c in filtered_ranked_df.columns]],
            use_container_width=True
        )

        with st.expander("How recommendation scores are calculated", expanded=False):
            st.markdown(
                """
                **Score definitions**

                - `interest_score`: `1.0` if product category is in member interests, else `0.0`.
                - `browser_score`: `1.0` if browser intent matches category, or if browser intent is `Sale` for on-sale items, or `Trending` for high-trend items (trend >= 70); otherwise `0.0`.
                - `trend_score`: base marketplace trend signal from product data; normalized in ranking as `trend_norm = trend_score / max(trend_score)`.
                - `final_score`: weighted blend of personalization + business signals + lifecycle boost + exploration noise.

                **Final score formula (recommendations)**

                `final_score =`
                `interest_score * 0.30 * exploit_weight`
                `+ audience_score * 0.18 * exploit_weight`
                `+ browser_score * 0.15 * exploit_weight`
                `+ app_score * 0.14 * exploit_weight`
                `+ popularity_norm * 0.12 * exploit_weight`
                `+ trend_norm * 0.06 * exploit_weight`
                `+ recency_norm * 0.05 * exploit_weight`
                `+ margin_score * lifecycle_boost`
                `+ trend_norm * discovery_boost`
                `+ lifecycle_score`
                `+ random_exploration(0..explore_weight)`

                where:
                - `explore_weight = explore_exploit / 100`
                - `exploit_weight = 1 - explore_weight`
                - `lifecycle_boost = 0.12` for repeat members, else `0.0`
                - `discovery_boost = 0.12` for new members, else `0.0`
                """
            )
            st.markdown(
                """
                **Signals currently used**

                - Declared member interests
                - Browser intent signal (`category`, `Sale`, `Trending`)
                - App affinity signals (`Run Club App`, `Training App`, `Sneaker Drops App`, `Shopping App`)
                - Audience fit (`Men`, `Women`, `Kids`)
                - Product trend, popularity, and recency
                - Product margin score
                - Lifecycle stage + customer type
                - Privacy preference (limits which signals are available)

                **Suggested additional signals**

                - Inventory and size availability by location
                - Price affinity and discount sensitivity
                - Returns history / fit confidence
                - Session context (time of day, device, channel)
                - Weather and seasonality by geography
                - Brand-newness preference vs replenishment intent
                - Delivery speed / fulfillment promise
                """
            )

        st.session_state["ranked_df"] = filtered_ranked_df

# ---------------------------------------------------------
# TAB 3 — ADS & AUCTION
# ---------------------------------------------------------

with tab3:
    st.header("Marketing & Ads")

    if "config" not in st.session_state:
        st.info("Configure the member strategy first in Tab 1.")
    else:
        user = st.session_state["user"]
        config = st.session_state["config"]
        ranked_df = st.session_state.get("ranked_df")
        top_product = ranked_df.iloc[0] if ranked_df is not None and not ranked_df.empty else None
        interactions = st.session_state["interactions"]
        email_decision = martech_email_decision(user, top_product)
        push_eval = evaluate_push_notification(user, interactions, top_product)
        log_propensity_evaluation(st.session_state, push_eval)

        st.subheader("Lifecycle Email Decision")
        st.info(shoe_email_status(user))
        decision_cols = st.columns(4)
        decision_cols[0].metric("Action", email_decision["action"])
        decision_cols[1].metric("Preferred Channel", email_decision["channel"])
        decision_cols[2].metric("Lifecycle", user["lifecycle_stage"])
        decision_cols[3].metric("Emails This Week", f"{user['emails_sent_last_7_days']} / {user['email_frequency_cap_per_week']}")
        st.write(f"**Subject line:** {email_decision['subject_line']}")
        st.caption(email_decision["privacy_note"])
        st.write(
            "Rule: if the member just bought footwear, suppress shoe emails. "
            "Running shoe emails resume when the member reaches 5.5 months since last shoe purchase."
        )

        st.subheader("Push Notification (Propensity-Gated)")
        push_cols = st.columns(4)
        push_cols[0].metric("Propensity Score", f"{push_eval['score']:.2f}")
        push_cols[1].metric("Threshold", f">{push_eval['threshold']:.2f}")
        push_cols[2].metric("Push Status", "Queued" if push_eval["queued"] else "Suppressed")
        push_cols[3].metric("Queue Size", len(st.session_state.get("notification_queue", [])))
        if push_eval["queued"]:
            st.success(
                f"Queued: {push_eval['notification']['title']} — {push_eval['notification']['body']}"
            )
        else:
            st.warning(
                "Push suppressed: propensity below threshold, lifecycle rule, or channel "
                f"({user.get('channel_preference')}) does not include Push."
            )
        if st.session_state.get("notification_queue"):
            st.dataframe(
                pd.DataFrame(st.session_state["notification_queue"]),
                use_container_width=True,
                hide_index=True,
            )

        auction_df = run_auction(
            user,
            st.session_state["bids"],
            st.session_state["products"],
            st.session_state["sellers"],
            config
        )

        st.subheader("Sponsored Product Auction")
        st.dataframe(auction_df.head(15), use_container_width=True)

        with st.expander("How auction scores are calculated", expanded=False):
            st.markdown(
                """
                **Score definitions**

                - `relevance`: `1.0` if ad product category is in member interests, else `0.2`.
                - `fairness_factor`: `1.25` for small sellers when diversity guardrail is enabled, else `1.0`.
                - `final_score`: blend of bid value (ROAS), user relevance, and fairness.

                **Final score formula (auction)**

                `roas_weight = roas_fairness / 100`
                `fairness_weight = 1 - roas_weight`

                `final_score = (bid_amount * roas_weight) + (relevance * 0.5) + (fairness_factor * fairness_weight)`
                """
            )
            st.markdown(
                """
                **Signals currently used**

                - Bid amount from sellers
                - Member interest-category relevance
                - Seller type (`is_small_seller`)
                - Diversity guardrail toggle (`enforce_diversity`)
                - ROAS vs fairness slider (`roas_fairness`)

                **Suggested additional signals**

                - Predicted click-through and conversion probability
                - Margin-aware value per click/order
                - Ad quality and historical engagement
                - Frequency capping and fatigue at member level
                - Budget pacing and campaign constraints
                - Category-level fairness constraints over time
                - Post-click outcomes (returns, cancellations) for quality weighting
                """
            )

        st.session_state["auction_df"] = auction_df

# ---------------------------------------------------------
# TAB 4 — METRICS DASHBOARD
# ---------------------------------------------------------

with tab4:
    st.header("Portfolio Metrics & Open Pain Points")

    if "auction_df" not in st.session_state:
        st.info("Run the simulation first.")
    else:
        auction_df = st.session_state["auction_df"]
        sellers_df = st.session_state["sellers"]

        # Fake impressions for now (each auction result = 1 impression)
        impressions_df = auction_df[["seller_id", "product_id"]].copy()

        # Fake events (no real clicks yet)
        events_df = pd.DataFrame(columns=["event_type", "product_id"])

        ctr = compute_ctr(events_df)
        conversion = compute_conversion(events_df)
        roas = compute_roas(auction_df, events_df)
        diversity = compute_seller_diversity(impressions_df)
        small_seller_share = compute_small_seller_share(impressions_df, sellers_df)

        st.metric("CTR", ctr)
        st.metric("Conversion Rate", conversion)
        st.metric("ROAS", roas)
        st.metric("Seller Diversity Index", diversity)
        st.metric("Channel Diversity Share", small_seller_share)

        st.write("Impressions by Channel")
        st.bar_chart(impressions_df["seller_id"].value_counts())

    st.subheader("Additional Pain Points to Address")
    st.markdown(
        """
        - Inventory-aware ranking with size availability and local fulfillment promises.
        - Identity stitching across web, retail, app, and engagement platforms.
        - Channel orchestration across email, push, in-app, and paid media.
        - Fairness checks across gender, age groups, and sport communities.
        - Real incrementality measurement with holdout groups and longer-term LTV.
        """
    )

with tab5:
    st.header("A/B Testing Lab")

    if "ranked_df" not in st.session_state:
        st.info("Run the simulation and open Recommendations first.")
    else:
        ranked_df = st.session_state["ranked_df"]
        user = st.session_state["user"]
        config = st.session_state["config"]
        users_df = st.session_state["users"]

        st.subheader("Experiment Definition")
        experiment_cols = st.columns(3)
        with experiment_cols[0]:
            hypothesis = st.text_area(
                "Hypothesis",
                "Lifecycle-aware, consent-filtered recommendations will increase revenue per session without increasing unsubscribes."
            )
            randomization_unit = st.selectbox(
                "Randomization Unit",
                ["Member", "Session", "Household", "Device"],
                index=0
            )
            population = st.multiselect(
                "Eligible Population",
                sorted(users_df["lifecycle_stage"].unique()),
                default=sorted(users_df["lifecycle_stage"].unique())
            )
        with experiment_cols[1]:
            primary_metric = st.selectbox(
                "Primary Success Metric",
                ["Revenue per Session", "Conversion Rate", "CTR", "Incremental Margin"],
                index=0
            )
            minimum_detectable_effect = st.slider(
                "Minimum Detectable Effect",
                1, 25, 8,
                help="Smallest lift worth detecting for this demo experiment."
            )
            confidence_level = st.selectbox("Confidence Level", ["90%", "95%", "99%"], index=1)
        with experiment_cols[2]:
            traffic_allocation = st.slider("Traffic Allocated to Test", 10, 100, 50)
            treatment_split = st.slider("Treatment Split Within Test", 10, 90, 50)
            experiment_days = st.slider("Experiment Duration", 7, 56, 21)

        eligible_users = users_df[users_df["lifecycle_stage"].isin(population)] if population else users_df.iloc[0:0]
        daily_sessions = max(1, len(eligible_users) * 3)
        total_test_sessions = int(daily_sessions * experiment_days * (traffic_allocation / 100))
        treatment_sessions = int(total_test_sessions * (treatment_split / 100))
        control_sessions = total_test_sessions - treatment_sessions

        sizing_cols = st.columns(4)
        sizing_cols[0].metric("Eligible Members", f"{len(eligible_users):,}")
        sizing_cols[1].metric("Estimated Test Sessions", f"{total_test_sessions:,}")
        sizing_cols[2].metric("Control Sessions", f"{control_sessions:,}")
        sizing_cols[3].metric("Treatment Sessions", f"{treatment_sessions:,}")

        st.subheader("Variant Design")
        variants_df = pd.DataFrame([
            {
                "variant": "A: Control",
                "ranking_logic": "Popularity, trend, and sale ribbons",
                "signals_allowed": "Contextual catalog signals",
                "martech_rule": "Standard shoe replenishment suppression",
                "traffic_share": f"{100 - treatment_split}%"
            },
            {
                "variant": "B: Treatment",
                "ranking_logic": "Lifecycle-aware ranking with consent filter",
                "signals_allowed": config["privacy_mode"],
                "martech_rule": "Frequency cap + replenishment + channel preference",
                "traffic_share": f"{treatment_split}%"
            },
        ])
        st.dataframe(variants_df, use_container_width=True)

        st.subheader("Metrics and Guardrails")
        metrics_df = pd.DataFrame([
            {"metric_type": "Primary", "metric": primary_metric, "decision_rule": f"Win if lift >= {minimum_detectable_effect}% at {confidence_level} confidence"},
            {"metric_type": "Secondary", "metric": "CTR", "decision_rule": "Should improve or remain neutral"},
            {"metric_type": "Secondary", "metric": "Conversion Rate", "decision_rule": "Should improve or remain neutral"},
            {"metric_type": "Guardrail", "metric": "Unsubscribe Rate", "decision_rule": "Must not increase by more than 0.2 percentage points"},
            {"metric_type": "Guardrail", "metric": "Email Frequency Cap", "decision_rule": "Must respect each member cap"},
            {"metric_type": "Guardrail", "metric": "Privacy Consent Coverage", "decision_rule": "Must use only consented or contextual signals"},
        ])
        st.dataframe(metrics_df, use_container_width=True)

        experiment_df = simulate_experiment(ranked_df, user)
        impact = business_impact(experiment_df, len(eligible_users))
        st.subheader("Simulated Result Readout")
        st.dataframe(experiment_df, use_container_width=True)

        impact_cols = st.columns(len(impact))
        for index, (label, value) in enumerate(impact.items()):
            impact_cols[index].metric(label, value)

        st.subheader("Launch Checklist")
        st.markdown(
            f"""
            - Hypothesis documented: {hypothesis}
            - Unit of randomization: {randomization_unit}
            - No overlapping experiments on the same member/session population.
            - Assignment is sticky for the experiment duration.
            - Exposure logging records variant, member/session id, timestamp, and eligible surface.
            - Privacy mode is enforced before ranking and Martech activation.
            - Stop rule: ship treatment only if primary metric wins and guardrails stay healthy.
            """
        )

with tab6:
    st.header("Trust & Safety & Product Architecture")

    st.subheader("Privacy-first personalization controls")
    st.markdown(
        """
        - Synthetic demo users only; no real GPS, health, purchase, or account data.
        - Consent gates app usage, marketing activation, and email eligibility.
        - Limited-consent mode removes app signals and mileage from ranking.
        - No-app mode falls back to contextual and trend-based recommendations.
        - Frequency caps, suppression windows, unsubscribe, and retention limits reduce over-targeting.
        - Recommendation explanations show why each product is ranked.
        """
    )

    st.subheader("Reference architecture")
    st.code(
        "Signals -> Consent Filter -> Feature Scoring -> Recommender -> Auction/Ranking "
        "-> Martech Trigger -> Experiment Metrics",
        language="text"
    )

    st.subheader("Story")
    st.write(
        "This demo positions personalization as a measurable, privacy-aware product system: "
        "it connects member lifecycle, consent, recommendation quality, marketing fatigue, "
        "ad monetization, and executive impact metrics."
    )
    st.subheader("Architecture principles")
    st.markdown(
        """
        - **User trust first:** consent and communication controls gate personalization.
        - **Business + user balance:** ranking and auction optimize outcomes while protecting relevance.
        - **Explainability by default:** recommendations include plain-language rationale.
        - **Experiment-driven iteration:** A/B testing drives rollout decisions with guardrails.
        """
    )

    st.subheader("Key trade-offs")
    st.markdown(
        """
        - **Relevance vs. exploration:** short-term precision versus long-term discovery.
        - **Revenue vs. fairness:** maximizing bid value while protecting marketplace diversity.
        - **Personalization depth vs. privacy:** richer signals versus stricter data minimization.
        - **Velocity vs. risk:** shipping quickly while maintaining measurable guardrails.
        """
    )

with tab7:
    st.header("Architecture Diagram")
    diagram_path = Path(__file__).with_name("architecture diagram.png")
    if diagram_path.exists():
        st.image(str(diagram_path), caption="PersonaScale AI architecture workflow", use_container_width=True)
    else:
        st.warning("Architecture diagram file not found. Expected: architecture diagram.png")

with tab8:
    render_genai_agent_studio_tab(st.session_state)

st.divider()
render_engine_telemetry(st.session_state)
