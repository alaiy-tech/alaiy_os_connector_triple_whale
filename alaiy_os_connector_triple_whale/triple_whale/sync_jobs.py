# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Scheduler entry point. hooks.py runs check_and_enqueue() every minute; it
reads the configured intervals from Triple Whale Connector Settings and
enqueues a background job per sync type only when one is actually due.
"""

import frappe
from frappe.utils import add_to_date, now_datetime

_INTERVAL_MINUTES = {
    "Hourly": 60,
    "Daily": 1440,
}

# A sync that has been "running" longer than this is treated as dead, so a
# crashed job never blocks the schedule forever. Set above the job timeout so
# a slow-but-alive sync is never double-enqueued.
_STALE_RUNNING_SECONDS = 3600


def check_and_enqueue():
    if not frappe.db.exists("DocType", "Triple Whale Sync Log"):
        return

    settings = frappe.get_single("Triple Whale Connector Settings")
    if not settings.is_enabled:
        return

    _maybe_enqueue(
        interval_setting=settings.triple_whale_metrics_sync_interval or "Disabled",
        sync_type="metrics",
        enqueue_fn="alaiy_os_connector_triple_whale.triple_whale.metrics.pull.run",
    )
    _maybe_enqueue(
        interval_setting=settings.triple_whale_attribution_sync_interval or "Disabled",
        sync_type="attribution",
        enqueue_fn="alaiy_os_connector_triple_whale.triple_whale.attribution.pull.run",
    )


def _maybe_enqueue(interval_setting, sync_type, enqueue_fn):
    interval_minutes = _INTERVAL_MINUTES.get(interval_setting)
    if not interval_minutes:  # "Disabled" or anything unrecognised
        return

    now = now_datetime()

    # Skip if a (non-stale) job is already running for this sync type.
    running = frappe.db.get_value(
        "Triple Whale Sync Log",
        {"sync_type": sync_type, "status": "running"},
        "started_at",
        order_by="started_at desc",
    )
    if running and (now - running).total_seconds() < _STALE_RUNNING_SECONDS:
        return

    # Skip if the last success is still inside the configured interval.
    last_success = frappe.db.get_value(
        "Triple Whale Sync Log",
        {"sync_type": sync_type, "status": "success"},
        "started_at",
        order_by="started_at desc",
    )
    if last_success and now < add_to_date(last_success, minutes=interval_minutes):
        return

    frappe.enqueue(enqueue_fn, queue="long", timeout=900, trigger="scheduled")
