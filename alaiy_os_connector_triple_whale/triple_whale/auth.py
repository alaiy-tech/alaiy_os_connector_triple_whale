# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
HTTP client for the Triple Whale Data-Out API, built from Triple Whale
Connector Settings so credentials are read in one place.

Triple Whale authenticates with an `x-api-key` header (not Bearer), and every
data endpoint is POST. An API key reaches only four endpoints; everything this
connector needs is one of them.
"""

import time

import frappe
import requests

API_BASE = "https://api.triplewhale.com/api/v2"

# Data-Out rate limits are not published. Responses carry RateLimit-Policy and,
# on 429, Retry-After -- but no remaining-counter header, so the only workable
# strategy is to retry on 429/5xx and honour Retry-After when it is present.
_MAX_ATTEMPTS = 4
_BACKOFF_BASE_SECONDS = 2
_MAX_RETRY_AFTER_SECONDS = 60


class TripleWhaleAPIError(Exception):
    """Raised when the API returns an error the caller cannot retry past."""


class TripleWhaleClient:
    def __init__(self):
        settings = frappe.get_single("Triple Whale Connector Settings")
        self.api_key = (
            settings.get_password("triple_whale_api_key")
            if settings.triple_whale_api_key
            else None
        )
        self.shop_domain = (settings.triple_whale_shop_domain or "").strip()
        self.currency = (settings.triple_whale_currency or "").strip()
        if not self.api_key:
            raise RuntimeError("Triple Whale connector is not configured (API Key missing).")
        if not self.shop_domain:
            raise RuntimeError("Triple Whale connector is not configured (Shop Domain missing).")

    def _headers(self):
        return {"x-api-key": self.api_key, "Content-Type": "application/json"}

    def _request(self, method, path, json=None, timeout=120):
        url = f"{API_BASE}/{path.lstrip('/')}"
        last_error = None

        for attempt in range(_MAX_ATTEMPTS):
            if attempt:
                time.sleep(min(_BACKOFF_BASE_SECONDS**attempt, _MAX_RETRY_AFTER_SECONDS))
            try:
                resp = requests.request(
                    method, url, headers=self._headers(), json=json, timeout=timeout
                )
            except requests.exceptions.RequestException as e:
                last_error = str(e)
                continue

            if resp.status_code == 429:
                # Retry-After is authoritative when present; sleep here rather
                # than falling through to the generic backoff above.
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        time.sleep(min(float(retry_after), _MAX_RETRY_AFTER_SECONDS))
                    except ValueError:
                        pass
                last_error = "Rate limited (429)"
                continue

            if resp.status_code >= 500:
                last_error = f"HTTP {resp.status_code}: {resp.text[:200]}"
                continue

            if resp.status_code >= 400:
                raise TripleWhaleAPIError(f"HTTP {resp.status_code}: {resp.text[:500]}")

            try:
                return resp.json()
            except ValueError:
                raise TripleWhaleAPIError(f"Response was not JSON: {resp.text[:200]}")

        raise TripleWhaleAPIError(
            f"Request to {path} failed after {_MAX_ATTEMPTS} attempts: {last_error}"
        )

    def whoami(self):
        """Validate the API key. The only GET endpoint a key can reach."""
        return self._request("GET", "/users/api-keys/me", timeout=15)

    def summary_page(self, start_date, end_date, today_hour=24):
        """
        Store-wide aggregate metrics for a date range.

        today_hour is base-1 (1-25) and only affects partial current-day data;
        a full previous day is unaffected by the value sent.
        """
        payload = {
            "shopDomain": self.shop_domain,
            "period": {"start": str(start_date), "end": str(end_date)},
            "todayHour": today_hour,
        }
        return self._request("POST", "/summary-page/get-data", json=payload)

    def sql(self, query, start_date, end_date):
        """
        Run SQL against the Triple Whale warehouse.

        The query must reference @startDate / @endDate rather than literal
        dates; the bound values are sent in `period`.
        """
        payload = {
            "shopId": self.shop_domain,
            "query": query,
            "period": {"startDate": str(start_date), "endDate": str(end_date)},
        }
        if self.currency:
            payload["currency"] = self.currency
        return self._request("POST", "/orcabase/api/sql", json=payload)

    def orders_with_journeys(
        self, start_date, end_date, page=1, page_size=100, exclude_journey_data=True
    ):
        """
        Order-level attribution, one page at a time.

        This endpoint takes a flat shop/startDate/endDate body rather than the
        shopDomain/period shape the other two use, and it paginates -- pageSize
        is capped at 100 by the API.
        """
        payload = {
            "shop": self.shop_domain,
            "startDate": str(start_date),
            "endDate": str(end_date),
            "page": page,
            "pageSize": min(int(page_size), 100),
            "excludeJourneyData": bool(exclude_journey_data),
        }
        return self._request(
            "POST", "/attribution/get-orders-with-journeys-v2", json=payload
        )
