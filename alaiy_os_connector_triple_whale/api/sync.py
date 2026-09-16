# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Whitelisted entry points the Alaiy OS connector card and the settings form
call to kick off / inspect syncs. These stay thin: create the log so it shows
up as "queued" immediately, then enqueue the real work on the long queue.
"""

import frappe

from alaiy_os_connector_triple_whale.triple_whale.sync_log import get_or_create_log


@frappe.whitelist()
def trigger_metrics_sync():
    """Manually enqueue a store-wide summary metrics pull."""
    log = get_or_create_log("metrics", "manual")
    frappe.enqueue(
        "alaiy_os_connector_triple_whale.triple_whale.metrics.pull.run",
        queue="long",
        timeout=900,
        trigger="manual",
        log_name=log.name,
    )
    return {"queued": True, "log_name": log.name}


@frappe.whitelist()
def trigger_attribution_sync():
    """Manually enqueue a per-product attribution pull."""
    log = get_or_create_log("attribution", "manual")
    frappe.enqueue(
        "alaiy_os_connector_triple_whale.triple_whale.attribution.pull.run",
        queue="long",
        timeout=900,
        trigger="manual",
        log_name=log.name,
    )
    return {"queued": True, "log_name": log.name}


@frappe.whitelist()
def trigger_ads_sync():
    """Manually enqueue a per-channel ad performance pull."""
    log = get_or_create_log("ads", "manual")
    frappe.enqueue(
        "alaiy_os_connector_triple_whale.triple_whale.ads.pull.run",
        queue="long",
        timeout=900,
        trigger="manual",
        log_name=log.name,
    )
    return {"queued": True, "log_name": log.name}


@frappe.whitelist()
def trigger_cohorts_sync():
    """Manually enqueue a cohort retention rebuild."""
    log = get_or_create_log("cohorts", "manual")
    frappe.enqueue(
        "alaiy_os_connector_triple_whale.triple_whale.cohorts.pull.run",
        queue="long",
        timeout=1800,
        trigger="manual",
        log_name=log.name,
    )
    return {"queued": True, "log_name": log.name}


@frappe.whitelist()
def get_sync_status(sync_type=None):
    """
    Return the most recent Triple Whale Sync Log rows, newest first.

    The Alaiy OS connector card passes the registry slot name ("categories"
    or "items"); map those to this connector's own sync_type values.
    """
    filters = {}
    if sync_type:
        type_map = {"categories": "metrics", "items": "attribution"}
        filters["sync_type"] = type_map.get(sync_type, sync_type)
    return frappe.get_all(
        "Triple Whale Sync Log",
        filters=filters,
        fields=[
            "name", "sync_type", "trigger", "status",
            "started_at", "finished_at",
            "items_processed", "items_created", "items_updated", "items_failed",
            "pages_total", "pages_done",
            "error_message",
        ],
        order_by="started_at desc",
        limit=5,
    )
