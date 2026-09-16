# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
SQL executed against the Triple Whale warehouse via /orcabase/api/sql.

Queries must reference @startDate / @endDate rather than literal dates -- the
bound values travel in the request's `period` object, so these strings are
constant and never interpolated with caller input.

Column names here were read off the live warehouse rather than the published
table docs, which disagree with it in places.
"""

# Per-product, per-day sales, funnel, ad attribution and returns.
#
# product_analytics_tvf already carries ad spend, funnel and returns alongside
# sales at product-variant grain, so no join against ads_table or refunds_table
# is needed -- Triple Whale has done the attribution join upstream.
#
# Grouped by day/product/variant because the source is finer than that (it also
# breaks down by collection), which would otherwise double-count a product that
# belongs to more than one collection.
PRODUCT_METRICS_QUERY = """
SELECT
    event_date,
    product_id,
    variant_id,
    ANY_VALUE(sku)           AS sku,
    ANY_VALUE(product_title) AS product_title,
    ANY_VALUE(variant_title) AS variant_title,
    ANY_VALUE(product_status) AS product_status,
    ANY_VALUE(vendor)        AS vendor,
    SUM(total_items_sold)    AS total_items_sold,
    SUM(revenue)             AS revenue,
    SUM(orders)              AS orders,
    SUM(spend)               AS spend,
    SUM(visits)              AS visits,
    SUM(added_to_cart_items) AS added_to_cart_items,
    SUM(clicks)              AS clicks,
    SUM(impressions)         AS impressions,
    SUM(returns)             AS returns,
    SUM(new_customer_revenue) AS new_customer_revenue,
    SUM(new_customer_orders)  AS new_customer_orders
FROM product_analytics_tvf
WHERE event_date BETWEEN @startDate AND @endDate
GROUP BY event_date, product_id, variant_id
ORDER BY event_date DESC, revenue DESC
"""
