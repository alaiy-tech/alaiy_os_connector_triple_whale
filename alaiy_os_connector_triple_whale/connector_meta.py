"""
Single source of truth for this connector's registration metadata.
Consumed by setup/install.py → upserted into alaiy_os's OS Connector Registry.
"""

connector_meta = {
    "connector_id": "triple_whale",
    "connector_name": "Triple Whale",
    "connector_app": "alaiy_os_connector_triple_whale",
    # Triple Whale is read-only analytics rather than somewhere we sell to or
    # buy from; "channel" is the closer of the two values the registry allows.
    "connector_type": "channel",
    "description": "Marketing analytics, attribution and profitability metrics",
    "icon": "chart-line",
    "icon_url": "",
    "settings_doctype": "Triple Whale Connector Settings",
    "test_method": "alaiy_os_connector_triple_whale.api.test_connection.test_connection",
    # Both registry sync slots pull inbound -- nothing is ever pushed to Triple
    # Whale. Slot 1 is store-wide summary metrics, slot 2 is product-level
    # warehouse data queried over SQL.
    "sync_categories_method": "alaiy_os_connector_triple_whale.api.sync.trigger_metrics_sync",
    "sync_items_method": "alaiy_os_connector_triple_whale.api.sync.trigger_attribution_sync",
    "sync_status_method": "alaiy_os_connector_triple_whale.api.sync.get_sync_status",
    "sync_categories_label": "Metrics",
    "sync_items_label": "Attribution",
    "is_enabled": 0,
    "connection_status": "untested",
}
