# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Per-product metrics -> Triple Whale Product Metric.

There is no per-product REST endpoint; product-level figures come from SQL
against Triple Whale's warehouse tables. The query itself lives in queries.py.
"""

import frappe

from alaiy_os_connector_triple_whale.triple_whale.attribution.queries import (
    PRODUCT_METRICS_QUERY,
)
from alaiy_os_connector_triple_whale.triple_whale.auth import (
    TripleWhaleAPIError,
    TripleWhaleClient,
)
from alaiy_os_connector_triple_whale.triple_whale.sync_log import run_logged
from alaiy_os_connector_triple_whale.triple_whale.window import as_float, sync_window

# Warehouse column -> Triple Whale Product Metric fieldname. product_id and
# variant_id are part of the row key and handled separately in upsert().
SQL_FIELD_MAP = {
    "sku": "sku",
    "product_title": "product_title",
    "variant_title": "variant_title",
    "vendor": "vendor",
    "product_status": "product_status",
    "total_items_sold": "units_sold",
    "revenue": "product_revenue",
    "orders": "orders",
    "spend": "attributed_spend",
    "visits": "product_views",
    "added_to_cart_items": "add_to_carts",
    "clicks": "clicks",
    "impressions": "impressions",
    "returns": "refunded_amount",
    "new_customer_revenue": "new_customer_revenue",
    "new_customer_orders": "new_customer_orders",
}

_TEXT_FIELDS = ("sku", "product_title", "variant_title", "vendor", "product_status")

# SKU -> Item name for the duration of one sync. A sync re-fetches a rolling
# window, so the same SKU recurs once per day in the window; without this each
# repeat costs up to four queries. Sentinel distinguishes "looked up, no match"
# from "not looked up yet", so unmatched SKUs are not retried either.
_MISSING = object()
_item_cache = {}


def run(trigger="scheduled", log_name=None):
    """Pull per-product metrics for the sync window via warehouse SQL."""

    def worker(log):
        _item_cache.clear()

        client = TripleWhaleClient()
        start, end = sync_window()
        rows = extract_rows(client.sql(PRODUCT_METRICS_QUERY, start, end))

        log.pages_total = 1
        log.pages_done = 1
        log.items_processed = len(rows)

        created = updated = failed = 0
        for row in rows:
            try:
                if upsert(row):
                    created += 1
                else:
                    updated += 1
            except Exception:
                failed += 1
                frappe.log_error(
                    title="Triple Whale connector: product metric upsert failed",
                    message=f"{frappe.get_traceback()}\n\nRow: {row}",
                )

        log.items_created = created
        log.items_updated = updated
        log.items_failed = failed
        log.log_messages = _match_summary()
        frappe.db.commit()

    run_logged("attribution", trigger, log_name, worker)


def _match_summary():
    """
    Report how many distinct SKUs resolved to an Item.

    A low rate is the difference between "this supplier sold nothing" and
    "their SKUs do not line up with Triple Whale's", which is otherwise
    invisible -- unmatched rows still store fine, they just never join.
    """
    total = len(_item_cache)
    if not total:
        return "No SKUs seen."

    unmatched = sorted(s for s, item in _item_cache.items() if not item)
    matched = total - len(unmatched)
    lines = [f"SKU to Item: {matched}/{total} matched."]
    if unmatched:
        shown = ", ".join(unmatched[:50])
        lines.append(f"Unmatched ({len(unmatched)}): {shown}")
        if len(unmatched) > 50:
            lines.append(f"...and {len(unmatched) - 50} more.")
    return "\n".join(lines)


def extract_rows(response):
    """
    Pull the result rows out of an /orcabase/api/sql response.

    A successful query returns a bare JSON array of row objects, despite the
    published spec describing a {"success", "message", "data"} envelope. Both
    are handled: the envelope form still appears on failures, where `message`
    carries the reason and is raised rather than being treated as an empty
    result -- a malformed query would otherwise look like a period with no
    sales.
    """
    if isinstance(response, list):
        return [r for r in response if isinstance(r, dict)]

    if not isinstance(response, dict):
        raise TripleWhaleAPIError(
            f"Unexpected SQL response type: {type(response).__name__}"
        )

    if response.get("success") is False or response.get("message"):
        raise TripleWhaleAPIError(
            f"SQL query rejected: {response.get('message') or 'no reason given'}"
        )

    rows = response.get("data")
    if not isinstance(rows, list):
        return []
    return [r for r in rows if isinstance(r, dict)]


def upsert(row):
    """Write one product-day row. Returns True when a new row was created."""
    metric_date = str(row.get("event_date") or row.get("date") or "")[:10]
    product_id = row.get("product_id")
    if not metric_date or not product_id:
        raise ValueError("Row is missing event_date or product_id")

    variant_id = str(row.get("variant_id") or "")
    key = {
        "metric_date": metric_date,
        "product_id": str(product_id),
        "variant_id": variant_id,
    }
    existing = frappe.db.exists("Triple Whale Product Metric", key)
    if existing:
        doc = frappe.get_doc("Triple Whale Product Metric", existing)
        is_new = False
    else:
        doc = frappe.new_doc("Triple Whale Product Metric")
        doc.metric_date = metric_date
        doc.product_id = str(product_id)
        doc.variant_id = variant_id
        is_new = True

    for source, target in SQL_FIELD_MAP.items():
        value = row.get(source)
        if value in (None, ""):
            continue
        if source in _TEXT_FIELDS:
            doc.set(target, str(value))
        else:
            numeric = as_float(value)
            if numeric is not None:
                doc.set(target, numeric)

    _set_derived_rates(doc, row)
    doc.item = resolve_item(row.get("sku"))
    doc.save(ignore_permissions=True)
    return is_new


def _set_derived_rates(doc, row):
    """
    Rates are computed here rather than in SQL so a zero denominator yields a
    blank field instead of failing the whole query.
    """
    views = as_float(row.get("visits")) or 0
    carts = as_float(row.get("added_to_cart_items")) or 0
    orders = as_float(row.get("orders")) or 0
    revenue = as_float(row.get("revenue")) or 0
    spend = as_float(row.get("spend")) or 0
    returned = as_float(row.get("returns")) or 0

    doc.conversion_rate = (orders / views * 100) if views else None
    doc.add_to_cart_rate = (carts / views * 100) if views else None
    # The warehouse reports spend at product grain but not a separate
    # ad-attributed revenue column, so ROAS here is product revenue over the
    # ad spend attributed to that product.
    doc.attributed_roas = (revenue / spend) if spend else None
    doc.return_rate = (returned / revenue * 100) if revenue else None


def resolve_item(sku):
    """
    Map a Triple Whale SKU onto an Alaiy OS Item.

    Triple Whale reports on everything the store sells, which can include
    products Alaiy OS does not carry, so an unmatched SKU is expected and
    leaves the link blank rather than failing the row.

    Matching is tried in order of decreasing confidence: the Item name, then
    item_code, then the barcode child table, then a case-insensitive
    item_code. The case-insensitive pass is last because it can in principle
    match more than one Item, in which case the row is left unlinked rather
    than guessing.
    """
    if not sku:
        return None
    sku = str(sku).strip()
    if not sku:
        return None

    cached = _item_cache.get(sku)
    if cached is not _MISSING:
        return cached

    resolved = (
        frappe.db.get_value("Item", sku, "name")
        or frappe.db.get_value("Item", {"item_code": sku}, "name")
        or frappe.db.get_value("Item Barcode", {"barcode": sku}, "parent")
        or _match_case_insensitive(sku)
    )
    _item_cache[sku] = resolved
    return resolved


def _match_case_insensitive(sku):
    matches = frappe.db.sql(
        "SELECT name FROM `tabItem` WHERE LOWER(item_code) = LOWER(%s) LIMIT 2",
        (sku,),
    )
    return matches[0][0] if len(matches) == 1 else None
