# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Row shaping and query text for the page traffic sync, checked without a site.

    python3 alaiy_os_connector_triple_whale/tests/test_page_shapes.py
"""

import importlib.util
import os
import re
import sys
import types
import unittest

HERE = os.path.dirname(__file__)
PAGES = os.path.join(HERE, "..", "triple_whale", "pages")


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


# The two modules under test import each other by package path; register stand-in packages.
for pkg in ("alaiy_os_connector_triple_whale", "alaiy_os_connector_triple_whale.triple_whale",
            "alaiy_os_connector_triple_whale.triple_whale.pages"):
    sys.modules[pkg] = types.ModuleType(pkg)
    sys.modules[pkg].__path__ = []
paths = _load("alaiy_os_connector_triple_whale.triple_whale.pages.paths", os.path.join(PAGES, "paths.py"))
shapes = _load("alaiy_os_connector_triple_whale.triple_whale.pages.shapes", os.path.join(PAGES, "shapes.py"))
queries_text = open(os.path.join(PAGES, "queries.py"), encoding="utf-8").read()


class TestMergeClicks(unittest.TestCase):
    def values(self):
        return [
            {"metric_date": "2026-09-05", "page_type": "collection", "page_path": "/collections/a", "clicked_through": 0},
            {"metric_date": "2026-09-05", "page_type": "product", "page_path": "/products/x", "clicked_through": 0},
            {"metric_date": "2026-09-06", "page_type": "collection", "page_path": "/collections/a", "clicked_through": 0},
        ]

    def test_only_collection_pages_get_clicks_matched_by_day_and_page(self):
        clicks = [
            {"event_date": "2026-09-05", "page": "/collections/a?x=1", "clicked": "7"},
            {"event_date": "2026-09-05", "page": "/products/x", "clicked": "99"},
        ]
        out = shapes.merge_clicks(self.values(), clicks)
        self.assertEqual([v["clicked_through"] for v in out], [7, 0, 0])

    def test_no_click_rows(self):
        out = shapes.merge_clicks(self.values(), [])
        self.assertEqual([v["clicked_through"] for v in out], [0, 0, 0])


class TestTrafficValues(unittest.TestCase):
    def test_rows_are_shaped(self):
        rows = [
            {"event_date": "2026-09-05", "traffic_source": "Paid ads", "page": "https://shop.example.com/products/ring?utm=a",
             "sessions": 12, "new_visitors": "5"},
            {"event_date": "", "traffic_source": "Direct", "page": "/x", "sessions": 1},
        ]
        out = shapes.traffic_values(rows)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["page_path"], "/products/ring")
        self.assertEqual(out[0]["handle"], "ring")
        self.assertEqual(out[0]["page_type"], "product")
        self.assertEqual((out[0]["sessions"], out[0]["new_visitors"]), (12, 5))

    def test_missing_source_is_other(self):
        out = shapes.traffic_values([{"event_date": "2026-09-05", "page": "/collections/b", "sessions": 1}])
        self.assertEqual(out[0]["traffic_source"], "Other")


class TestQueryText(unittest.TestCase):
    def test_query_string_is_stripped_with_an_escaped_backslash(self):
        """In the warehouse's SQL a single backslash before ? is dropped, which leaves
        an invalid pattern. Each pattern must carry two backslashes."""
        patterns = re.findall(r"replaceRegexpOne\(\w+, '([^']*)'", queries_text)
        self.assertGreaterEqual(len(patterns), 4)
        for p in patterns:
            self.assertEqual(p, "\\\\?.*$")


if __name__ == "__main__":
    unittest.main()
