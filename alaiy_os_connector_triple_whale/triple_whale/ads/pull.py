# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Per-channel ad performance -> Triple Whale Ad Metric.

One row per channel per day, covering every ad platform the account connects.
Nothing here is platform-specific: Meta, Google, TikTok and anything added
later arrive on their own rows without a schema change.
"""

import frappe

from alaiy_os_connector_triple_whale.triple_whale.ads.queries import CHANNEL_METRICS_QUERY
from alaiy_os_connector_triple_whale.triple_whale.cohorts.queries import (
    REFUNDS_BY_CHANNEL_QUERY,
)
from alaiy_os_connector_triple_whale.triple_whale.attribution.pull import extract_rows
from alaiy_os_connector_triple_whale.triple_whale.auth import TripleWhaleClient
from alaiy_os_connector_triple_whale.triple_whale.sync_log import run_logged
from alaiy_os_connector_triple_whale.triple_whale.window import as_float, sync_window

SQL_FIELD_MAP = {
    "currency": "currency",
    "spend": "spend",
    "impressions": "impressions",
    "clicks": "clicks",
    "conversions": "conversions",
    "conversion_value": "conversion_value",
    "reach": "reach",
    "outbound_clicks": "outbound_clicks",
    "visits": "visits",
    "engagements": "engagements",
}

_TEXT_FIELDS = ("currency",)


def run(trigger="scheduled", log_name=None):
    """Pull per-channel ad metrics for the sync window."""

    def worker(log):
        client = TripleWhaleClient()
        start, end = sync_window()
        rows = extract_rows(client.sql(CHANNEL_METRICS_QUERY, start, end))
        refunds = _refunds_by_channel(client, start, end)

        log.pages_total = 2
        log.pages_done = 2
        log.items_processed = len(rows)

        created = updated = failed = 0
        channels = set()
        for row in rows:
            try:
                if upsert(row, refunds):
                    created += 1
                else:
                    updated += 1
                if row.get("channel"):
                    channels.add(str(row["channel"]))
            except Exception:
                failed += 1
                frappe.log_error(
                    title="Triple Whale connector: ad metric upsert failed",
                    message=f"{frappe.get_traceback()}\n\nRow: {row}",
                )

        log.items_created = created
        log.items_updated = updated
        log.items_failed = failed
        log.log_messages = (
            f"Channels: {', '.join(sorted(channels))}" if channels else "No channels reported."
        )
        frappe.db.commit()

    run_logged("ads", trigger, log_name, worker)


def _refunds_by_channel(client, start, end):
    """
    Refunded value keyed by (date, channel).

    Fetched alongside the spend figures so a channel's return rate sits beside
    what it cost, which is the comparison that matters: a channel can look
    efficient on ROAS while quietly returning most of what it sells.
    """
    refunds = {}
    for row in extract_rows(client.sql(REFUNDS_BY_CHANNEL_QUERY, start, end)):
        date = str(row.get("event_date") or "")[:10]
        channel = row.get("channel")
        if date and channel:
            refunds[(date, str(channel))] = row
    return refunds


def upsert(row, refunds=None):
    """Write one channel-day row. Returns True when a new row was created."""
    metric_date = str(row.get("event_date") or "")[:10]
    channel = row.get("channel")
    if not metric_date or not channel:
        raise ValueError("Row is missing event_date or channel")

    key = {"metric_date": metric_date, "channel": str(channel)}
    existing = frappe.db.exists("Triple Whale Ad Metric", key)
    if existing:
        doc = frappe.get_doc("Triple Whale Ad Metric", existing)
        is_new = False
    else:
        doc = frappe.new_doc("Triple Whale Ad Metric")
        doc.metric_date = metric_date
        doc.channel = str(channel)
        is_new = True

    for source, target in SQL_FIELD_MAP.items():
        value = row.get(source)
        if value in (None, ""):
            continue
        if source in _TEXT_FIELDS:
            doc.set(target, str(value))
        else:
            number = as_float(value)
            if number is not None:
                doc.set(target, number)

    _set_refunds(doc, (refunds or {}).get((metric_date, str(channel))))
    _set_derived_rates(doc, row)
    doc.save(ignore_permissions=True)
    return is_new


def _set_refunds(doc, refund_row):
    """
    Attach this channel's share of refunds.

    Refund values arrive negative from the warehouse; they are stored as
    positive amounts so the field reads as "how much came back" rather than
    requiring the reader to interpret a sign.
    """
    if not refund_row:
        doc.refunded = 0
        doc.refunded_cogs = 0
        doc.refunded_orders = 0
        return

    doc.refunded = abs(as_float(refund_row.get("refunded")) or 0)
    doc.refunded_cogs = abs(as_float(refund_row.get("refunded_cogs")) or 0)
    doc.refunded_orders = abs(as_float(refund_row.get("refunded_orders")) or 0)


def _set_derived_rates(doc, row):
    """
    Derived after the channel roll-up rather than in SQL, so these are true
    period rates rather than an average of per-ad averages, and a zero
    denominator leaves the field blank instead of failing the query.
    """
    spend = as_float(row.get("spend")) or 0
    clicks = as_float(row.get("clicks")) or 0
    impressions = as_float(row.get("impressions")) or 0
    conversions = as_float(row.get("conversions")) or 0
    conversion_value = as_float(row.get("conversion_value")) or 0

    doc.ctr = (clicks / impressions * 100) if impressions else None
    doc.cpc = (spend / clicks) if clicks else None
    doc.cpm = (spend / impressions * 1000) if impressions else None
    doc.roas = (conversion_value / spend) if spend else None
    doc.cpa = (spend / conversions) if conversions else None

    refunded = as_float(doc.refunded) or 0
    net_value = conversion_value - refunded
    doc.net_conversion_value = net_value
    doc.return_rate = (refunded / conversion_value * 100) if conversion_value else None
    doc.net_roas = (net_value / spend) if spend else None
