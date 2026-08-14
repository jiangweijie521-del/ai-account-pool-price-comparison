from __future__ import annotations

import copy
import sqlite3
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from tempfile import TemporaryDirectory

import ops
import server


class BackupTest(unittest.TestCase):
    def test_backup_is_consistent_private_and_rotated(self):
        with TemporaryDirectory() as temp_dir:
            root = Path(temp_dir)
            database = root / "analytics.sqlite3"
            backup_dir = root / "backups"
            with sqlite3.connect(database) as connection:
                connection.execute("CREATE TABLE sample(value TEXT NOT NULL)")
                connection.execute("INSERT INTO sample VALUES('first')")

            base = datetime(2026, 8, 15, 3, 20, tzinfo=timezone(timedelta(hours=8)))
            first = ops.backup_database(database, backup_dir, keep=2, now=base)
            with sqlite3.connect(database) as connection:
                connection.execute("INSERT INTO sample VALUES('second')")
            ops.backup_database(database, backup_dir, keep=2, now=base + timedelta(seconds=1))
            ops.backup_database(database, backup_dir, keep=2, now=base + timedelta(seconds=2))

            self.assertFalse(first.exists())
            self.assertEqual(len(list(backup_dir.glob("analytics-*.sqlite3"))), 2)
            newest = sorted(backup_dir.glob("analytics-*.sqlite3"))[-1]
            with sqlite3.connect(newest) as connection:
                self.assertEqual(connection.execute("SELECT COUNT(*) FROM sample").fetchone()[0], 2)
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            self.assertEqual(newest.stat().st_mode & 0o777, 0o600)


class MonitorTest(unittest.TestCase):
    def setUp(self):
        self.cache = copy.deepcopy(server.CACHE)
        payload = {
            "ok": True,
            "partial": False,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
            "refresh_seconds": 300,
            "summary": {"total": 4, "available": 4, "out_of_stock": 0, "groups": 2, "shops_fresh": 2, "shops_stale": 0, "shops_total": 2},
            "shops": [],
            "items": [],
        }
        server.CACHE.update({"stored_at": server.time.monotonic(), "payload": payload})
        self.httpd = server.AppServer(("127.0.0.1", 0), server.AppHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}/"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        server.CACHE.clear()
        server.CACHE.update(self.cache)

    def test_monitor_checks_real_health_and_complete_inventory(self):
        result = ops.monitor_base_url(self.base_url, timeout=5)

        self.assertEqual(result["items"], 4)
        self.assertEqual(result["shops_fresh"], 2)
        self.assertEqual(result["version"], server.SERVICE_VERSION)

    def test_monitor_rejects_partial_inventory(self):
        server.CACHE["payload"]["partial"] = True

        with self.assertRaisesRegex(RuntimeError, "inventory is partial"):
            ops.monitor_base_url(self.base_url, timeout=5)


if __name__ == "__main__":
    unittest.main()
