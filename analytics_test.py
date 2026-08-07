import base64
import json
import stat
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

import server


CHINA_TZ = timezone(timedelta(hours=8))


class AnalyticsStorageTest(unittest.TestCase):
    def require(self, name):
        value = getattr(server, name, None)
        self.assertTrue(callable(value), f"server.{name} must exist")
        return value

    def test_ip_hash_is_stable_within_a_day_and_rotates_next_day(self):
        hash_visitor = self.require("hash_visitor")
        secret = b"test-secret"

        first = hash_visitor("203.0.113.7", "2026-08-07", secret)
        same_day = hash_visitor("203.0.113.7", "2026-08-07", secret)
        next_day = hash_visitor("203.0.113.7", "2026-08-08", secret)

        self.assertEqual(first, same_day)
        self.assertNotEqual(first, next_day)
        self.assertNotIn("203.0.113.7", first)

    def test_daily_summary_counts_unique_ips_visits_and_dwell_time(self):
        record_event = self.require("record_analytics_event")
        get_summary = self.require("get_analytics_summary")
        now = datetime(2026, 8, 7, 10, 0, tzinfo=CHINA_TZ)

        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "analytics.sqlite3"
            secret = b"test-secret"
            record_event(database, secret, "203.0.113.7", "session-0000000001", 0, now)
            record_event(database, secret, "203.0.113.7", "session-0000000001", 30, now + timedelta(seconds=30))
            record_event(database, secret, "203.0.113.7", "session-0000000002", 0, now)
            record_event(database, secret, "203.0.113.7", "session-0000000002", 20, now + timedelta(seconds=20))
            record_event(database, secret, "198.51.100.4", "session-0000000003", 0, now)
            record_event(database, secret, "198.51.100.4", "session-0000000003", 10, now + timedelta(seconds=10))

            summary = get_summary(database, 30, now)
            today = summary["days"][0]

            self.assertEqual(today["date"], "2026-08-07")
            self.assertEqual(today["unique_ips"], 2)
            self.assertEqual(today["visits"], 3)
            self.assertEqual(today["average_seconds"], 20)
            self.assertEqual(today["total_seconds"], 60)
            self.assertNotIn(b"203.0.113.7", database.read_bytes())
            self.assertEqual(stat.S_IMODE(database.stat().st_mode), 0o600)

    def test_duration_is_clamped_to_session_wall_time(self):
        record_event = self.require("record_analytics_event")
        get_summary = self.require("get_analytics_summary")
        now = datetime(2026, 8, 7, 10, 0, tzinfo=CHINA_TZ)

        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "analytics.sqlite3"
            secret = b"test-secret"
            record_event(database, secret, "203.0.113.7", "session-0000000001", 0, now)
            record_event(database, secret, "203.0.113.7", "session-0000000001", 3600, now + timedelta(seconds=5))

            today = get_summary(database, 30, now)["days"][0]
            self.assertLessEqual(today["total_seconds"], 10)

    def test_session_crossing_midnight_is_counted_on_both_days(self):
        record_event = self.require("record_analytics_event")
        get_summary = self.require("get_analytics_summary")
        before_midnight = datetime(2026, 8, 7, 23, 59, 55, tzinfo=CHINA_TZ)

        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "analytics.sqlite3"
            secret = b"test-secret"
            record_event(database, secret, "203.0.113.7", "session-0000000001", 0, before_midnight)
            record_event(
                database,
                secret,
                "203.0.113.7",
                "session-0000000001",
                10,
                before_midnight + timedelta(seconds=10),
            )

            days = get_summary(database, 30, before_midnight + timedelta(seconds=10))["days"]
            self.assertEqual([day["date"] for day in days], ["2026-08-08", "2026-08-07"])
            self.assertEqual([day["unique_ips"] for day in days], [1, 1])
            self.assertEqual([day["visits"] for day in days], [1, 1])


class AnalyticsHttpTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        server.ANALYTICS_DB_FILE = Path(self.temp_dir.name) / "analytics.sqlite3"
        server.ANALYTICS_HASH_SECRET = b"http-test-secret"
        server.ANALYTICS_ADMIN_USER = "admin"
        server.ANALYTICS_ADMIN_PASSWORD = "correct-horse-battery-staple"
        self.httpd = server.AppServer(("127.0.0.1", 0), server.AppHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)
        self.temp_dir.cleanup()

    def test_tracking_endpoint_and_authenticated_admin_summary(self):
        body = json.dumps({"session_id": "session-0000000001", "active_seconds": 0}).encode()
        request = Request(
            f"{self.base_url}/api/analytics/session",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "CF-Connecting-IP": "203.0.113.7"},
        )
        with urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 204)

        with self.assertRaises(HTTPError) as unauthorized:
            urlopen(f"{self.base_url}/api/admin/analytics", timeout=5)
        self.assertEqual(unauthorized.exception.code, 401)
        self.assertIn("Basic", unauthorized.exception.headers["WWW-Authenticate"])

        credentials = base64.b64encode(b"admin:correct-horse-battery-staple").decode()
        admin_request = Request(
            f"{self.base_url}/api/admin/analytics?days=30",
            headers={"Authorization": f"Basic {credentials}"},
        )
        with urlopen(admin_request, timeout=5) as response:
            payload = json.load(response)

        self.assertEqual(payload["days"][0]["unique_ips"], 1)
        self.assertEqual(payload["days"][0]["visits"], 1)

        page_request = Request(
            f"{self.base_url}/admin",
            headers={"Authorization": f"Basic {credentials}"},
        )
        with urlopen(page_request, timeout=5) as response:
            html = response.read().decode("utf-8")
        self.assertIn("<h1>访问分析</h1>", html)


if __name__ == "__main__":
    unittest.main()
