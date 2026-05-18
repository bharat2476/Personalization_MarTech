-- Run AFTER: supabase/migrations/20260518120000_cdp_stitched_schema.sql
-- Supabase Dashboard -> SQL Editor -> New query -> paste -> Run

INSERT INTO public.consumers (
    external_id,
    segment,
    declared_interests,
    lifecycle_stage,
    browser_intent_signal,
    gender,
    age_group,
    location_region,
    email_opt_in,
    consent_marketing,
    consent_app_usage,
    channel_preference,
    last_shoe_purchase_at,
    shoe_suppression_window,
    max_weekly_touches,
    touches_sent_this_week
) VALUES (
    'USER_7721',
    'High-Value Runner',
    ARRAY['Marathon Training', 'Trail Running'],
    'High-Value Member',
    'Trail',
    'Women',
    '35-44',
    'CA',
    true,
    true,
    true,
    'Email + Push',
    now() - interval '14 days',
    interval '14 days',
    3,
    0
)
ON CONFLICT (external_id) DO UPDATE SET
    last_shoe_purchase_at = EXCLUDED.last_shoe_purchase_at,
    declared_interests = EXCLUDED.declared_interests;

INSERT INTO public.products (
    sku, name, price, category, product_type, audience,
    description, behavioral_tags
) VALUES (
    'ACC-004',
    'HydroStream 2L Hydration Vest',
    85.00,
    'Accessories',
    'Accessories',
    'Women',
    'Lightweight 2L hydration vest for marathon and trail training. High semantic fit for endurance runners.',
    ARRAY['hydration', 'marathon', 'trail', 'ultra']
)
ON CONFLICT (sku) DO NOTHING;

INSERT INTO public.behavioral_logs (
    consumer_id,
    event_type,
    target_id,
    target_category,
    session_propensity_score,
    event_metadata
)
SELECT
    c.id,
    'view',
    'AeroGlow Shoes',
    'Running',
    0.82,
    '{"views_in_10_min": 3}'::jsonb
FROM public.consumers c
WHERE c.external_id = 'USER_7721'
LIMIT 1;
