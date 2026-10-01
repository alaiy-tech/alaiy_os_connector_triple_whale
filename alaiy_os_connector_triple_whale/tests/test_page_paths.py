# Copyright (c) 2026, Alaiy and contributors
# For license information, please see license.txt
"""Storefront URL helpers, checked without a site.

    python3 alaiy_os_connector_triple_whale/tests/test_page_paths.py
"""

import importlib.util
import os
import unittest

_path = os.path.join(os.path.dirname(__file__), "..", "triple_whale", "pages", "paths.py")
_spec = importlib.util.spec_from_file_location("paths", _path)
paths = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(paths)


class TestPaths(unittest.TestCase):
    def test_page_types(self):
        self.assertEqual(paths.page_type_for("/"), "home")
        self.assertEqual(paths.page_type_for("/products/some-ring"), "product")
        self.assertEqual(paths.page_type_for("/collections/some-brand"), "collection")
        self.assertEqual(paths.page_type_for("/search"), "search")
        self.assertEqual(paths.page_type_for("/pages/sourcing"), "other")

    def test_handles(self):
        self.assertEqual(paths.handle_for("/products/some-ring"), "some-ring")
        self.assertEqual(paths.handle_for("/collections/some-brand/"), "some-brand")
        self.assertEqual(paths.handle_for("/pages/sourcing"), "")
        self.assertEqual(paths.handle_for("/"), "")

    def test_clean_path_strips_query_and_domain(self):
        self.assertEqual(paths.clean_path("/collections/x?utm_source=a"), "/collections/x")
        self.assertEqual(paths.clean_path("https://shop.example.com/products/y?z=1"), "/products/y")
        self.assertEqual(paths.clean_path("https://shop.example.com"), "/")
        self.assertEqual(paths.clean_path(None), "/")

    def test_long_paths_are_capped(self):
        self.assertEqual(len(paths.clean_path("/products/" + "a" * 400)), 255)


if __name__ == "__main__":
    unittest.main()
