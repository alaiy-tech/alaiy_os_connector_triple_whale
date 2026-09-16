# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Store-wide summary metrics -> Triple Whale Daily Metric.

The Summary Page endpoint aggregates a whole period into one flat metric list
rather than breaking it down by day, so this calls it once per day in the
window to build a per-day series.
"""

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
    "sales": "order_revenue",           # "Order Revenue": gross - discounts + tax + shipping
    "netSales": "total_sales",          # "Total Sales": gross - discounts - returns + shipping + tax
    "grossSales": "gross_sales",
    "orders": "orders",
    "shopifyAov": "aov",
    "newCustomerSales": "new_customer_revenue",
    "rcRevenue": "returning_customer_revenue",
    "newCustomersPercent": "new_customers_percent",
    "blendedAds": "spend",              # blended spend across every ad platform
    "mer": "mer",
    "roas": "blended_roas",
    "shopifyCpa": "blended_cpa",
    "newCustomersCpa": "ncpa",          # the CAC figure
    "newCustomersRoas": "new_customer_roas",
    "totalNetProfit": "net_profit",
    "totalNetMargin": "net_margin",
    "cogs": "cost_of_goods",
    "poas": "poas",
    "totalRefunds": "total_refunded_price",
    "totalReturns": "returns_percent",
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
        by_day = extract_daily_series(response)

        log.pages_total = 1
        log.pages_done = 1
        log.items_processed = len(by_day)

        created = updated = 0
        for day, payload in sorted(by_day.items()):
            if upsert(day, payload):
                created += 1
            else:
                updated += 1

        log.items_created = created
        log.items_updated = updated
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


def extract_daily_series(response):
    """
    Turn the response into {"YYYY-MM-DD": {id: value}} using each metric's
    `charts.current` series.

    Chart points are {"x": <day of month>, "y": <value>}. The endpoint answers
    month-to-date regardless of the range asked for, so the month those days
    belong to is taken from the largest x seen: it is the most recent day with
    data, which cannot be in the future.
    """
    if not isinstance(response, dict):
        return {}
    metrics = response.get("metrics")
    if not isinstance(metrics, list):
        return {}

    today_date = getdate(today())
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
            day = point.get("x")
            if day is None:
                continue
            try:
                day = int(day)
            except (TypeError, ValueError):
                continue
            if not 1 <= day <= 31:
                continue

            # A day number above today's means the series belongs to last
            # month -- the API never reports days that have not happened.
            month_ref = today_date
            if day > today_date.day:
                month_ref = getdate(add_days(today_date.replace(day=1), -1))
            try:
                stamp = str(month_ref.replace(day=day))
            except ValueError:
                continue

            by_day.setdefault(stamp, {})[str(key)] = point.get("y")

    return by_day


def upsert(metric_date, payload):
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

    channels = payload.get("channels") or payload.get("by_channel")
    if channels:
        doc.channel_breakdown = json.dumps(channels, default=str)[:140000]
    doc.raw_payload = json.dumps(payload, default=str)[:140000]

    doc.save(ignore_permissions=True)
    return is_new
