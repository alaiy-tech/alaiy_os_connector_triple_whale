# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Cohort retention SQL, executed via /orcabase/api/sql.

The warehouse is ClickHouse, not BigQuery: date handling is toStartOfMonth /
dateDiff rather than DATE_TRUNC, and distinct counts are countDistinct rather
than COUNT(DISTINCT ...). Queries that look like standard SQL but use a
BigQuery type name fail outright, so these stay in ClickHouse's dialect.

customer_segmentation_analytics_tvf would be the obvious source but is a
table-valued function that rejects a plain SELECT, so cohorts are derived from
orders_table, which is the canonical order record anyway.
"""

# One row per cohort month per month-since-acquisition.
#
# A customer belongs to the month of their first ever order, and is counted in
# every later month they order again. Retention is therefore measured against
# the cohort's own size rather than against the whole customer base.
#
# The window bounds which activity is counted, not which cohorts exist: the
# first_order subquery deliberately scans all history, because a cohort's
# start month is a property of the customer and does not change with the
# reporting period.
COHORT_RETENTION_QUERY = """
WITH first_order AS (
    SELECT
        customer_id,
        min(event_date) AS acquired_on
    FROM orders_table
    WHERE customer_id != ''
    GROUP BY customer_id
),
cohort_size AS (
    SELECT
        toStartOfMonth(acquired_on) AS cohort_month,
        countDistinct(customer_id)  AS cohort_customers
    FROM first_order
    GROUP BY cohort_month
)
SELECT
    toStartOfMonth(f.acquired_on) AS cohort_month,
    dateDiff('month', toStartOfMonth(f.acquired_on), toStartOfMonth(o.event_date))
        AS months_since,
    any(c.cohort_customers)    AS cohort_customers,
    countDistinct(o.customer_id) AS active_customers,
    countDistinct(o.order_id)  AS orders,
    sum(o.order_revenue)       AS revenue
FROM orders_table o
INNER JOIN first_order f ON f.customer_id = o.customer_id
INNER JOIN cohort_size c ON c.cohort_month = toStartOfMonth(f.acquired_on)
WHERE o.event_date BETWEEN @startDate AND @endDate
  AND o.customer_id != ''
GROUP BY cohort_month, months_since
ORDER BY cohort_month DESC, months_since ASC
"""

# Refunded value per marketing channel per day.
#
# refunds_table carries source_name, but that is the sales channel (web, pos)
# rather than the marketing channel that won the order, so refunds join
# through pixel_orders_table to reach attribution.
#
# That table is multi-touch: an order appears once per touchpoint, so joining
# naively bills the whole refund to every channel that touched it -- one
# refund was landing in full against three separate channels. Each refund is
# therefore split by the touchpoint's linear_weight, normalised by the weight
# actually present for that order so the parts sum back to the whole even
# where the weights do not total one.
#
# Keyed on the refund's own event_date rather than the order's, so a refund
# lands on the day the money actually went back.
REFUNDS_BY_CHANNEL_QUERY = """
WITH weights AS (
    SELECT
        order_id,
        channel,
        sum(linear_weight) AS weight
    FROM pixel_orders_table
    WHERE channel != ''
    GROUP BY order_id, channel
),
totals AS (
    SELECT order_id, sum(weight) AS total_weight
    FROM weights
    GROUP BY order_id
)
SELECT
    r.event_date AS event_date,
    w.channel    AS channel,
    sum(r.total_refunded_price * w.weight / t.total_weight) AS refunded,
    sum(r.total_refunded_cogs  * w.weight / t.total_weight) AS refunded_cogs,
    sum(w.weight / t.total_weight)                          AS refunded_orders,
    countDistinct(r.refund_id)                              AS refund_events
FROM refunds_table r
INNER JOIN weights w ON w.order_id = r.order_id
INNER JOIN totals  t ON t.order_id = r.order_id
WHERE r.event_date BETWEEN @startDate AND @endDate
  AND t.total_weight > 0
GROUP BY event_date, channel
ORDER BY event_date DESC, refunded ASC
"""
