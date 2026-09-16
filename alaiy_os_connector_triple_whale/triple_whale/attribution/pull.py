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

# SQL column -> Triple Whale Product Metric fieldname. product_id/variant_id
# are part of the row key and handled separately in upsert().
SQL_FIELD_MAP = {
    "sku": "sku",
    "product_title": "product_title",
    "units_sold": "units_sold",
    "product_revenue": "product_revenue",
    "orders": "orders",
    "attributed_revenue": "attributed_revenue",
    "attributed_spend": "attributed_spend",
    "product_views": "product_views",
    "add_to_carts": "add_to_carts",
    "refunded_amount": "refunded_amount",
    "refunded_units": "refunded_units",
}

_TEXT_FIELDS = ("sku", "product_title")


def run(trigger="scheduled", log_name=None):
    """Pull per-product metrics for the sync window via warehouse SQL."""

    def worker(log):
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
        frappe.db.commit()

    run_logged("attribution", trigger, log_name, worker)


def extract_rows(response):
    """
    Pull the result rows out of an /orcabase/api/sql response.

    The documented shape is {"success": bool, "message": str, "data": [...]}.
    A success:false body carries the reason in `message`, which is raised
    rather than treated as an empty result -- a malformed query would
    otherwise look like a period with no sales.
    """
    if not isinstance(response, dict):
        raise TripleWhaleAPIError(
            f"Unexpected SQL response type: {type(response).__name__}"
        )

    if response.get("success") is False:
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
    views = as_float(row.get("product_views")) or 0
    carts = as_float(row.get("add_to_carts")) or 0
    orders = as_float(row.get("orders")) or 0
    revenue = as_float(row.get("product_revenue")) or 0
    spend = as_float(row.get("attributed_spend")) or 0
    attributed = as_float(row.get("attributed_revenue")) or 0
    refunded = as_float(row.get("refunded_amount")) or 0

    doc.conversion_rate = (orders / views * 100) if views else None
    doc.add_to_cart_rate = (carts / views * 100) if views else None
    doc.attributed_roas = (attributed / spend) if spend else None
    doc.return_rate = (refunded / revenue * 100) if revenue else None


def resolve_item(sku):
    """
    Map a Triple Whale SKU onto an Alaiy OS Item.

    Triple Whale reports on everything the store sells, which can include
    products Alaiy OS does not carry, so an unmatched SKU is expected and
    leaves the link blank rather than failing the row.
    """
    if not sku:
        return None
    sku = str(sku).strip()
    if frappe.db.exists("Item", sku):
        return sku
    return frappe.db.get_value("Item", {"item_code": sku}, "name")
