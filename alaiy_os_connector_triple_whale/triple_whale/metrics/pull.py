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
        by_day = extract_daily_series(response, start, end)

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
