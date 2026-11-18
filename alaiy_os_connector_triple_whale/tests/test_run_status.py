"""A finished sync run is closed with the status core's run_status gives for its counts."""

import importlib
import sys
import types
import unittest

MODULE = "alaiy_os_connector_triple_whale.triple_whale.sync_log"


def _core_run_status(processed, failed, skipped, error=None):
    if processed > 0 and failed >= processed:
        return "failed"
    if processed == 0 and (error or skipped > 0):
        return "failed"
    return "success"


class FakeLog:
    def __init__(self):
        self.status = None
        self.error_message = None
        self.items_processed = 0
        self.items_failed = 0

    def save(self, **kwargs):
        pass


def _load(with_core=True):
    log = FakeLog()
    frappe = types.ModuleType("frappe")
    frappe.db = types.SimpleNamespace(exists=lambda *a: True, commit=lambda: None)
    frappe.get_doc = lambda *a: log
    frappe.get_traceback = lambda: "traceback"
    frappe.log_error = lambda **kw: None
    utils = types.ModuleType("frappe.utils")
    utils.now_datetime = lambda: None
    frappe.utils = utils
    mods = {"frappe": frappe, "frappe.utils": utils}
    if with_core:
        runs = types.ModuleType("alaiy_os.health.runs")
        runs.run_status = _core_run_status
        mods.update({"alaiy_os": types.ModuleType("alaiy_os"),
                     "alaiy_os.health": types.ModuleType("alaiy_os.health"),
                     "alaiy_os.health.runs": runs})
    else:
        mods["alaiy_os.health.runs"] = None  # import raises ImportError
    sys.modules.pop(MODULE, None)
    saved = {k: sys.modules.get(k) for k in mods}
    sys.modules.update(mods)
    try:
        return importlib.import_module(MODULE), log
    finally:
        for k, v in saved.items():
            if v is None:
                sys.modules.pop(k, None)
            else:
                sys.modules[k] = v


def _run(mod, log, processed, failed):
    def worker(_log):
        _log.items_processed = processed; _log.items_failed = failed
    mod.run_logged("x", "manual", "L", worker)


class TestRunStatus(unittest.TestCase):
    def test_every_item_failed_is_failed_with_message(self):
        mod, log = _load()
        _run(mod, log, 3, 3)
        self.assertEqual(log.status, "failed")
        self.assertIn("Every item failed (3)", log.error_message)

    def test_some_failed_is_still_success(self):
        mod, log = _load()
        _run(mod, log, 3, 1)
        self.assertEqual(log.status, "success")

    def test_nothing_processed_is_success(self):
        mod, log = _load()
        _run(mod, log, 0, 0)
        self.assertEqual(log.status, "success")

    def test_worker_raising_is_failed(self):
        mod, log = _load()

        def boom(_log):
            raise ValueError("x")

        with self.assertRaises(ValueError):
            mod.run_logged("x", "manual", "L", boom)
        self.assertEqual(log.status, "failed")

    def test_without_core_helper_keeps_old_behaviour(self):
        mod, log = _load(with_core=False)
        _run(mod, log, 3, 3)
        self.assertEqual(log.status, "success")


if __name__ == "__main__":
    unittest.main()
