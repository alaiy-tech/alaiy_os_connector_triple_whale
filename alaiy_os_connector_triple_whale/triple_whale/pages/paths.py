# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Storefront URL helpers for the page traffic sync. Stdlib only."""

_MAX_PATH = 255


def page_type_for(path):
    """product / collection / home / search / other, from a URL path."""
    if path in ("", "/"):
        return "home"
    if path.startswith("/products/"):
        return "product"
    if path.startswith("/collections/"):
        return "collection"
    if path.startswith("/search"):
        return "search"
    return "other"


def handle_for(path):
    """The product or collection handle: the last path segment, else empty."""
    if page_type_for(path) not in ("product", "collection"):
        return ""
    return path.rstrip("/").rsplit("/", 1)[-1][:_MAX_PATH]


def clean_path(value):
    """The URL's path with no domain or query string, capped to the field length."""
    path = str(value or "").split("?", 1)[0].strip()
    if "://" in path:
        rest = path.split("://", 1)[1]
        path = "/" + rest.split("/", 1)[1] if "/" in rest else "/"
    return (path or "/")[:_MAX_PATH]
