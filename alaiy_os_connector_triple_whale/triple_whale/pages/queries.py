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

# Of the sessions that opened a collection page, how many went on to open a
# product page afterwards, per collection page per day.
#
# page_view_number orders the page views within a session. The same page view is
# repeated across attribution rows, so sessions are counted distinct, and a
# session is split at midnight (it is matched to product views on the same day).
CLICK_THROUGH_QUERY = r"""
SELECT
    c.event_date                                      AS event_date,
    c.page                                            AS page,
    uniqExact(c.session_id)                           AS sessions,
    uniqExactIf(c.session_id, p.max_pv > c.min_pv)    AS clicked
FROM (
    SELECT event_date, session_id,
           replaceRegexpOne(url, '\\?.*$', '') AS page,
           min(page_view_number)               AS min_pv
    FROM customer_journey_table
    WHERE page_type = 'collection' AND event_date BETWEEN @startDate AND @endDate
    GROUP BY event_date, session_id, page
) AS c
LEFT JOIN (
    SELECT event_date, session_id, max(page_view_number) AS max_pv
    FROM customer_journey_table
    WHERE page_type = 'product' AND event_date BETWEEN @startDate AND @endDate
    GROUP BY event_date, session_id
) AS p ON c.session_id = p.session_id AND c.event_date = p.event_date
GROUP BY c.event_date, c.page
"""

# Where the sessions that began on a product or collection page came from, grouped
# into a handful of sources.
#
# The raw channel values are many and uneven (a typo of facebook, several email
# tools), so they are grouped here to keep the table small. The order matters:
# Direct first, then email and SMS, then paid, then organic and social.
TRAFFIC_SOURCES_QUERY = r"""
SELECT
    event_date,
    multiIf(
        ifNull(channel, '') = 'Direct', 'Direct',
        ifNull(utm_medium, '') IN ('email', 'sms')
            OR ifNull(channel, '') IN ('klaviyo', 'OrderlyEmails', 'swym-Wishlist'), 'Email & SMS',
        ifNull(channel, '') LIKE '%-ads' OR ifNull(utm_medium, '') IN ('cpc', 'paid'), 'Paid ads',
        ifNull(channel, '') = 'organic_and_social', 'Organic & social',
        ifNull(utm_medium, '') = 'affiliate', 'Affiliates',
        'Other'
    )                                                          AS traffic_source,
    replaceRegexpOne(landing_page, '\\?.*$', '')               AS page,
    uniqExact(session_id)                                      AS sessions,
    uniqExactIf(session_id, coalesce(is_new_visitor, 0) = 1)   AS new_visitors
FROM sessions_table
WHERE event_date BETWEEN @startDate AND @endDate
  AND match(landing_page, '^(https?://[^/]+)?/(products|collections)/')
GROUP BY event_date, traffic_source, page
"""
