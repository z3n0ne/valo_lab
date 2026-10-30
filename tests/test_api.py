"""Integration tests for the local HTTP API (no network access)."""
import http.client
import importlib
import json
import os
import shutil
import tempfile
import threading
import unittest
from pathlib import Path

TMP_DATA = tempfile.mkdtemp(prefix="valo-test-")
os.environ["VALO_DATA_DIR"] = TMP_DATA
os.environ.pop("HENRIK_API_KEY", None)

from valorant import config as config_mod  # noqa: E402
from valorant import web as web_mod  # noqa: E402

importlib.reload(config_mod)
importlib.reload(web_mod)

from valorant.db import Database  # noqa: E402
from valorant.demo import seed_demo  # noqa: E402


class FakeSync:
    """Stand-in for SyncManager so tests never touch the network."""

    def __init__(self):
        self.calls = []

    def snapshot(self):
        return {"state": "idle", "message": "", "progress": 0, "total": 0, "last_sync": None, "stale": True}

    def start(self, full=False):
        self.calls.append(full)
        return False


class ApiTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = Database(config_mod.DB_PATH)
        cls.db.init_schema()
        seed_demo(cls.db)
        cls.sync = FakeSync()
        cls.server = web_mod.make_server("127.0.0.1", 0, web_mod.App(db=cls.db, sync=cls.sync))
        cls.port = cls.server.server_address[1]
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join(timeout=5)
        os.environ.pop("VALO_DATA_DIR", None)
        shutil.rmtree(TMP_DATA, ignore_errors=True)

    def request(self, method, path, body=None):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        headers = {}
        payload = None
        if body is not None:
            payload = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        conn.request(method, path, body=payload, headers=headers)
        response = conn.getresponse()
        raw = response.read()
        conn.close()
        try:
            data = json.loads(raw.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError):
            data = raw
        return response.status, data

    def test_health(self):
        status, data = self.request("GET", "/api/health")
        self.assertEqual(status, 200)
        self.assertTrue(data["ok"])
        self.assertIn("version", data)

    def test_index_is_served(self):
        status, data = self.request("GET", "/")
        self.assertEqual(status, 200)
        self.assertIn(b"VALO", data)

    def test_bootstrap_reports_demo_and_filters(self):
        status, data = self.request("GET", "/api/bootstrap")
        self.assertEqual(status, 200)
        self.assertFalse(data["configured"])
        self.assertTrue(data["demo"])
        self.assertEqual(data["counts"]["matches"], 90)
        self.assertEqual(data["counts"]["real"], 0)
        self.assertIn("regions", data)
        self.assertIn("platforms", data)
        self.assertIn("has_api_key", data["config"])
        self.assertFalse(data["config"]["has_api_key"], "the API key must never leak to the browser")
        self.assertNotIn("api_key", data["config"])

    def test_stats_payload(self):
        status, data = self.request("GET", "/api/stats?mode=tactical&days=90")
        self.assertEqual(status, 200)
        self.assertEqual(data["summary"]["matches"], 90)
        self.assertTrue(data["agents"])
        self.assertTrue(data["maps"])
        self.assertTrue(data["insights"])
        self.assertTrue(data["recent"])
        self.assertIn("profile", data)
        self.assertLessEqual(len(data["recent"]), 60)

    def test_unknown_route(self):
        status, data = self.request("GET", "/api/nope")
        self.assertEqual(status, 404)
        self.assertIn("error", data)

    def test_static_traversal_is_blocked(self):
        for path in ("/static/../valorant/web.py", "/static/../data/config.json"):
            with self.subTest(path=path):
                status, _ = self.request("GET", path)
                self.assertIn(status, (403, 404))

    def test_missing_static_file(self):
        status, data = self.request("GET", "/static/does-not-exist.js")
        self.assertEqual(status, 404)

    def test_sync_without_configuration_is_rejected(self):
        config_mod.save_config({"riot_name": "", "riot_tag": "", "api_key": ""})
        status, data = self.request("POST", "/api/sync", {})
        self.assertEqual(status, 400)
        self.assertFalse(self.sync.calls)
        self.assertIn("error", data)

    def test_bad_json_is_rejected(self):
        conn = http.client.HTTPConnection("127.0.0.1", self.port, timeout=10)
        conn.request("POST", "/api/sync", body=b"{oops", headers={"Content-Type": "application/json"})
        response = conn.getresponse()
        response.read()
        conn.close()
        self.assertEqual(response.status, 400)

    def test_settings_are_saved_and_key_is_hidden(self):
        status, data = self.request(
            "POST",
            "/api/settings",
            {"riot_name": "Axel", "riot_tag": "EUW", "region": "eu", "platform": "pc", "api_key": "secret-123"},
        )
        self.assertEqual(status, 200)
        self.assertTrue(data["configured"])
        self.assertTrue(data["config"]["has_api_key"])
        self.assertNotIn("secret-123", json.dumps(data))
        stored = json.loads((Path(TMP_DATA) / "config.json").read_text())
        self.assertEqual(stored["api_key"], "secret-123")
        mode = os.stat(Path(TMP_DATA) / "config.json").st_mode & 0o777
        self.assertEqual(mode, 0o600, "the config file contains the API key and must stay private")

    def test_demo_can_be_cleared_and_reseeded(self):
        status, data = self.request("POST", "/api/demo/clear", {})
        self.assertEqual(status, 200)
        self.assertEqual(data["removed"], 90)
        self.assertFalse(data["bootstrap"]["demo"])
        self.assertTrue(data["bootstrap"]["demo_dismissed"])
        self.assertEqual(data["bootstrap"]["counts"]["matches"], 0)

        status, data = self.request("POST", "/api/demo/seed", {})
        self.assertEqual(status, 200)
        self.assertEqual(data["added"], 90)
        self.assertTrue(data["bootstrap"]["demo"])


if __name__ == "__main__":
    unittest.main()
