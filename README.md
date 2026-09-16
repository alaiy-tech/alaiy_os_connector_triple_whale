# Alaiy OS Connector — Triple Whale

Pulls marketing analytics, attribution and profitability metrics from
[Triple Whale](https://triplewhale.com) into Alaiy OS, for the Admin and
Supplier dashboards.

This connector is **read-only**. Nothing is ever written back to Triple Whale.

## What it pulls

Two sync slots, both inbound:

| Slot | Source | Lands in |
|---|---|---|
| **Metrics** | `POST /summary-page/get-data` | `Triple Whale Daily Metric` — one row per day, store-wide |
| **Attribution** | `POST /orcabase/api/sql` | `Triple Whale Product Metric` — one row per product per day |

Both run nightly by default. Triple Whale's summary figures are aggregate and
settle overnight, so there is nothing to gain from a tighter schedule.

## The API surface

Base URL `https://api.triplewhale.com/api/v2`, authenticated with an
**`x-api-key`** header. A personal API key reaches exactly four endpoints:

| Endpoint | Used for |
|---|---|
| `GET /users/api-keys/me` | Test Connection |
| `POST /summary-page/get-data` | Metrics sync |
| `POST /orcabase/api/sql` | Attribution sync (product-level) |
| `POST /attribution/get-orders-with-journeys-v2` | Order-level journeys (not yet used) |

There is no per-product REST endpoint. Product-level figures come from SQL
against Triple Whale's warehouse tables (`product_analytics_table`,
`orders_table`, `refunds_table`, `ads_table`), which is why the attribution
slot issues a SQL query rather than a plain GET.

Full reference material — OpenAPI specs, the table/metric catalogue, rate
limits, scopes, and Triple Whale's own sample apps — is kept in
`docs/triple_whale/` at the repo root.

## Layout

Shared plumbing sits at the top of `triple_whale/`; each domain gets its own
package, the same way the Shopify connector splits `order/` and `product/`.

```
triple_whale/
├── auth.py            API client -- credentials, headers, retry/backoff
├── sync_log.py        Sync Log lifecycle (queued -> running -> success/failed)
├── window.py          Date window + numeric coercion shared by both syncs
├── sync_jobs.py       Scheduler -- decides what is due
├── metrics/
│   └── pull.py        Summary Page -> Triple Whale Daily Metric
└── attribution/
    ├── queries.py     Warehouse SQL
    └── pull.py        SQL results -> Triple Whale Product Metric
```

Each `pull.py` owns its own field mapping (`SUMMARY_FIELD_MAP`,
`SQL_FIELD_MAP`) because the two read from different sources into different
doctypes; there is no overlap to share.

## Setup

1. Generate an API key at <https://app.triplewhale.com/api-keys>.
   Required scopes: **Summary Page: Read**, **Pixel Attribution: Read**, and
   the **Data Out** scope covering the SQL endpoint.
2. Install and migrate:
   ```bash
   bench get-app alaiy_os_connector_triple_whale /path/to/this/repo
   bench --site <site> install-app alaiy_os_connector_triple_whale
   bench --site <site> migrate
   bench build --app alaiy_os_connector_triple_whale
   ```
3. Open **Triple Whale Connector Settings**, paste the API key, set the shop
   domain (the `myshopify.com` domain registered with Triple Whale), and tick
   Enable.
4. Run **Test Connection**. On success it reports the scopes the key carries.

### Scope caveat

The key-creation UI lists `Summary Page: Read` and `Pixel Attribution: Read`,
but Triple Whale's troubleshooting guide references a separate `Data Out` scope
covering the SQL endpoint that does not appear in that picker. The attribution
sync depends entirely on SQL access. Test Connection prints the granted scopes
so this can be confirmed before relying on product-level data.

### Rate limits

Triple Whale does not publish rate limits for the Data-Out endpoints, and
responses carry no remaining-counter header. The client retries on 429 and 5xx
with exponential backoff, honouring `Retry-After` when present.

## Settings

| Field | Purpose |
|---|---|
| API Key | Personal API key, stored encrypted. |
| Shop Domain | The `myshopify.com` domain registered with Triple Whale. Sent as `shopDomain`/`shopId`. |
| Currency | Aggregation currency. Defaults to the Triple Whale account currency when blank. |
| Company | Alaiy OS company the figures belong to. |
| Metrics / Attribution Sync Interval | `Disabled`, `Hourly` or `Daily`. |
| Lookback Days | How far back each sync re-fetches. Attribution is restated for several days after an order, so a window wider than one day is required. Defaults to 7. |

## Why syncs re-fetch a window

Attribution is not final on the day an order lands — Triple Whale continues to
reassign credit as the attribution window closes. A sync that only fetched
yesterday would permanently freeze whatever was known at the time. Instead each
run re-fetches `Lookback Days` and upserts, so late restatements land.

## License

AGPL-3.0 (`license.txt`).
