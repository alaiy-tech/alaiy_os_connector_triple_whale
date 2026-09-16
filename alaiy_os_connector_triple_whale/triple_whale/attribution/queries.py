# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
SQL executed against the Triple Whale warehouse via /orcabase/api/sql.

Queries must reference @startDate / @endDate rather than literal dates -- the
bound values travel in the request's `period` object, so these strings are
constant and never interpolated with caller input.

Table and column names follow Triple Whale's published warehouse schema; the
catalogue is in docs/triple_whale/reference/llms.txt.
"""

# Per-product, per-day sales, funnel, ad attribution and refunds.
#
# product_analytics_table carries sales and funnel figures together, so it is
# the spine. Ad attribution and refunds live in separate tables at different
# grains and are aggregated to product-day before joining, which keeps the
# join from multiplying the spine's rows.
PRODUCT_METRICS_QUERY = """
WITH product_base AS (
    SELECT
        event_date,
        product_id,
        variant_id,
        ANY_VALUE(sku)           AS sku,
        ANY_VALUE(product_title) AS product_title,
        SUM(product_quantity_sold_in_order) AS units_sold,
        SUM(product_revenue)                AS product_revenue,
        COUNT(DISTINCT order_id)            AS orders,
        SUM(product_views)                  AS product_views,
        SUM(add_to_carts)                   AS add_to_carts
    FROM product_analytics_table
    WHERE event_date BETWEEN @startDate AND @endDate
    GROUP BY event_date, product_id, variant_id
),
attribution AS (
    SELECT
        event_date,
        product_id,
        SUM(attributed_revenue) AS attributed_revenue,
        SUM(spend)              AS attributed_spend
    FROM ads_table
    WHERE event_date BETWEEN @startDate AND @endDate
      AND product_id IS NOT NULL
    GROUP BY event_date, product_id
),
refunds AS (
    SELECT
        event_date,
        product_id,
        SUM(refunded_amount)   AS refunded_amount,
        SUM(refunded_quantity) AS refunded_units
    FROM refunds_table
    WHERE event_date BETWEEN @startDate AND @endDate
    GROUP BY event_date, product_id
)
SELECT
    p.event_date,
    p.product_id,
    p.variant_id,
    p.sku,
    p.product_title,
    p.units_sold,
    p.product_revenue,
    p.orders,
    p.product_views,
    p.add_to_carts,
    a.attributed_revenue,
    a.attributed_spend,
    r.refunded_amount,
    r.refunded_units
FROM product_base p
LEFT JOIN attribution a
       ON a.event_date = p.event_date AND a.product_id = p.product_id
LEFT JOIN refunds r
       ON r.event_date = p.event_date AND r.product_id = p.product_id
ORDER BY p.event_date DESC, p.product_revenue DESC
"""
