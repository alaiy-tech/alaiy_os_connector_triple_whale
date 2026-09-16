# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
The date window each sync covers, shared by both sync types.

Syncs re-fetch a rolling window rather than just yesterday: Triple Whale
restates attribution for several days after an order lands, so a single-day
fetch would permanently freeze whatever was known at the time.
"""

import frappe
from frappe.utils import add_days, getdate, today

DEFAULT_LOOKBACK_DAYS = 7


def sync_window():
    """The date range a sync covers, inclusive, as (start, end) strings."""
    settings = frappe.get_single("Triple Whale Connector Settings")
    lookback = (
        frappe.utils.cint(settings.triple_whale_lookback_days) or DEFAULT_LOOKBACK_DAYS
    )
    end = today()
    return add_days(end, -lookback), end


def days_in_range(start, end):
    """Every date from start to end inclusive, as YYYY-MM-DD strings."""
    days = []
    cursor = getdate(start)
    last = getdate(end)
    while cursor <= last:
        days.append(str(cursor))
        cursor = getdate(add_days(cursor, 1))
    return days


def as_float(value):
    """Coerce an API value to float, or None when it is absent/unparseable."""
    if value in (None, ""):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None
