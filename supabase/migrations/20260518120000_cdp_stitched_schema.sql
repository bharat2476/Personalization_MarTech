-- =============================================================================
-- CDP Stitched Schema Migration (Supabase / PostgreSQL + pgvector)
-- Principal DBA pattern: unify PIM (products), identity (consumers), and
-- real-time telemetry (behavioral_logs) for Agentic RAG + MarTech orchestration.
--
-- EMBEDDING DIMENSION: This migration uses 384 (e.g. sentence-transformers /
-- all-MiniLM-L6-v2). For OpenAI text-embedding-3-small/large, change every
-- vector(384) → vector(1536) and rebuild the HNSW index (see § DIMENSION SWAP).
-- =============================================================================

-- -----------------------------------------------------------------------------
-- 1. pgvector extension (required for description_embedding + match_products)
-- -----------------------------------------------------------------------------
-- Supabase hosts pgvector in the `extensions` schema; objects in `public` still
-- resolve the `vector` type once the extension is enabled.
CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions;

-- Optional: expose vector ops in public search_path for ad-hoc SQL in Studio
-- ALTER DATABASE postgres SET search_path TO public, extensions;


-- -----------------------------------------------------------------------------
-- 2. products — canonical PIM + semantic retrieval column
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.products (
    id                  uuid PRIMARY KEY DEFAULT gen_random_uuid(),

    -- PIM / registry keys
    sku                 text NOT NULL UNIQUE,
    name                text NOT NULL,
    price               numeric(12, 2) NOT NULL CHECK (price >= 0),
    category            text NOT NULL,
    product_type        text,                    -- Footwear | Apparel | Accessories
    audience            text,                    -- Men | Women | Kids
    margin              numeric(5, 4),
    behavioral_tags     text[] DEFAULT '{}',
    description         text,                    -- source text used to build embeddings

    -- Semantic layer: 384-d MiniLM-class models (HuggingFace). Cosine ops below.
    description_embedding extensions.vector(384),

    metadata            jsonb NOT NULL DEFAULT '{}'::jsonb,  -- extensible PIM facets
    is_active           boolean NOT NULL DEFAULT true,
    created_at          timestamptz NOT NULL DEFAULT now(),
    updated_at          timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.products IS
    'Unified product registry (PIM). description_embedding powers sub-ms ANN retrieval for Agentic RAG.';

COMMENT ON COLUMN public.products.description_embedding IS
    'L2-normalized embedding of name + description + behavioral_tags. Dimension must match match_products().';


-- -----------------------------------------------------------------------------
-- 3. consumers — zero-party profile + demographic + marketing guardrails
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.consumers (
    id                          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
    external_id                 text NOT NULL UNIQUE,   -- e.g. USER_7721 (CDP stitch key)

    -- Zero-party (declared) attributes
    segment                     text,                   -- e.g. High-Value Runner
    declared_interests          text[] NOT NULL DEFAULT '{}',  -- Marathon Training, Trail Running
    lifecycle_stage             text,
    browser_intent_signal       text,

    -- Demographics
    gender                      text,
    age_group                   text,
    location_region             text,

    -- Consent & channel
    email_opt_in                boolean NOT NULL DEFAULT false,
    consent_marketing           boolean NOT NULL DEFAULT false,
    consent_app_usage           boolean NOT NULL DEFAULT false,
    channel_preference          text,

    -- Operational MarTech guardrails
    last_shoe_purchase_at       timestamptz,            -- anchor for suppression logic
    shoe_suppression_window     interval NOT NULL DEFAULT interval '14 days',
    max_weekly_touches          smallint NOT NULL DEFAULT 3 CHECK (max_weekly_touches > 0),
    touches_sent_this_week      smallint NOT NULL DEFAULT 0 CHECK (touches_sent_this_week >= 0),

    metadata                    jsonb NOT NULL DEFAULT '{}'::jsonb,
    created_at                  timestamptz NOT NULL DEFAULT now(),
    updated_at                  timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.consumers IS
    'Identity + zero-party attributes + frequency/suppression guardrails for orchestration.';

COMMENT ON COLUMN public.consumers.shoe_suppression_window IS
    'Post-footwear-purchase cooling period; blocks shoe promos while still allowing accessory RAG matches.';

COMMENT ON COLUMN public.consumers.external_id IS
    'Stable cross-system identifier used to stitch behavioral_logs → consumers.';

-- Guardrail evaluator (STABLE: safe to call per-row in RPCs; uses transaction timestamp)
CREATE OR REPLACE FUNCTION public.is_shoe_promotion_suppressed(c public.consumers)
RETURNS boolean
LANGUAGE sql
STABLE
AS $$
    SELECT
        c.last_shoe_purchase_at IS NOT NULL
        AND now() < (c.last_shoe_purchase_at + c.shoe_suppression_window);
$$;


-- -----------------------------------------------------------------------------
-- 4. behavioral_logs — high-throughput clickstream / event telemetry
-- -----------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS public.behavioral_logs (
    id                          bigserial PRIMARY KEY,
    consumer_id                 uuid NOT NULL REFERENCES public.consumers(id) ON DELETE CASCADE,

    event_type                  text NOT NULL CHECK (
                                    event_type IN (
                                        'view', 'click', 'add_to_cart', 'purchase',
                                        'email_open', 'email_click', 'push_sent', 'push_dismiss'
                                    )
                                ),
    target_id                   text NOT NULL,   -- SKU, product uuid, or campaign id
    target_category             text,
    session_id                  text,
    session_propensity_score    numeric(6, 4) CHECK (
                                    session_propensity_score IS NULL
                                    OR (session_propensity_score >= 0 AND session_propensity_score <= 1)
                                ),
    event_metadata              jsonb NOT NULL DEFAULT '{}'::jsonb,
    occurred_at                 timestamptz NOT NULL DEFAULT now()
);

COMMENT ON TABLE public.behavioral_logs IS
    'Append-only behavioral telemetry; partition-ready via occurred_at for warehouse export.';

-- Hot path: "last N events for consumer in session" (personalization loop)
CREATE INDEX IF NOT EXISTS idx_behavioral_logs_consumer_time
    ON public.behavioral_logs (consumer_id, occurred_at DESC);

CREATE INDEX IF NOT EXISTS idx_behavioral_logs_session
    ON public.behavioral_logs (session_id, occurred_at DESC)
    WHERE session_id IS NOT NULL;

-- Agentic feature store: filter by event_type + target for propensity recompute
CREATE INDEX IF NOT EXISTS idx_behavioral_logs_event_target
    ON public.behavioral_logs (event_type, target_id, occurred_at DESC);


-- -----------------------------------------------------------------------------
-- 5. B-tree indexes — metadata pre-filter BEFORE vector scan (critical for RAG)
-- -----------------------------------------------------------------------------
-- PostgreSQL applies these predicates first; the planner shrinks the candidate set
-- passed to the HNSW index, avoiding full-catalog cosine work at query time.
CREATE INDEX IF NOT EXISTS idx_products_category
    ON public.products (category)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_products_price
    ON public.products (price)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_products_category_price
    ON public.products (category, price)
    WHERE is_active = true;

CREATE INDEX IF NOT EXISTS idx_consumers_segment
    ON public.consumers (segment);


-- -----------------------------------------------------------------------------
-- 6. HNSW index — sub-millisecond approximate nearest neighbor (ANN) retrieval
-- -----------------------------------------------------------------------------
-- HNSW (Hierarchical Navigable Small World):
--   • Graph-based ANN: greedy multi-layer search → O(log N) hops vs O(N) brute force
--   • No training phase (unlike IVFFlat); safe for continuous catalog ingest / Agentic RAG
--   • `m` = max edges/node (16): higher → better recall, more RAM
--   • `ef_construction` = build-time beam (64): higher → better index quality, slower build
--
-- `vector_cosine_ops` aligns with `<=>` (cosine distance) in match_products().
-- For inner-product models, switch opclass to vector_ip_ops and normalize embeddings.
--
-- Typical Agentic RAG loop: embed user intent once → single HNSW probe → top-k SKUs
-- in <1–5 ms at 100k–1M rows (hardware dependent).
CREATE INDEX IF NOT EXISTS idx_products_embedding_hnsw_cosine
    ON public.products
    USING hnsw (description_embedding extensions.vector_cosine_ops)
    WITH (m = 16, ef_construction = 64)
    WHERE description_embedding IS NOT NULL AND is_active = true;


-- -----------------------------------------------------------------------------
-- IVFFlat (alternative) — commented; enable for bulk-static catalogs if preferred
-- -----------------------------------------------------------------------------
-- IVFFlat partitions the vector space into `lists` centroids (training via ANALYZE).
-- Pros: smaller index, fast builds on huge static corpora.
-- Cons: requires REINDEX + ANALYZE after major distribution shift; lower recall unless
--       `probes` is tuned per query (SET ivfflat.probes = N).
--
-- CREATE INDEX idx_products_embedding_ivfflat_cosine
--     ON public.products
--     USING ivfflat (description_embedding extensions.vector_cosine_ops)
--     WITH (lists = 100)
--     WHERE description_embedding IS NOT NULL AND is_active = true;
-- -- After bulk load: ANALYZE public.products;


-- -----------------------------------------------------------------------------
-- 7. updated_at maintenance
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.set_updated_at()
RETURNS trigger
LANGUAGE plpgsql
AS $$
BEGIN
    NEW.updated_at := now();
    RETURN NEW;
END;
$$;

DROP TRIGGER IF EXISTS trg_products_updated_at ON public.products;
CREATE TRIGGER trg_products_updated_at
    BEFORE UPDATE ON public.products
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();

DROP TRIGGER IF EXISTS trg_consumers_updated_at ON public.consumers;
CREATE TRIGGER trg_consumers_updated_at
    BEFORE UPDATE ON public.consumers
    FOR EACH ROW EXECUTE FUNCTION public.set_updated_at();


-- -----------------------------------------------------------------------------
-- 8. match_products — Cosine similarity RPC for Supabase / PostgREST
-- -----------------------------------------------------------------------------
-- Distance operator `<=>` = cosine distance when using vector_cosine_ops index.
-- Similarity = 1 - distance (for unit-normalized vectors; clamp in app if needed).
--
-- Query plan (ideal): Bitmap/Index Scan on category/price → HNSW on embedding subset.
CREATE OR REPLACE FUNCTION public.match_products(
    query_embedding         extensions.vector(384),
    match_count             integer DEFAULT 10,
    filter_category         text DEFAULT NULL,
    filter_product_type     text DEFAULT NULL,
    min_price               numeric DEFAULT NULL,
    max_price               numeric DEFAULT NULL,
    exclude_product_types   text[] DEFAULT NULL,   -- e.g. ARRAY['Footwear'] during shoe suppression
    similarity_threshold    double precision DEFAULT NULL,
    active_only             boolean DEFAULT true
)
RETURNS TABLE (
    product_id              uuid,
    sku                     text,
    name                    text,
    category                text,
    product_type            text,
    price                   numeric,
    similarity              double precision
)
LANGUAGE sql
STABLE
PARALLEL SAFE
SET search_path = public, extensions
AS $$
    SELECT
        p.id            AS product_id,
        p.sku,
        p.name,
        p.category,
        p.product_type,
        p.price,
        (1 - (p.description_embedding <=> query_embedding))::double precision AS similarity
    FROM public.products AS p
    WHERE p.description_embedding IS NOT NULL
      AND (NOT active_only OR p.is_active = true)
      AND (filter_category IS NULL OR p.category = filter_category)
      AND (filter_product_type IS NULL OR p.product_type = filter_product_type)
      AND (min_price IS NULL OR p.price >= min_price)
      AND (max_price IS NULL OR p.price <= max_price)
      AND (
          exclude_product_types IS NULL
          OR p.product_type IS NULL
          OR NOT (p.product_type = ANY (exclude_product_types))
      )
      AND (
          similarity_threshold IS NULL
          OR (1 - (p.description_embedding <=> query_embedding)) >= similarity_threshold
      )
    ORDER BY p.description_embedding <=> query_embedding   -- uses HNSW when selective
    LIMIT GREATEST(match_count, 1);
$$;

COMMENT ON FUNCTION public.match_products IS
    'Agentic RAG retrieval: cosine ANN over products.description_embedding with PIM metadata guards.';


-- -----------------------------------------------------------------------------
-- 9. Stitched helper RPC — consumer context + vector match in one round-trip
-- -----------------------------------------------------------------------------
CREATE OR REPLACE FUNCTION public.match_products_for_consumer(
    p_external_id           text,
    query_embedding         extensions.vector(384),
    match_count             integer DEFAULT 5,
    filter_category         text DEFAULT NULL,
    min_price               numeric DEFAULT NULL,
    max_price               numeric DEFAULT NULL
)
RETURNS TABLE (
    sku                     text,
    name                    text,
    category                text,
    price                   numeric,
    similarity              double precision,
    shoe_promotions_suppressed boolean
)
LANGUAGE plpgsql
STABLE
SET search_path = public, extensions
AS $$
DECLARE
    v_consumer public.consumers%ROWTYPE;
    v_exclude_types text[];
BEGIN
    SELECT * INTO v_consumer
    FROM public.consumers c
    WHERE c.external_id = p_external_id;

    IF NOT FOUND THEN
        RAISE EXCEPTION 'Consumer not found: %', p_external_id USING ERRCODE = 'P0002';
    END IF;

    IF public.is_shoe_promotion_suppressed(v_consumer) THEN
        v_exclude_types := ARRAY['Footwear'];
    END IF;

    RETURN QUERY
    SELECT
        m.sku,
        m.name,
        m.category,
        m.price,
        m.similarity,
        public.is_shoe_promotion_suppressed(v_consumer)
    FROM public.match_products(
        query_embedding,
        match_count,
        filter_category,
        NULL,
        min_price,
        max_price,
        v_exclude_types,
        NULL,
        true
    ) AS m;
END;
$$;


-- -----------------------------------------------------------------------------
-- 10. Grants for Supabase RPC exposure (adjust roles per security model)
-- -----------------------------------------------------------------------------
GRANT USAGE ON SCHEMA public TO anon, authenticated, service_role;

GRANT SELECT ON public.products TO anon, authenticated, service_role;
GRANT SELECT ON public.consumers TO authenticated, service_role;
GRANT SELECT, INSERT ON public.behavioral_logs TO authenticated, service_role;

GRANT EXECUTE ON FUNCTION public.match_products TO anon, authenticated, service_role;
GRANT EXECUTE ON FUNCTION public.match_products_for_consumer TO authenticated, service_role;


-- -----------------------------------------------------------------------------
-- § DIMENSION SWAP (OpenAI 1536) — run manually if switching embedding model
-- -----------------------------------------------------------------------------
-- ALTER TABLE public.products
--     ALTER COLUMN description_embedding TYPE extensions.vector(1536);
-- DROP INDEX IF EXISTS idx_products_embedding_hnsw_cosine;
-- CREATE INDEX idx_products_embedding_hnsw_cosine
--     ON public.products
--     USING hnsw (description_embedding extensions.vector_cosine_ops)
--     WITH (m = 16, ef_construction = 64)
--     WHERE description_embedding IS NOT NULL AND is_active = true;
-- -- Recreate match_products / match_products_for_consumer with vector(1536) signatures.
