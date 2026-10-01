# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Storefront page traffic -> Triple Whale Page Metric and Landing Page Metric.

Page Metric holds true page views per product, collection and other page per
day. Landing Page Metric holds sessions, visitors, bounces and time on site for
the sessions that began on each page. Both are counts only.

These tables are large (a week of journey events is hundreds of thousands of
rows), so unlike the other syncs this one does not save a document per row.
Each window is fetched first, then the dates it covers are replaced in one
step, so a failed fetch leaves the previous data untouched and a re-run is
idempotent.
"""

import frappe
from frappe.utils import add_days, getdate, now_datetime, today

from alaiy_os_connector_triple_whale.triple_whale.attribution.pull import extract_rows
from alaiy_os_connector_triple_whale.triple_whale.auth import TripleWhaleClient
from alaiy_os_connector_triple_whale.triple_whale.pages.paths import clean_path, handle_for, page_type_for
from alaiy_os_connector_triple_whale.triple_whale.pages.queries import (
    CLICK_THROUGH_QUERY,
    LANDING_PAGES_QUERY,
    PAGE_VIEWS_QUERY,
    TRAFFIC_SOURCES_QUERY,
)
from alaiy_os_connector_triple_whale.triple_whale.pages.shapes import merge_clicks, traffic_values
from alaiy_os_connector_triple_whale.triple_whale.sync_log import run_logged
from alaiy_os_connector_triple_whale.triple_whale.window import as_float, sync_window

PAGE_DOCTYPE = "Triple Whale Page Metric"
LANDING_DOCTYPE = "Triple Whale Landing Page Metric"
TRAFFIC_DOCTYPE = "Triple Whale Traffic Metric"

# The first run has no history to extend, so it reaches back this far; later
# runs only re-fetch the configured lookback.
BACKFILL_DAYS = 90
# One query per window keeps each response a manageable size.
CHUNK_DAYS = 7

_PAGE_TYPES = {"product", "collection", "home", "search"}


def windows():
    """[(start, end)] date ranges to fetch, oldest first, never including today
    (a partial day would be restated on the next run anyway)."""
    start, _ = sync_window()
    end = add_days(today(), -1)
    # A table with no rows yet is filled from the full backfill, so a table added
    # later (traffic sources) is populated for the whole history on its first run.
    if not frappe.db.count(PAGE_DOCTYPE) or not frappe.db.count(TRAFFIC_DOCTYPE):
        start = add_days(today(), -BACKFILL_DAYS)
    ranges = []
    cursor = getdate(start)
    last = getdate(end)
    while cursor <= last:
        chunk_end = min(getdate(add_days(cursor, CHUNK_DAYS - 1)), last)
        ranges.append((str(cursor), str(chunk_end)))
        cursor = getdate(add_days(chunk_end, 1))
    return ranges


def run(trigger="scheduled", log_name=None):
    """Pull page views, landing pages, click-through and traffic sources for the sync window."""

    def worker(log):
        client = TripleWhaleClient()
        ranges = windows()
        log.pages_total = len(ranges)
        log.pages_done = 0
        pages = landings = traffic = 0

        for start, end in ranges:
            page_rows = extract_rows(client.sql(PAGE_VIEWS_QUERY, start, end))
            landing_rows = extract_rows(client.sql(LANDING_PAGES_QUERY, start, end))
            click_rows = extract_rows(client.sql(CLICK_THROUGH_QUERY, start, end))
            traffic_rows = extract_rows(client.sql(TRAFFIC_SOURCES_QUERY, start, end))

            pages += _replace(PAGE_DOCTYPE, start, end, merge_clicks(_page_values(page_rows), click_rows))
            landings += _replace(LANDING_DOCTYPE, start, end, _landing_values(landing_rows))
            traffic += _replace(TRAFFIC_DOCTYPE, start, end, traffic_values(traffic_rows))

            log.pages_done += 1
            log.items_processed = pages + landings + traffic
            log.save(ignore_permissions=True)
            frappe.db.commit()

        log.items_created = pages + landings + traffic
        log.items_updated = 0
        log.items_failed = 0
        log.log_messages = f"Page rows: {pages}. Landing page rows: {landings}. Traffic source rows: {traffic}."
        frappe.db.commit()

    run_logged("pages", trigger, log_name, worker)


def _page_values(rows):
    values = []
    for row in rows:
        date = str(row.get("event_date") or "")[:10]
        path = clean_path(row.get("page"))
        page_type = str(row.get("page_type") or "other")
        if not date:
            continue
        values.append({
            "metric_date": date,
            "page_type": page_type if page_type in _PAGE_TYPES else "other",
            "page_path": path,
            "handle": handle_for(path),
            "page_views": int(as_float(row.get("page_views")) or 0),
            "sessions": int(as_float(row.get("sessions")) or 0),
            "clicked_through": 0,
        })
    return values


def _landing_values(rows):
    values = []
    for row in rows:
        date = str(row.get("event_date") or "")[:10]
        path = clean_path(row.get("page"))
        if not date:
            continue
        values.append({
            "metric_date": date,
            "landing_page": path,
            "page_type": page_type_for(path),
            "handle": handle_for(path),
            "sessions": int(as_float(row.get("sessions")) or 0),
            "unique_visitors": int(as_float(row.get("unique_visitors")) or 0),
            "new_visitors": int(as_float(row.get("new_visitors")) or 0),
            "bounces": int(as_float(row.get("bounces")) or 0),
            "page_views": int(as_float(row.get("page_views")) or 0),
            "time_on_site": as_float(row.get("time_on_site")) or 0,
            "add_to_carts": int(as_float(row.get("add_to_carts")) or 0),
            "orders": int(as_float(row.get("orders")) or 0),
            "revenue": as_float(row.get("revenue")) or 0,
        })
    return values


def _replace(doctype, start, end, records):
    """Replace every row of `doctype` dated start..end with `records`.

    Done only after the rows were fetched, so a failed fetch never empties the
    table. bulk_insert needs the standard columns spelled out.
    """
    frappe.db.delete(doctype, {"metric_date": ["between", [start, end]]})
    if not records:
        return 0

    meta_fields = [f for f in records[0]]
    columns = ["name", "creation", "modified", "modified_by", "owner", "docstatus", "idx"] + meta_fields
    stamp = now_datetime()
    rows = [
        [frappe.generate_hash(length=10), stamp, stamp, "Administrator", "Administrator", 0, 0]
        + [record[f] for f in meta_fields]
        for record in records
    ]
    # bulk_insert is limited to a batch size internally; the sync is a
    # background job, so the explicit commit by the caller is the boundary.
    frappe.db.bulk_insert(doctype, columns, rows)
    return len(records)
