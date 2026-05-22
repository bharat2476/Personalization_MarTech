"""Product Guide tab — Non Tech Persona content for in-app onboarding."""

import streamlit as st

from personascale_ui import APP_NAME


def render_product_guide_tab() -> None:
    st.header("Product Guide")
    st.caption(f"What {APP_NAME} does — explained without technical jargon.")

    st.info(
        f"**{APP_NAME} — explained simply**  \n"
        "This demo was built for a business crisis: **retention was falling** and "
        "**average spend per digital order** was dropping. After **data science, sales, "
        "and marketing** reviewed the data together, the company chose to invest in "
        "**real-time hyper-personalization**, **agentic RAG**, a **vector product catalog**, "
        "**Gemini-class AI**, and **smart push notifications** — not more blanket ads."
    )

    st.subheader("Why this product was built")
    st.markdown(
        """
        | | |
        |---|---|
        | **Situation** | Consumer **retention** down; **average ticket** per digital purchase down. |
        | **Task** | Cross-functional teams analyzed browse, purchase, and campaign data. |
        | **Decision** | Ship a **next-purchase recommendation engine** + **vector search** + **agentic RAG** + **propensity-gated push**. |
        | **Goal** | Bring shoppers back, grow basket size, message only when intent is high. |
        """
    )

    st.subheader("What is the objective?")
    st.markdown(
        "**Main goal:** Reverse retention and average-order declines by predicting **what "
        "each member will buy next**, surfacing it on-site in real time, and sending **push "
        "notifications** for those items only when rules and propensity allow."
    )
    st.markdown("The product tries to answer three questions for every shopper:")
    st.markdown(
        """
        1. **What should we show them?** — Which products belong in their “Recommended for you” section?
        2. **Why are we showing it?** — Can we explain it clearly?
        3. **Should we email or push-notify them?** — Or should we stay quiet?
        """
    )

    outcome_cols = st.columns(4)
    outcomes = [
        ("Retention", "Relevant next-purchase paths"),
        ("Average ticket", "Cross-sell & replenishment"),
        ("Push ROI", "Notify only when propensity > 0.75"),
        ("Team alignment", "DS + sales + marketing one demo"),
    ]
    for col, (title, detail) in zip(outcome_cols, outcomes):
        with col:
            st.metric(title, detail)

    st.subheader("What the solution includes")
    st.markdown(
        """
        | Piece | Business value |
        |-------|----------------|
        | **Real-time recommendations** | Hyper-personal shelf; updates as the shopper clicks |
        | **Next-purchase prediction** | Surfaces what they are likely to buy next, not random trending items |
        | **Vector database** | Semantic product search (“hydration for marathon”) via Supabase + pgvector |
        | **Agentic RAG (GenAI tab)** | Marketer asks in English; AI checks profile, rules, catalog, then queues push |
        | **Gemini / GenAI** | Cost-efficient orchestration layer in the demo (optional full LLM mode) |
        | **Propensity-gated push** | Mobile alert only when score is high enough and shoe/email caps allow |
        """
    )

    st.subheader("What business problem does it simulate?")
    st.markdown(
        "A **sports retail marketplace** with **500 products** and **100 sample members** — "
        "the same pattern used when retention and AOV were diagnosed."
    )
    st.markdown(
        """
        The app shows how a company would:

        - Personalize what each person sees in **real time**
        - **Predict the next purchase** and rank the shelf accordingly
        - Send **push notifications** for those high-intent items
        - Test Variant A vs B before a full rollout
        - Let marketing run **agentic RAG** plays without writing SQL
        """
    )

    st.subheader("The workflow — step by step")
    st.code(
        "Pick a customer  →  See personalized products  →  Decide on marketing  →  Measure results",
        language=None,
    )

    with st.expander("Step 1: Choose your customer — **Member & Strategy** tab", expanded=True):
        st.markdown(
            """
            **What you do:** Pick a type of shopper — e.g. a “High-Value Runner,” a new customer,
            someone who shares a lot of data vs. someone who shares very little.

            **What it represents:** Every customer has a profile: what they told you they like,
            what they bought before, whether they opted into emails, and so on.

            **Why it matters:** You can’t personalize for “everyone.” You start with *one person’s* situation.
            """
        )

    with st.expander("Step 2: Show personalized products — **Recommendations** tab"):
        st.markdown(
            """
            **What you do:** Browse the product grid. Click **View** or **Click** on items.
            The list reorders as you interact.

            **What it represents:** Like Netflix suggesting shows based on what you watched —
            the site adjusts what it shows based on current browsing.
            """
        )
        st.markdown("**Two ways to rank products:**")
        st.table(
            {
                "": ["Simple idea", "Example"],
                "Variant A": [
                    "What are you doing *right now*?",
                    "You clicked 3 hydration vests → show more hydration gear",
                ],
                "Variant B (default)": [
                    "Who are you *plus* what are you doing now?",
                    "Marathon runner + clicked vests → running + hydration mix",
                ],
            }
        )
        st.caption('Each product can show **“Why am I seeing this?”** so the system isn’t a black box.')

    with st.expander("Step 3: Marketing decisions — **Marketing & Ads** tab"):
        st.markdown(
            """
            **What you do:** See whether this customer should get an email or push notification — or nothing.

            **Real-world rules the demo simulates:**

            - They bought shoes 2 weeks ago → don’t push shoe ads yet
            - They’ve had 3 emails this week → stop, we’re at the limit
            - They didn’t consent to marketing → don’t contact them

            **Propensity score (0 to 1):** A “readiness to message” score. Only above **0.75**
            does the system queue a push. Otherwise it **suppresses** on purpose.
            """
        )

    with st.expander("Step 4: Measure and experiment — **Portfolio Metrics** & **A/B Testing Lab** tabs"):
        st.markdown(
            """
            - **Portfolio Metrics** — executive view: clicks, conversions, return on ad spend
            - **A/B Testing Lab** — compare Variant A vs B before rolling out to millions of users

            Like testing two email subject lines, but for the whole recommendation experience.
            """
        )

    with st.expander("Step 5: Trust & architecture — **Trust & Safety** & **Architecture Diagram** tabs"):
        st.markdown(
            "Privacy principles and how data flows from the website → decision engine → "
            "marketing message. Useful for stakeholders and roadmap conversations."
        )

    with st.expander("Step 6: AI marketing assistant — **GenAI Agent Studio** tab"):
        st.markdown(
            """
            **What you do:** Type in plain English, e.g.:

            > This customer looked at shoes 3 times but bought shoes 2 weeks ago.
            > Suggest hydration gear, not shoes.

            **What it represents:** A marketing employee asks an AI assistant to:

            1. Look up the customer profile
            2. Check the rules (can we contact them? are shoe promos blocked?)
            3. Search the product catalog for good matches
            4. Decide whether to send a notification

            **Built-in demo example:** Customer `USER_7721` — a serious runner who recently bought shoes.
            The system should **not** push more shoes; it should suggest a hydration vest instead.
            """
        )

    st.subheader("The big picture")
    st.code(
        """Retention & AOV down → DS + sales + marketing analyze data
        ↓
Build vector catalog + agentic RAG + real-time recommender + Gemini AI
        ↓
Shopper browses → signals collected (profile, clicks, purchases)
        ↓
Predict next purchase → personalized product shelf
        ↓
Propensity: send push for that item?
        ↓
Yes + rules OK → hyper-personalized push
No → suppress
        ↓
Measure retention, basket size, A/B tests""",
        language=None,
    )

    st.subheader("What this product is — and is not")
    is_cols, is_not_cols = st.columns(2)
    with is_cols:
        st.markdown(
            """
            **It is**

            - A **demo / simulator**
            - A **portfolio piece** to show product thinking
            - **Fake data** (500 products, 100 members)
            - Shows **how decisions would be made**
            """
        )
    with is_not_cols:
        st.markdown(
            """
            **It is not**

            - A live production store
            - Software you install for your own shop tomorrow
            - Real customer databases
            - A finished Amazon-scale system
            """
        )

    st.success(
        f"**One-sentence summary:** {APP_NAME} demonstrates how a marketplace fought "
        "falling retention and average ticket with agentic RAG, vector search, real-time "
        "next-purchase recommendations, and propensity-gated push — while respecting "
        "privacy and business rules."
    )

    st.subheader("Try it now (5-minute path)")
    st.markdown(
        """
        1. Open **Member & Strategy** → pick a member → **Run Simulation**
        2. Open **Recommendations** → click **View** / **Click** on a few products
        3. Open **Marketing & Ads** → check push/email rules
        4. Open **GenAI Agent Studio** → try the sample prompt for `USER_7721`
        """
    )
    st.caption(
        "For setup, architecture, and code details, see **README.md** in the repo (Tech Persona section)."
    )
