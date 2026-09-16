# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Read endpoints backing the Triple Whale page.

Everything here reads the cached metric doctypes; none of it calls Triple
Whale. The dashboard must stay usable when the API is unreachable, and page
loads should never burn API quota.
"""

import frappe
from frappe.utils import add_days, date_diff, today


# Below this much spend a ROAS ratio is arithmetic noise: a product that
# happened to receive a few rupees of impressions next to a large organic sale
# reads as a spectacular return it did not earn.
MIN_SPEND_FOR_ROAS = 100.0


def _report_currency():
    """
    The currency the figures are actually denominated in, as configured.

    Triple Whale bases its figures on the connected store and ad accounts,
    which need not report in the Alaiy OS site currency -- stamping the site
    symbol on figures returned in another one would misstate them. Nothing is
    assumed when the setting is blank: the page then shows bare numbers rather
    than a symbol that might be wrong.
    """
    settings = frappe.get_single("Triple Whale Connector Settings")
    return (settings.triple_whale_currency or "").strip() or None


# A window longer than this makes the daily charts unreadable and the queries
# slow without telling anyone anything the monthly cohort view does not.
MAX_WINDOW_DAYS = 730


def _window(days, start=None, end=None):
    """
    The reporting window, as (start, end) inclusive.

    An explicit range wins over the day count, so the presets and the custom
    picker share one path. A reversed range is swapped rather than rejected,
    since picking the end date first is an easy thing to do.
    """
    if start and end:
        start, end = str(start)[:10], str(end)[:10]
        if start > end:
            start, end = end, start
        if date_diff(end, start) + 1 > MAX_WINDOW_DAYS:
            start = add_days(end, -(MAX_WINDOW_DAYS - 1))
        return start, end

    days = max(1, min(frappe.utils.cint(days) or 30, MAX_WINDOW_DAYS))
    anchor = str(end)[:10] if end else today()
    return add_days(anchor, -(days - 1)), anchor


@frappe.whitelist()
def get_overview(days=30, start=None, end=None):
    """Headline figures for the period, plus the daily series behind them."""
    start, end = _window(days, start, end)

    rows = frappe.get_all(
        "Triple Whale Daily Metric",
        filters={"metric_date": ["between", [start, end]]},
        fields=[
            "metric_date", "total_sales", "order_revenue", "orders", "spend",
            "mer", "net_profit", "net_margin", "ncpa", "blended_roas",
            "new_customer_revenue", "returning_customer_revenue",
            "total_refunded_price", "returns_percent", "gross_profit",
            "aov", "visitors", "sessions", "site_conversion_rate",
            "unique_customers", "new_customers_percent", "new_customer_orders",
            "customer_ltv",
        ],
        order_by="metric_date asc",
    )

    totals = {
        "total_sales": 0.0,
        "order_revenue": 0.0,
        "orders": 0,
        "spend": 0.0,
        "net_profit": 0.0,
        "gross_profit": 0.0,
        "new_customer_revenue": 0.0,
        "returning_customer_revenue": 0.0,
        "total_refunded_price": 0.0,
        "visitors": 0,
        "sessions": 0,
        "unique_customers": 0,
        "new_customer_orders": 0,
    }
    for r in rows:
        for key in totals:
            totals[key] += r.get(key) or 0

    # Ratios are recomputed from the period totals rather than averaged across
    # days -- averaging a ratio weights a quiet day the same as a peak one.
    sales = totals["total_sales"]
    spend = totals["spend"]
    totals["mer"] = (sales / spend) if spend else None
    totals["poas"] = (totals["net_profit"] / spend) if spend else None
    totals["net_margin"] = (totals["net_profit"] / sales * 100) if sales else None
    totals["returns_percent"] = (
        (totals["total_refunded_price"] / sales * 100) if sales else None
    )
    totals["aov"] = (sales / totals["orders"]) if totals["orders"] else None
    totals["blended_roas"] = (sales / spend) if spend else None
    totals["ncpa"] = _acquisition_cost(rows, spend, totals["new_customer_orders"])

    # LTV is a standing figure rather than something to sum across days, so the
    # latest day that reported one is the meaningful value.
    ltv = next(
        (r.get("customer_ltv") for r in reversed(rows) if r.get("customer_ltv")),
        None,
    )
    totals["customer_ltv"] = ltv
    totals["ltv_cac_ratio"] = (
        (ltv / totals["ncpa"]) if (ltv and totals["ncpa"]) else None
    )
    totals["site_conversion_rate"] = (
        (totals["orders"] / totals["sessions"] * 100) if totals["sessions"] else None
    )
    nc = totals["new_customer_revenue"]
    rc = totals["returning_customer_revenue"]
    totals["new_customer_share"] = (nc / (nc + rc) * 100) if (nc + rc) else None

    return {
        "period": {"start": start, "end": end, "days": len(rows)},
        "currency": _report_currency(),
        "totals": totals,
        "series": rows,
        "previous": _previous_totals(start, end),
    }


def _acquisition_cost(rows, spend, new_customer_orders):
    """
    Cost to acquire one new customer, over the whole period.

    Triple Whale reports this per day as newCustomersCpa, but a per-day CAC
    cannot simply be averaged: a day with one acquisition would weigh as much
    as a day with fifty. So the period figure is spend over new customers,
    and the reported daily values are only used to recover the customer count
    on days where nothing else gives it.
    """
    if not spend:
        return None

    customers = float(new_customer_orders or 0)

    if not customers:
        # Fall back to the share of orders flagged as from new customers.
        for r in rows:
            day_orders = r.get("orders") or 0
            share = r.get("new_customers_percent")
            if day_orders and share is not None:
                customers += day_orders * float(share) / 100

    if not customers:
        # Last resort: back the count out of the daily CAC Triple Whale gave.
        for r in rows:
            cac = r.get("ncpa")
            day_spend = r.get("spend")
            if cac and day_spend:
                customers += float(day_spend) / float(cac)

    return (spend / customers) if customers else None


def _previous_totals(start, end):
    """
    The same span immediately before the selected one, for period-on-period
    deltas. Computed here rather than in the browser so the comparison uses
    the same aggregation rules as the current period.
    """
    span = date_diff(end, start) + 1
    prev_end = add_days(start, -1)
    prev_start = add_days(prev_end, -(span - 1))
    rows = frappe.get_all(
        "Triple Whale Daily Metric",
        filters={"metric_date": ["between", [prev_start, prev_end]]},
        fields=["total_sales", "spend", "orders", "net_profit"],
    )
    out = {"total_sales": 0.0, "spend": 0.0, "orders": 0, "net_profit": 0.0}
    for r in rows:
        for k in out:
            out[k] += r.get(k) or 0
    out["mer"] = (out["total_sales"] / out["spend"]) if out["spend"] else None
    out["aov"] = (out["total_sales"] / out["orders"]) if out["orders"] else None
    return out


@frappe.whitelist()
def get_top_products(days=30, limit=20, sort_by="product_revenue", start=None, end=None):
    """Per-product figures for the period, aggregated across days."""
    start, end = _window(days, start, end)

    allowed_sorts = {
        "product_revenue", "units_sold", "attributed_spend",
        "refunded_amount", "new_customer_revenue",
    }
    if sort_by not in allowed_sorts:
        sort_by = "product_revenue"
    limit = max(1, min(frappe.utils.cint(limit) or 20, 200))

    rows = frappe.db.sql(
        f"""
        SELECT
            product_id,
            MAX(sku)           AS sku,
            MAX(product_title) AS product_title,
            MAX(vendor)        AS vendor,
            MAX(item)          AS item,
            SUM(units_sold)           AS units_sold,
            SUM(product_revenue)      AS product_revenue,
            SUM(orders)               AS orders,
            SUM(attributed_spend)     AS attributed_spend,
            SUM(new_customer_revenue) AS new_customer_revenue,
            SUM(product_views)        AS product_views,
            SUM(add_to_carts)         AS add_to_carts,
            SUM(refunded_amount)      AS refunded_amount
        FROM `tabTriple Whale Product Metric`
        WHERE metric_date BETWEEN %(start)s AND %(end)s
        GROUP BY product_id
        ORDER BY {sort_by} DESC
        LIMIT %(limit)s
        """,
        {"start": start, "end": end, "limit": limit},
        as_dict=True,
    )

    # Recomputed from period totals for the same reason as above.
    for r in rows:
        views = r.get("product_views") or 0
        revenue = r.get("product_revenue") or 0
        spend = r.get("attributed_spend") or 0
        r["conversion_rate"] = ((r.get("orders") or 0) / views * 100) if views else None
        r["add_to_cart_rate"] = ((r.get("add_to_carts") or 0) / views * 100) if views else None
        r["attributed_roas"] = (
            (revenue / spend) if spend >= MIN_SPEND_FOR_ROAS else None
        )
        r["return_rate"] = ((r.get("refunded_amount") or 0) / revenue * 100) if revenue else None

    return {
        "period": {"start": start, "end": end},
        "currency": _report_currency(),
        "products": rows,
    }


@frappe.whitelist()
def get_channels(days=30, start=None, end=None):
    """Ad performance by channel for the period."""
    start, end = _window(days, start, end)
    rows = frappe.db.sql(
        """
        SELECT channel,
               SUM(spend)            AS spend,
               SUM(impressions)      AS impressions,
               SUM(clicks)           AS clicks,
               SUM(conversions)      AS conversions,
               SUM(conversion_value) AS conversion_value
        FROM `tabTriple Whale Ad Metric`
        WHERE metric_date BETWEEN %(start)s AND %(end)s
        GROUP BY channel
        ORDER BY spend DESC
        """,
        {"start": start, "end": end},
        as_dict=True,
    )
    for r in rows:
        spend = r.get("spend") or 0
        clicks = r.get("clicks") or 0
        impressions = r.get("impressions") or 0
        conversions = r.get("conversions") or 0
        r["ctr"] = (clicks / impressions * 100) if impressions else None
        r["cpc"] = (spend / clicks) if clicks else None
        r["cpm"] = (spend / impressions * 1000) if impressions else None
        r["roas"] = ((r.get("conversion_value") or 0) / spend) if spend else None
        r["cpa"] = (spend / conversions) if conversions else None
    return {
        "period": {"start": start, "end": end},
        "currency": _report_currency(),
        "channels": rows,
    }


@frappe.whitelist()
def get_state():
    """Whether the connector is configured, and when it last synced."""
    settings = frappe.get_single("Triple Whale Connector Settings")
    last = {}
    for sync_type in ("metrics", "attribution", "ads", "cohorts"):
        row = frappe.get_all(
            "Triple Whale Sync Log",
            filters={"sync_type": sync_type},
            fields=["name", "status", "started_at", "finished_at", "items_processed"],
            order_by="started_at desc",
            limit=1,
        )
        last[sync_type] = row[0] if row else None

    return {
        "is_enabled": bool(settings.is_enabled),
        "shop_domain": settings.triple_whale_shop_domain,
        "has_key": bool(settings.triple_whale_api_key),
        "lookback_days": settings.triple_whale_lookback_days,
        "last_sync": last,
        "daily_rows": frappe.db.count("Triple Whale Daily Metric"),
        "product_rows": frappe.db.count("Triple Whale Product Metric"),
        "ad_rows": frappe.db.count("Triple Whale Ad Metric"),
    }


@frappe.whitelist()
def get_connection_overview():
    """
    What Triple Whale is connected to, and what each sync is doing.

    Powers the panel on the settings form. The integration list is derived
    from the metrics the account actually reports rather than a hardcoded
    list, so a newly connected platform shows up on its own.
    """
    settings = frappe.get_single("Triple Whale Connector Settings")

    syncs = []
    for key, label, interval_field, doctype in (
        ("metrics", "Store Metrics", "triple_whale_metrics_sync_interval",
         "Triple Whale Daily Metric"),
        ("attribution", "Product Attribution", "triple_whale_attribution_sync_interval",
         "Triple Whale Product Metric"),
        ("ads", "Ad Channels", "triple_whale_ads_sync_interval",
         "Triple Whale Ad Metric"),
        ("cohorts", "Cohort Retention", "triple_whale_cohorts_sync_interval",
         "Triple Whale Cohort"),
    ):
        last = frappe.get_all(
            "Triple Whale Sync Log",
            filters={"sync_type": key},
            fields=[
                "name", "status", "trigger", "started_at", "finished_at",
                "items_processed", "items_created", "items_updated",
                "items_failed", "error_message",
            ],
            order_by="started_at desc",
            limit=1,
        )
        syncs.append({
            "key": key,
            "label": label,
            "interval": settings.get(interval_field) or "Disabled",
            "doctype": doctype,
            "rows": frappe.db.count(doctype),
            "last": last[0] if last else None,
        })

    return {
        "is_enabled": bool(settings.is_enabled),
        "shop_domain": settings.triple_whale_shop_domain,
        "has_key": bool(settings.triple_whale_api_key),
        "lookback_days": settings.triple_whale_lookback_days,
        "syncs": syncs,
        "integrations": _detected_integrations(),
    }


# Metric id prefix -> the platform it belongs to. Triple Whale reports every
# integration it supports whether or not this account uses one, so presence is
# inferred from a non-zero value rather than from the metric merely existing.
_INTEGRATION_PREFIXES = {
    "facebook": "Meta Ads",
    "google": "Google Ads",
    "ga_": "Google Analytics",
    "tiktok": "TikTok Ads",
    "snapchat": "Snapchat Ads",
    "pinterest": "Pinterest Ads",
    "twitter": "X Ads",
    "bing": "Microsoft Ads",
    "amazon": "Amazon",
    "walmart": "Walmart",
    "klaviyo": "Klaviyo",
    "attentive": "Attentive",
    "postscript": "Postscript",
    "omnisend": "Omnisend",
    "smsbump": "SMSBump",
    "sendlane": "Sendlane",
    "recharge": "Recharge",
    "skio": "Skio",
    "loop": "Loop",
    "stayai": "Stay AI",
    "shipbob": "ShipBob",
    "shipstation": "ShipStation",
    "gorgias": "Gorgias",
    "okendo": "Okendo",
    "criteo": "Criteo",
    "outbrain": "Outbrain",
    "taboola": "Taboola",
    "applovin": "AppLovin",
    "linkedin": "LinkedIn Ads",
    "reddit": "Reddit Ads",
    "rokt": "Rokt",
    "mountain": "MNTN",
    "vibe": "Vibe",
    "openaiAds": "OpenAI Ads",
    "influencer": "Influencers",
    "pixel": "Triple Whale Pixel",
    "shopify": "Shopify",
}


def _detected_integrations(days=30):
    """
    Platforms this account actually reports data for, most recent window.

    Reads the stored All Metrics rows rather than calling Triple Whale, so the
    settings form stays instant and never spends API quota.
    """
    start, end = _window(days)
    rows = frappe.db.sql(
        """
        SELECT DISTINCT v.metric_id
        FROM `tabTriple Whale Metric Value` v
        INNER JOIN `tabTriple Whale Daily Metric` d ON d.name = v.parent
        WHERE d.metric_date BETWEEN %(start)s AND %(end)s
        """,
        {"start": start, "end": end},
    )
    seen = {r[0] for r in rows if r and r[0]}

    found = {}
    for metric_id in seen:
        # Longest prefix first, so "googleAds" is not claimed by a shorter
        # entry that happens to also match.
        label = next(
            (
                lbl
                for pre, lbl in sorted(
                    _INTEGRATION_PREFIXES.items(), key=lambda kv: -len(kv[0])
                )
                if metric_id.startswith(pre)
            ),
            None,
        )
        # A platform Triple Whale adds later has no entry here. Falling back
        # to its own prefix keeps it visible rather than silently dropping a
        # connected integration because this list has not caught up.
        if label is None:
            label = _infer_label(metric_id)
        if label:
            found[label] = found.get(label, 0) + 1

    # Channels that actually carry ad spend are worth stating outright rather
    # than inferring from a metric prefix.
    spend_channels = frappe.db.sql(
        """
        SELECT channel, SUM(spend) AS spend
        FROM `tabTriple Whale Ad Metric`
        WHERE metric_date BETWEEN %(start)s AND %(end)s
        GROUP BY channel HAVING SUM(spend) > 0
        """,
        {"start": start, "end": end},
        as_dict=True,
    )

    # Triple Whale's channel ids do not match the platform names the metric
    # prefixes produce -- facebook-ads is Meta Ads -- so the mapping is stated
    # rather than inferred from the strings.
    spending_labels = sorted(
        {
            _CHANNEL_LABELS.get(r["channel"], r["channel"])
            for r in spend_channels
        }
    )

    return {
        "platforms": sorted(found.keys()),
        "metric_counts": found,
        "spending": spending_labels,
        "ad_channels": [
            {
                "channel": r["channel"],
                "label": _CHANNEL_LABELS.get(r["channel"], r["channel"]),
                "spend": r["spend"],
            }
            for r in spend_channels
        ],
    }


def _infer_label(metric_id):
    """
    Best-effort platform name for a metric with no mapping entry.

    Metric ids are camelCase and lead with their platform, so the leading
    lowercase run is the platform. Anything shorter than three characters is
    too ambiguous to label and is skipped.
    """
    lead = ""
    for ch in metric_id:
        if ch.islower() or ch == "_":
            lead += ch
        else:
            break
    lead = lead.strip("_")
    if len(lead) < 3:
        return None
    # Generic metric families rather than an integration name.
    if lead in _NOT_PLATFORMS:
        return None
    # A platform name is a prefix, so something follows it. A metric that is
    # only its own name -- mer, orders, discounts -- is a store-wide figure
    # rather than an integration.
    if lead == metric_id:
        return None
    return lead[:1].upper() + lead[1:]


# Leading words that begin a metric name without naming an integration.
_NOT_PLATFORMS = {
    "total", "blended", "custom", "new", "returning", "avg", "top", "unique",
    "gross", "net", "cash", "cogs", "orders", "sales", "shipping", "taxes",
    "discounts", "inventory", "handling", "payment", "responses", "pacing",
    "forward", "enq", "kno", "benchmarks", "influencer", "conversion",
}


# Triple Whale's standardized channel id -> the platform label used elsewhere.
_CHANNEL_LABELS = {
    "facebook-ads": "Meta Ads",
    "google-ads": "Google Ads",
    "tiktok-ads": "TikTok Ads",
    "snapchat-ads": "Snapchat Ads",
    "pinterest-ads": "Pinterest Ads",
    "twitter-ads": "X Ads",
    "bing-ads": "Microsoft Ads",
    "amazon-ads": "Amazon",
    "linkedin-ads": "LinkedIn Ads",
    "reddit-ads": "Reddit Ads",
    "criteo-ads": "Criteo",
    "outbrain-ads": "Outbrain",
    "taboola-ads": "Taboola",
    "applovin-ads": "AppLovin",
}


@frappe.whitelist()
def get_cohorts(limit=12):
    """
    Retention and realised LTV by acquisition cohort, newest first.

    Not bounded by the dashboard's date range: a cohort curve is about how far
    customers have been followed since acquisition, which a reporting window
    would truncate rather than filter.
    """
    limit = max(1, min(frappe.utils.cint(limit) or 12, 36))
    months = frappe.db.sql(
        """
        SELECT DISTINCT cohort_month
        FROM `tabTriple Whale Cohort`
        ORDER BY cohort_month DESC
        LIMIT %(limit)s
        """,
        {"limit": limit},
    )
    months = [m[0] for m in months]
    if not months:
        return {"cohorts": [], "max_months": 0}

    rows = frappe.get_all(
        "Triple Whale Cohort",
        filters={"cohort_month": ["in", months]},
        fields=[
            "cohort_month", "months_since", "cohort_customers",
            "active_customers", "retention_rate", "orders", "revenue",
            "revenue_per_customer", "cumulative_revenue_per_customer",
        ],
        order_by="cohort_month desc, months_since asc",
    )

    grouped = {}
    for r in rows:
        grouped.setdefault(str(r["cohort_month"]), []).append(r)

    return {
        "currency": _report_currency(),
        "max_months": max((r["months_since"] or 0) for r in rows),
        "cohorts": [
            {
                "cohort_month": month,
                "cohort_customers": entries[0]["cohort_customers"],
                "periods": entries,
            }
            for month, entries in grouped.items()
        ],
    }
