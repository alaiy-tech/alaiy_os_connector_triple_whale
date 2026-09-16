# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Read endpoints backing the Triple Whale page.

Everything here reads the cached metric doctypes; none of it calls Triple
Whale. The dashboard must stay usable when the API is unreachable, and page
loads should never burn API quota.
"""

import frappe
from frappe.utils import add_days, today


def _window(days):
    days = max(1, min(frappe.utils.cint(days) or 30, 365))
    end = today()
    return add_days(end, -(days - 1)), end


@frappe.whitelist()
def get_overview(days=30):
    """Headline figures for the period, plus the daily series behind them."""
    start, end = _window(days)

    rows = frappe.get_all(
        "Triple Whale Daily Metric",
        filters={"metric_date": ["between", [start, end]]},
        fields=[
            "metric_date", "total_sales", "orders", "spend", "mer",
            "net_profit", "net_margin", "ncpa", "blended_roas",
            "new_customer_revenue", "returning_customer_revenue",
            "total_refunded_price", "returns_percent",
        ],
        order_by="metric_date asc",
    )

    totals = {
        "total_sales": 0.0,
        "orders": 0,
        "spend": 0.0,
        "net_profit": 0.0,
        "new_customer_revenue": 0.0,
        "returning_customer_revenue": 0.0,
        "total_refunded_price": 0.0,
    }
    for r in rows:
        for key in totals:
            totals[key] += r.get(key) or 0

    # Ratios are recomputed from the period totals rather than averaged across
    # days -- averaging a ratio weights a quiet day the same as a peak one.
    sales = totals["total_sales"]
    spend = totals["spend"]
    totals["mer"] = (sales / spend) if spend else None
    totals["poas"] = (totals["net_profit"] / spend) if spend else None
    totals["net_margin"] = (totals["net_profit"] / sales * 100) if sales else None
    totals["returns_percent"] = (
        (totals["total_refunded_price"] / sales * 100) if sales else None
    )
    totals["aov"] = (sales / totals["orders"]) if totals["orders"] else None

    return {
        "period": {"start": start, "end": end, "days": len(rows)},
        "totals": totals,
        "series": rows,
    }


@frappe.whitelist()
def get_top_products(days=30, limit=20, sort_by="product_revenue"):
    """Per-product figures for the period, aggregated across days."""
    start, end = _window(days)

    allowed_sorts = {
        "product_revenue", "units_sold", "attributed_spend",
        "refunded_amount", "new_customer_revenue",
    }
    if sort_by not in allowed_sorts:
        sort_by = "product_revenue"
    limit = max(1, min(frappe.utils.cint(limit) or 20, 200))

    rows = frappe.db.sql(
        f"""
        SELECT
            product_id,
            MAX(sku)           AS sku,
            MAX(product_title) AS product_title,
            MAX(vendor)        AS vendor,
            MAX(item)          AS item,
            SUM(units_sold)           AS units_sold,
            SUM(product_revenue)      AS product_revenue,
            SUM(orders)               AS orders,
            SUM(attributed_spend)     AS attributed_spend,
            SUM(new_customer_revenue) AS new_customer_revenue,
            SUM(product_views)        AS product_views,
            SUM(add_to_carts)         AS add_to_carts,
            SUM(refunded_amount)      AS refunded_amount
        FROM `tabTriple Whale Product Metric`
        WHERE metric_date BETWEEN %(start)s AND %(end)s
        GROUP BY product_id
        ORDER BY {sort_by} DESC
        LIMIT %(limit)s
        """,
        {"start": start, "end": end, "limit": limit},
        as_dict=True,
    )

    # Recomputed from period totals for the same reason as above.
    for r in rows:
        views = r.get("product_views") or 0
        revenue = r.get("product_revenue") or 0
        spend = r.get("attributed_spend") or 0
        r["conversion_rate"] = ((r.get("orders") or 0) / views * 100) if views else None
        r["add_to_cart_rate"] = ((r.get("add_to_carts") or 0) / views * 100) if views else None
        r["attributed_roas"] = (revenue / spend) if spend else None
        r["return_rate"] = ((r.get("refunded_amount") or 0) / revenue * 100) if revenue else None

    return {"period": {"start": start, "end": end}, "products": rows}


@frappe.whitelist()
def get_state():
    """Whether the connector is configured, and when it last synced."""
    settings = frappe.get_single("Triple Whale Connector Settings")
    last = {}
    for sync_type in ("metrics", "attribution"):
        row = frappe.get_all(
            "Triple Whale Sync Log",
            filters={"sync_type": sync_type},
            fields=["name", "status", "started_at", "finished_at", "items_processed"],
            order_by="started_at desc",
            limit=1,
        )
        last[sync_type] = row[0] if row else None

    return {
        "is_enabled": bool(settings.is_enabled),
        "shop_domain": settings.triple_whale_shop_domain,
        "has_key": bool(settings.triple_whale_api_key),
        "lookback_days": settings.triple_whale_lookback_days,
        "last_sync": last,
        "daily_rows": frappe.db.count("Triple Whale Daily Metric"),
        "product_rows": frappe.db.count("Triple Whale Product Metric"),
    }
