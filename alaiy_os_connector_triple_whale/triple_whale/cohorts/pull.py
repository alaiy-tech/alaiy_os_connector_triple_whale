# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Cohort retention -> Triple Whale Cohort.

One row per cohort month per month since acquisition. Retention and realised
LTV are derived here rather than in SQL so a zero denominator leaves a blank
rather than failing the query.
"""

import frappe

from alaiy_os_connector_triple_whale.triple_whale.attribution.pull import extract_rows
from alaiy_os_connector_triple_whale.triple_whale.auth import TripleWhaleClient
from alaiy_os_connector_triple_whale.triple_whale.cohorts.queries import (
    COHORT_RETENTION_QUERY,
)
from alaiy_os_connector_triple_whale.triple_whale.sync_log import run_logged
from alaiy_os_connector_triple_whale.triple_whale.window import as_float, sync_window

# Cohort analysis needs far more history than the daily syncs: a retention
# curve built from one week says nothing. This is deliberately independent of
# the connector's lookback setting, which exists to catch restatements.
COHORT_HISTORY_DAYS = 730

SQL_FIELD_MAP = {
    "cohort_customers": "cohort_customers",
    "active_customers": "active_customers",
    "orders": "orders",
    "revenue": "revenue",
}


def run(trigger="scheduled", log_name=None):
    """Rebuild the cohort table from up to two years of order history."""

    def worker(log):
        client = TripleWhaleClient()
        _, end = sync_window()
        start = frappe.utils.add_days(end, -COHORT_HISTORY_DAYS)

        rows = extract_rows(client.sql(COHORT_RETENTION_QUERY, start, end))
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
                    title="Triple Whale connector: cohort upsert failed",
                    message=f"{frappe.get_traceback()}\n\nRow: {row}",
                )

        _set_cumulative_revenue()

        log.items_created = created
        log.items_updated = updated
        log.items_failed = failed
        log.log_messages = _summary(rows)
        frappe.db.commit()

    run_logged("cohorts", trigger, log_name, worker)


def upsert(row):
    """Write one cohort-month row. Returns True when a new row was created."""
    cohort_month = str(row.get("cohort_month") or "")[:10]
    months_since = row.get("months_since")
    if not cohort_month or months_since is None:
        raise ValueError("Row is missing cohort_month or months_since")

    months_since = int(months_since)
    # A negative offset would mean an order before the customer's first order.
    if months_since < 0:
        raise ValueError(f"Negative months_since ({months_since}) for {cohort_month}")

    key = {"cohort_month": cohort_month, "months_since": months_since}
    existing = frappe.db.exists("Triple Whale Cohort", key)
    if existing:
        doc = frappe.get_doc("Triple Whale Cohort", existing)
        is_new = False
    else:
        doc = frappe.new_doc("Triple Whale Cohort")
        doc.cohort_month = cohort_month
        doc.months_since = months_since
        is_new = True

    for source, target in SQL_FIELD_MAP.items():
        value = as_float(row.get(source))
        if value is not None:
            doc.set(target, value)

    size = as_float(row.get("cohort_customers")) or 0
    active = as_float(row.get("active_customers")) or 0
    revenue = as_float(row.get("revenue")) or 0

    doc.retention_rate = (active / size * 100) if size else None
    # Spread across the whole cohort rather than only those who ordered, so the
    # figure can be compared against CAC, which was paid for every one of them.
    doc.revenue_per_customer = (revenue / size) if size else None

    doc.save(ignore_permissions=True)
    return is_new


def _set_cumulative_revenue():
    """
    Walk each cohort forward, accumulating revenue per customer.

    This is realised LTV: the curve it traces is what acquisition cost has to
    be judged against. It runs as a second pass because a running total cannot
    be computed from one row in isolation.
    """
    rows = frappe.get_all(
        "Triple Whale Cohort",
        fields=["name", "cohort_month", "months_since", "revenue_per_customer"],
        order_by="cohort_month asc, months_since asc",
    )

    running = {}
    for row in rows:
        total = running.get(row.cohort_month, 0.0)
        total += row.revenue_per_customer or 0
        running[row.cohort_month] = total
        frappe.db.set_value(
            "Triple Whale Cohort",
            row.name,
            "cumulative_revenue_per_customer",
            total,
            update_modified=False,
        )


def _summary(rows):
    """State the cohorts covered and how far the curve reaches."""
    if not rows:
        return "No cohorts returned."
    months = {str(r.get("cohort_month"))[:10] for r in rows if r.get("cohort_month")}
    depth = max((int(r.get("months_since") or 0) for r in rows), default=0)
    return (
        f"{len(months)} cohorts, tracked up to {depth} months after acquisition."
    )
