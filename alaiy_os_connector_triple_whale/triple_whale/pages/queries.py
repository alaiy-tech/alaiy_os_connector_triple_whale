# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
SQL for storefront page traffic, executed via /orcabase/api/sql.

Column names were read off the live warehouse, not the published table docs,
which list the tables but not their columns. Both queries return counts only;
neither selects an email, phone number, name or any other visitor identifier.
"""

# True page views per page per day, from the customer journey table.
#
# customer_journey_table is one row per touchpoint of an attributed journey, so
# the same page view is repeated across many rows: a collection page showed
# 78,126 rows for 808 real page views over a week. Counting rows would overstate
# traffic roughly a hundredfold, so views are the distinct page_view_event_id.
#
# The query string is stripped so the same page with different utm tags is one
# page. product_id is empty on every product-page row, so pages are identified
# by their URL handle instead.
PAGE_VIEWS_QUERY = r"""
SELECT
    event_date,
    page_type,
    replaceRegexpOne(url, '\\?.*$', '')  AS page,
    uniqExact(page_view_event_id)        AS page_views,
    uniqExact(session_id)                AS sessions
FROM customer_journey_table
WHERE page_type IN ('product', 'collection', 'home', 'search')
  AND event_date BETWEEN @startDate AND @endDate
GROUP BY event_date, page_type, page
ORDER BY event_date DESC, page_views DESC
"""

# Sessions that began on each page, per day.
#
# web_analytics_table is split by device, country, city and hour; rolling it up
# to page-day gives the totals. time_on_site is the total seconds of sessions
# that did not bounce (a bounced session carries none), so the average is
# time_on_site / (sessions - bounces). That matches Triple Whale's own average
# session duration.
LANDING_PAGES_QUERY = r"""
SELECT
    event_date,
    replaceRegexpOne(landing_page, '\\?.*$', '') AS page,
    SUM(sessions)             AS sessions,
    SUM(unique_visitors)      AS unique_visitors,
    SUM(new_visitors)         AS new_visitors,
    SUM(bounces)              AS bounces,
    SUM(session_page_views)   AS page_views,
    SUM(time_on_site)         AS time_on_site,
    SUM(add_to_carts)         AS add_to_carts,
    SUM(orders_quantity)      AS orders,
    SUM(order_revenue)        AS revenue
FROM web_analytics_table
WHERE event_date BETWEEN @startDate AND @endDate
GROUP BY event_date, page
ORDER BY event_date DESC, sessions DESC
"""
