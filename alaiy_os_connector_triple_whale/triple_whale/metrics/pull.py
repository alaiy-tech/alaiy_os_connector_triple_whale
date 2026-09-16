# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Store-wide summary metrics -> Triple Whale Daily Metric.

The Summary Page endpoint returns every metric's period total alongside a
daily series in `charts.current`, so one call covers the whole window.

The series lags the current day: a day only appears once it has closed, so
today is never written by this sync. It lands on the following run, which is
another reason the sync re-fetches a window rather than a single day.
"""

import datetime
import json

import frappe
from frappe.utils import add_days, getdate, today

from alaiy_os_connector_triple_whale.triple_whale.auth import TripleWhaleClient
from alaiy_os_connector_triple_whale.triple_whale.sync_log import run_logged
from alaiy_os_connector_triple_whale.triple_whale.window import as_float, sync_window

# Summary Page metric `id` -> Triple Whale Daily Metric fieldname.
#
# These are the ids the endpoint actually returns, which are camelCase and do
# NOT match the snake_case column names in Triple Whale's metric catalogue --
# the catalogue documents warehouse columns, the Summary Page speaks its own
# vocabulary. Verified against a live response.
#
# The account returns ~500 metrics covering every integration it has; only the
# ones the dashboards consume are promoted to columns. The full payload is kept
# in raw_payload so a new metric can be backfilled without re-fetching.
SUMMARY_FIELD_MAP = {
    # Revenue
    "sales": "order_revenue",           # gross - discounts + tax + shipping
    "netSales": "total_sales",          # gross - discounts - returns + shipping + tax
    "grossSales": "gross_sales",
    "orders": "orders",
    "shopifyOrdersWithAmount": "orders_with_amount",
    "shopifyAov": "aov",
    "totalVariantsSold": "units_sold",
    "discounts": "discounts",
    "taxes": "taxes",
    "shippingPrice": "shipping_price",
    # Customers
    "newCustomerSales": "new_customer_revenue",
    "rcRevenue": "returning_customer_revenue",
    "newCustomersOrders": "new_customer_orders",
    "returningCustomerOrders": "returning_customer_orders",
    "newCustomersPercent": "new_customers_percent",
    "uniqueCustomers": "unique_customers",
    "uniqueCustomerSales": "customer_ltv",
    "customerFrequency": "customer_frequency",
    "ltvCpa": "ltv_cac_ratio",
    # Ad spend and efficiency
    "blendedAds": "spend",              # blended across every ad platform
    "mer": "mer",
    "roas": "blended_roas",
    "blendedAttributedRoas": "blended_attributed_roas",
    "shopifyCpa": "blended_cpa",
    "newCustomersCpa": "ncpa",          # the CAC figure
    "newCustomersRoas": "new_customer_roas",
    # Profitability
    "totalNetProfit": "net_profit",
    "grossProfit": "gross_profit",
    "totalNetMargin": "net_margin",
    "topKpiContributionProfit": "contribution_profit",
    "cogs": "cost_of_goods",
    "shipping": "shipping_costs",
    "handlingFees": "handling_fees",
    "paymentGateways": "payment_gateway_costs",
    "poas": "poas",
    # Returns
    "totalRefunds": "total_refunded_price",
    "totalReturns": "returns_percent",
    # Site traffic and funnel (pixel)
    "pixelVisitors": "visitors",
    "pixelUniqueVisitors": "unique_visitors",
    "pixelVisitSessions": "sessions",
    "pixelPageViews": "page_views",
    "pixelPercentNewVisitors": "new_visitors_percent",
    "pixelConversionRate": "site_conversion_rate",
    "pixelUniqueSessionsAtc": "add_to_carts",
    "pixelPercentAtc": "add_to_cart_rate",
    "pixelBounceRate": "bounce_rate",
    "pixelAvgSessionDuration": "avg_session_duration",
    # Blended channel roll-ups; per-channel detail is in Triple Whale Ad Metric
    "facebookAds": "facebook_spend",
    "facebookRoas": "facebook_roas",
    "facebookConversionValue": "facebook_conversion_value",
    "googleAds": "google_spend",
    "googleRoas": "google_roas",
    "googleConversionValue": "google_conversion_value",
    # Email and SMS
    "klaviyoPlacedOrderSales": "klaviyo_sales",
    "klaviyoSalesPercent": "klaviyo_sales_percent",
    "klaviyoPlacedOrderTotalPriceFlows": "klaviyo_flow_sales",
    "klaviyoPlacedOrderTotalPriceCampaigns": "klaviyo_campaign_sales",
    # Inventory
    "inventoryItems": "inventory_items",
    "totalInventoryValue": "inventory_value",
    "totalInventoryCost": "inventory_cost",
}


def run(trigger="scheduled", log_name=None):
    """
    Pull store-wide summary metrics for the sync window.

    One call covers the whole window: the endpoint returns each metric's daily
    series in `charts.current`, so there is no reason to ask per day -- and
    asking per day would in fact be wrong, since the endpoint ignores narrow
    date ranges and answers month-to-date regardless.
    """

    def worker(log):
        client = TripleWhaleClient()
        start, end = sync_window()

        response = client.summary_page(start, end)
        by_day = extract_daily_series(response, start, end)
        meta = extract_metric_meta(response)
        active = active_metric_ids(by_day, response)

        # Some metrics carry only a period total and no daily chart -- customer
        # counts and inventory levels among them. Those are attached to the
        # last day of the window rather than dropped, since leaving the field
        # unset makes Frappe store a zero that reads as a real measurement.
        period_only = period_only_metrics(response, by_day)
        if by_day and period_only:
            by_day[max(by_day)].update(period_only)

        log.pages_total = 1
        log.pages_done = 1
        log.items_processed = len(by_day)

        created = updated = 0
        for day, payload in sorted(by_day.items()):
            if upsert(day, payload, meta, active):
                created += 1
            else:
                updated += 1

        log.items_created = created
        log.items_updated = updated
        log.log_messages = (
            f"{len(active)} of {len(meta)} metrics reported by this account; "
            f"the rest were zero across the whole window and belong to "
            f"integrations that are not connected."
        )
        frappe.db.commit()

    run_logged("metrics", trigger, log_name, worker)


def extract_metrics(response):
    """
    Flatten the Summary Page response into {id: value}.

    The live shape is:

        {"metrics": [{"id": "mer", "metricId": "mer", "type": "percent",
                      "values": {"current": 14.8, "previous": 9.2},
                      "charts": {...}}, ...]}

    The published spec describes a simpler {"metricName", "value"} pair, which
    the endpoint does not actually return; both are accepted so a future
    change to the documented shape does not break the sync.
    """
    if not isinstance(response, dict):
        return {}

    metrics = response.get("metrics")
    if isinstance(metrics, dict):
        return metrics
    if not isinstance(metrics, list):
        return {}

    flat = {}
    for entry in metrics:
        if not isinstance(entry, dict):
            continue
        key = entry.get("id") or entry.get("metricName") or entry.get("metricId")
        if key is None:
            continue
        values = entry.get("values")
        if isinstance(values, dict):
            flat[str(key)] = values.get("current")
        elif "value" in entry:
            flat[str(key)] = entry.get("value")
    return flat


def active_metric_ids(by_day, response):
    """
    The metrics this account actually reports.

    Triple Whale answers with every metric it knows about, including the
    several hundred belonging to integrations this account does not use. Those
    are constant zero. Deciding per metric across the whole window rather than
    per day is what keeps a real zero -- a connected channel that simply spent
    nothing on a Sunday -- from being mistaken for a disconnected one.

    The period totals are consulted as well as the daily series, so a metric
    that is non-zero for the period but flat within it still counts.
    """
    active = set()
    for payload in by_day.values():
        for metric_id, value in payload.items():
            number = _as_number(value)
            if number:
                active.add(metric_id)

    for metric_id, value in (extract_metrics(response) or {}).items():
        if _as_number(value):
            active.add(metric_id)
    return active


def _as_number(value):
    """
    Truthiness test for the active check. A non-numeric value counts as
    present, since only a numeric zero marks a disconnected integration.
    """
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0 if str(value).strip() else None


def period_only_metrics(response, by_day):
    """
    Metrics the response reports for the period but never breaks down by day.

    Returning them separately keeps the daily rows honest: a metric that was
    simply never measured per day should not be written as zero on every day,
    which is indistinguishable from having genuinely been zero.
    """
    daily_keys = set()
    for payload in by_day.values():
        daily_keys.update(payload)

    period_only = {}
    for metric_id, value in (extract_metrics(response) or {}).items():
        if metric_id in daily_keys:
            continue
        if _as_number(value):
            period_only[metric_id] = value
    return period_only


def extract_metric_meta(response):
    """
    Collect each metric's human title and value type from the response, so the
    All Metrics table can label a metric without a hardcoded dictionary.
    """
    meta = {}
    if not isinstance(response, dict):
        return meta
    for entry in response.get("metrics") or []:
        if not isinstance(entry, dict):
            continue
        key = entry.get("id") or entry.get("metricId")
        if key is None:
            continue
        meta[str(key)] = {"title": entry.get("title"), "type": entry.get("type")}
    return meta


def extract_daily_series(response, start=None, end=None):
    """
    Turn the response into {"YYYY-MM-DD": {id: value}} using each metric's
    `charts.current` series.

    Chart points are {"x": <day of year>, "y": <value>} -- a standard 1-based
    ordinal day within the year, not a day of month and not a timestamp.
    Verified by matching chart values against orders_table, which carries real
    dates: x=252 is 2026-09-09, whose day-of-year is 252.

    The year is not stated anywhere in the response, so it is taken from the
    requested window. The series also carries one day either side of what was
    asked for, so points outside the window are dropped rather than written
    under a wrong date.
    """
    if not isinstance(response, dict):
        return {}
    metrics = response.get("metrics")
    if not isinstance(metrics, list):
        return {}

    end_date = getdate(end or today())
    start_date = getdate(start) if start else getdate(add_days(end_date, -30))

    # A window spanning a year boundary would make one ordinal ambiguous, so
    # candidate years are taken from the window itself.
    years = {start_date.year, end_date.year}

    by_day = {}
    for entry in metrics:
        if not isinstance(entry, dict):
            continue
        key = entry.get("id") or entry.get("metricId")
        charts = (entry.get("charts") or {}).get("current")
        if key is None or not isinstance(charts, list):
            continue

        for point in charts:
            if not isinstance(point, dict):
                continue
            stamp = _ordinal_to_date(point.get("x"), years, start_date, end_date)
            if stamp:
                by_day.setdefault(stamp, {})[str(key)] = point.get("y")

    return by_day


def _ordinal_to_date(x, years, start_date, end_date):
    """Resolve a day-of-year ordinal to a YYYY-MM-DD inside the window."""
    if x is None:
        return None
    try:
        ordinal = int(x)
    except (TypeError, ValueError):
        return None
    if not 1 <= ordinal <= 366:
        return None

    for year in sorted(years):
        try:
            candidate = datetime.date(year, 1, 1) + datetime.timedelta(days=ordinal - 1)
        except ValueError:
            continue
        if candidate.year == year and start_date <= candidate <= end_date:
            return str(candidate)
    return None


def upsert(metric_date, payload, meta=None, active=None):
    """Write one day's metrics. Returns True when a new row was created."""
    existing = frappe.db.exists("Triple Whale Daily Metric", {"metric_date": metric_date})
    if existing:
        doc = frappe.get_doc("Triple Whale Daily Metric", existing)
        is_new = False
    else:
        doc = frappe.new_doc("Triple Whale Daily Metric")
        doc.metric_date = metric_date
        is_new = True

    for source, target in SUMMARY_FIELD_MAP.items():
        value = as_float(payload.get(source))
        if value is not None:
            doc.set(target, value)

    _set_all_metrics(doc, payload, meta or {}, active)
    doc.raw_payload = json.dumps(payload, default=str)[:140000]

    doc.save(ignore_permissions=True)
    return is_new


def _set_all_metrics(doc, payload, meta, active=None):
    """
    Fill the All Metrics child table with every metric this account reports.

    Only metrics absent from `active` are skipped, and a metric is absent only
    when it was zero on every day of the window -- the signature of an
    integration that is not connected. Everything else stores, zeros included,
    so a day when a connected channel spent nothing is recorded as the zero it
    genuinely is rather than vanishing.
    """
    doc.set("all_metrics", [])
    for metric_id, value in sorted(payload.items()):
        if active is not None and metric_id not in active:
            continue
        if value is None:
            continue
        info = meta.get(metric_id) or {}
        number = as_float(value)
        row = {
            "metric_id": metric_id,
            "title": info.get("title") or "",
            "value_type": info.get("type") or "",
        }
        # A handful of metrics (the pacing forecasts) are string-typed. Keeping
        # the raw text means a non-numeric answer is recorded rather than
        # dropped for failing to parse as a number.
        if number is None:
            row["text_value"] = str(value)[:140]
        else:
            row["value"] = number
        doc.append("all_metrics", row)
