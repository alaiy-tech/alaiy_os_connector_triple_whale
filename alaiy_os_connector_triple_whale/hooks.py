app_name = "alaiy_os_connector_triple_whale"
app_title = "Alaiy Os Connector Triple Whale"
app_publisher = "Alaiy"
app_description = "Triple Whale analytics connector for Alaiy OS"
app_email = "mail@alaiy.com"
app_license = "agpl-3.0"

# ---------------------------------------------------------------------------
# Dependencies
# ---------------------------------------------------------------------------
# Every Alaiy OS connector runs on top of alaiy_os (registry, workspace,
# connector card) and erpnext (Item, Sales Order, Warehouse, ...).
required_apps = ["alaiy_os", "erpnext"]

# ---------------------------------------------------------------------------
# Installation / migration
# ---------------------------------------------------------------------------
# after_install runs once on `bench install-app`; after_migrate runs on every
# `bench migrate`. sync_connector_registry() (re)registers this connector in
# alaiy_os's OS Connector Registry and is idempotent, so it is safe on migrate.
after_install = [
    "alaiy_os_connector_triple_whale.setup.install.after_install"
]

after_migrate = [
    "alaiy_os_connector_triple_whale.setup.install.sync_connector_registry"
]

# ---------------------------------------------------------------------------
# Alaiy OS sidebar
# ---------------------------------------------------------------------------
# Register this connector's Sync Log under the Alaiy OS "Logs" sidebar section.
# alaiy_os reads this hook in create_or_update_workspace_sidebar().
alaiy_os_sidebar_log_items = [
    {
        "link_type": "DocType",
        "link_to": "Triple Whale Sync Log",
        "label": "Triple Whale Logs",
        "icon": "activity",
    }
]

# Extra rows under this connector's own top-level sidebar section (Dashboard
# is always added automatically by alaiy_os).
alaiy_os_sidebar_connector_items = [
    {
        "connector_id": "triple_whale",
        "link_type": "DocType",
        "link_to": "Triple Whale Daily Metric",
        "label": "Daily Metrics",
        "icon": "calendar",
    },
    {
        "connector_id": "triple_whale",
        "link_type": "DocType",
        "link_to": "Triple Whale Product Metric",
        "label": "Product Metrics",
        "icon": "box",
    },
]

# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------
# Runs every minute; check_and_enqueue() decides whether any sync is actually
# due based on the intervals configured in Triple Whale Connector Settings.
scheduler_events = {
    "cron": {
        "* * * * *": [
            "alaiy_os_connector_triple_whale.triple_whale.sync_jobs.check_and_enqueue"
        ]
    }
}
