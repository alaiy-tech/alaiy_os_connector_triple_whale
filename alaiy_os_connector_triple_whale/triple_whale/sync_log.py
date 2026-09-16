# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Triple Whale Sync Log lifecycle, shared by every sync.

Kept separate from the syncs themselves so the queued -> running ->
success/failed bookkeeping has one implementation; the connector card and the
Logs list depend on log status being accurate even when a sync throws.
"""

import frappe
from frappe.utils import now_datetime


def get_or_create_log(sync_type, trigger, log_name=None):
    """
    Return the Sync Log to use for this run. If log_name is given (the API
    layer pre-created it so it shows as 'queued' immediately) reuse it;
    otherwise create a fresh one. Newly created logs start as 'queued'.
    """
    if log_name and frappe.db.exists("Triple Whale Sync Log", log_name):
        return frappe.get_doc("Triple Whale Sync Log", log_name)

    log = frappe.new_doc("Triple Whale Sync Log")
    log.sync_type = sync_type
    log.trigger = trigger
    log.status = "queued"
    log.insert(ignore_permissions=True)
    frappe.db.commit()
    return log


def _mark_running(log):
    log.status = "running"
    log.started_at = now_datetime()
    log.save(ignore_permissions=True)
    frappe.db.commit()


def _mark_finished(log, status, error_message=None):
    log.status = status
    log.finished_at = now_datetime()
    if error_message:
        log.error_message = error_message[:2000]
    log.save(ignore_permissions=True)
    frappe.db.commit()


def run_logged(sync_type, trigger, log_name, worker):
    """
    Run `worker(log)` inside the log lifecycle.

    The exception is re-raised after the log is marked failed so the RQ job
    itself also registers as failed rather than silently succeeding.
    """
    log = get_or_create_log(sync_type, trigger, log_name)
    _mark_running(log)
    try:
        worker(log)
        _mark_finished(log, "success")
    except Exception:
        _mark_finished(log, "failed", frappe.get_traceback())
        frappe.log_error(
            title=f"Triple Whale connector: {sync_type} sync failed",
            message=frappe.get_traceback(),
        )
        raise
