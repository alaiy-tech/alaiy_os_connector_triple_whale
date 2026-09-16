# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""
Reachability check for the saved credentials. Wired into the registry via
connector_meta["test_method"] and called by the "Test Connection" button.
Always returns {"success": bool, "message": str} -- never raises to the caller.
"""

import frappe
import requests

from alaiy_os_connector_triple_whale.triple_whale.auth import API_BASE


@frappe.whitelist()
def test_connection():
    doc = frappe.get_single("Triple Whale Connector Settings")
    api_key = doc.get_password("triple_whale_api_key") if doc.triple_whale_api_key else None
    shop_domain = (doc.triple_whale_shop_domain or "").strip()

    if not api_key:
        return {"success": False, "message": "API Key is not set."}
    if not shop_domain:
        return {"success": False, "message": "Shop Domain is not set."}

    try:
        resp = requests.get(
            f"{API_BASE}/users/api-keys/me",
            headers={"x-api-key": api_key},
            timeout=15,
        )
    except requests.exceptions.ConnectionError:
        return {"success": False, "message": f"Could not reach {API_BASE}."}
    except requests.exceptions.Timeout:
        return {"success": False, "message": "Request timed out (15s)."}
    except Exception as e:
        return {"success": False, "message": str(e)[:200]}

    if resp.status_code == 401:
        return {"success": False, "message": "Authentication failed — check the API Key."}
    if resp.status_code == 403:
        return {"success": False, "message": "Access forbidden — verify the key's scopes."}
    if resp.status_code == 429:
        return {"success": False, "message": "Rate limited — try again shortly."}
    if resp.status_code != 200:
        return {"success": False, "message": f"HTTP {resp.status_code}: {resp.text[:200]}"}

    # Surface the granted scopes: SQL access is scoped separately from Summary
    # Page access, and the product-level syncs are unusable without it.
    try:
        data = resp.json() or {}
    except ValueError:
        return {"success": True, "message": "Connected successfully."}

    scopes = data.get("scopes") or data.get("scope") or []
    if isinstance(scopes, str):
        scopes = [scopes]
    if scopes:
        return {
            "success": True,
            "message": f"Connected successfully. Scopes: {', '.join(str(s) for s in scopes)}",
        }
    return {"success": True, "message": "Connected successfully."}
