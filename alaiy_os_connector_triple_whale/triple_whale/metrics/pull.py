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

from alaiy_os_connector_triple_whale.triple_whale.auth import TripleWhaleClient
from alaiy_os_connector_triple_whale.triple_whale.sync_log import run_logged
from alaiy_os_connector_triple_whale.triple_whale.window import (
    as_float,
    days_in_range,
    sync_window,
)

# Triple Whale metric name -> Triple Whale Daily Metric fieldname. Triple Whale
# returns far more than this; only the metrics the dashboards consume are
# promoted to columns. The whole payload is kept in raw_payload so a new metric
# can be backfilled without re-fetching.
SUMMARY_FIELD_MAP = {
    "total_sales": "total_sales",
    "gross_product_sales": "gross_sales",
    "order_revenue": "order_revenue",
    "orders": "orders",
    "aov": "aov",
    "new_customer_revenue": "new_customer_revenue",
    "returning_customer_revenue": "returning_customer_revenue",
    "new_customers_percent": "new_customers_percent",
    "spend": "spend",
    "mer": "mer",
    "roas": "blended_roas",
    "blended_cpa": "blended_cpa",
    "ncpa": "ncpa",
    "new_customer_roas": "new_customer_roas",
    "net_profit": "net_profit",
    "net_margin": "net_margin",
    "cost_of_goods": "cost_of_goods",
    "poas": "poas",
    "total_refunded_price": "total_refunded_price",
    "returns_percent": "returns_percent",
}


def run(trigger="scheduled", log_name=None):
    """Pull store-wide summary metrics for every day in the sync window."""

    def worker(log):
        client = TripleWhaleClient()
        start, end = sync_window()
        days = days_in_range(start, end)

        log.pages_total = len(days)
        log.pages_done = 0
        created = updated = failed = 0

        for day in days:
            try:
                payload = extract_metrics(client.summary_page(day, day))
                if payload:
                    if upsert(day, payload):
                        created += 1
                    else:
                        updated += 1
            except Exception:
                failed += 1
                frappe.log_error(
                    title="Triple Whale connector: summary fetch failed",
                    message=f"{frappe.get_traceback()}\n\nDate: {day}",
                )
            log.pages_done += 1

        log.items_processed = len(days)
        log.items_created = created
        log.items_updated = updated
        log.items_failed = failed
        frappe.db.commit()

    run_logged("metrics", trigger, log_name, worker)


def extract_metrics(response):
    """
    Flatten the Summary Page response into {metricName: value}.

    The documented shape is {"metrics": [{"metricName": ..., "value": ...}]};
    a plain object under the same key is accepted too rather than silently
    yielding nothing.
    """
    if not isinstance(response, dict):
        return {}

    metrics = response.get("metrics")
    if isinstance(metrics, list):
        flat = {}
        for entry in metrics:
            if isinstance(entry, dict) and entry.get("metricName") is not None:
                flat[str(entry["metricName"])] = entry.get("value")
        return flat
    if isinstance(metrics, dict):
        return metrics
    return {}


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
