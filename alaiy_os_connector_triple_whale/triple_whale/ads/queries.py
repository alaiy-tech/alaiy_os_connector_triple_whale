# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
SQL for per-channel ad performance, executed via /orcabase/api/sql.

Column names were read off the live warehouse rather than the published table
docs, which disagree with it in places.
"""

# One row per channel per day, across every ad platform the account connects.
#
# ads_table is at ad grain, so this rolls up to channel-day. Channels are
# Triple Whale's standardized ids (facebook-ads, google-ads, tiktok-ads, ...),
# which is why nothing here is platform-specific: a newly connected platform
# appears on its own rows without a schema change.
#
# Rates are deliberately not computed here. Deriving them after the rollup
# avoids averaging an average, and a zero denominator yields a blank rather
# than failing the query.
CHANNEL_METRICS_QUERY = """
SELECT
    event_date,
    channel,
    ANY_VALUE(currency)     AS currency,
    SUM(spend)              AS spend,
    SUM(impressions)        AS impressions,
    SUM(clicks)             AS clicks,
    SUM(conversions)        AS conversions,
    SUM(conversion_value)   AS conversion_value,
    SUM(reach)              AS reach,
    SUM(outbound_clicks)    AS outbound_clicks,
    SUM(visits)             AS visits,
    SUM(engagements)        AS engagements
FROM ads_table
WHERE event_date BETWEEN @startDate AND @endDate
GROUP BY event_date, channel
ORDER BY event_date DESC, spend DESC
"""
