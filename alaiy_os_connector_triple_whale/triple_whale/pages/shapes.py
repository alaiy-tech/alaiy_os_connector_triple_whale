# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Shapes warehouse rows into table rows for the page traffic sync. Stdlib only."""

from alaiy_os_connector_triple_whale.triple_whale.pages.paths import clean_path, handle_for, page_type_for


def _int(value):
    try:
        return int(float(value)) if value not in (None, "") else 0
    except (TypeError, ValueError):
        return 0


def merge_clicks(page_values, click_rows):
    """Set clicked_through on each collection page row from the click-through
    rows, matched by day and page. Other rows keep 0."""
    clicked = {}
    for row in click_rows:
        date = str(row.get("event_date") or "")[:10]
        path = clean_path(row.get("page"))
        if date:
            clicked[(date, path)] = clicked.get((date, path), 0) + _int(row.get("clicked"))
    for value in page_values:
        value["clicked_through"] = clicked.get((value["metric_date"], value["page_path"]), 0) \
            if value["page_type"] == "collection" else 0
    return page_values


def traffic_values(rows):
    """Traffic Metric rows: sessions per day, page and traffic source."""
    values = []
    for row in rows:
        date = str(row.get("event_date") or "")[:10]
        path = clean_path(row.get("page"))
        if not date:
            continue
        values.append({
            "metric_date": date,
            "page_type": page_type_for(path),
            "page_path": path,
            "handle": handle_for(path),
            "traffic_source": str(row.get("traffic_source") or "Other")[:140],
            "sessions": _int(row.get("sessions")),
            "new_visitors": _int(row.get("new_visitors")),
        })
    return values
