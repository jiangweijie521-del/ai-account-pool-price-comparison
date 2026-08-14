import base64
import http.client
import json
import sqlite3
import stat
import tempfile
import threading
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch
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

    def test_same_session_id_from_two_ips_counts_as_two_visits(self):
        record_event = self.require("record_analytics_event")
        get_summary = self.require("get_analytics_summary")
        now = datetime(2026, 8, 7, 10, 0, tzinfo=CHINA_TZ)

        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "analytics.sqlite3"
            secret = b"test-secret"
            record_event(database, secret, "203.0.113.7", "session-0000000001", 0, now)
            record_event(database, secret, "198.51.100.4", "session-0000000001", 0, now)

            today = get_summary(database, 30, now)["days"][0]
            self.assertEqual(today["unique_ips"], 2)
            self.assertEqual(today["visits"], 2)

    def test_legacy_session_schema_is_migrated_without_losing_rows(self):
        connection_factory = self.require("analytics_connection")
        now = datetime(2026, 8, 7, 10, 0, tzinfo=CHINA_TZ)
        with tempfile.TemporaryDirectory() as temp_dir:
            database = Path(temp_dir) / "analytics.sqlite3"
            with sqlite3.connect(database) as connection:
                connection.executescript(
                    """
                    CREATE TABLE visitors(day TEXT NOT NULL, visitor_hash TEXT NOT NULL, PRIMARY KEY(day, visitor_hash));
                    CREATE TABLE sessions(
                        session_id TEXT NOT NULL,
                        day TEXT NOT NULL,
                        visitor_hash TEXT NOT NULL,
                        started_at INTEGER NOT NULL,
                        last_seen INTEGER NOT NULL,
                        active_seconds INTEGER NOT NULL DEFAULT 0,
                        PRIMARY KEY(session_id, day)
                    );
                    INSERT INTO sessions VALUES('session-0000000001', '2026-08-07', 'legacy-hash', 1, 2, 1);
                    """
                )

            with connection_factory(database) as connection:
                primary_key = [row["name"] for row in connection.execute("PRAGMA table_info(sessions)") if row["pk"]]
                count = connection.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]

            self.assertEqual(primary_key, ["session_id", "day", "visitor_hash"])
            self.assertEqual(count, 1)

    def test_daily_session_limit_rejects_new_sessions_but_accepts_updates(self):
        record_event = self.require("record_analytics_event")
        now = datetime(2026, 8, 7, 10, 0, tzinfo=CHINA_TZ)
        with tempfile.TemporaryDirectory() as temp_dir, patch.object(server, "ANALYTICS_MAX_SESSIONS_PER_VISITOR_DAY", 1):
            database = Path(temp_dir) / "analytics.sqlite3"
            accepted = record_event(database, b"test-secret", "203.0.113.7", "session-0000000001", 0, now)
            rejected = record_event(database, b"test-secret", "203.0.113.7", "session-0000000002", 0, now)
            updated = record_event(database, b"test-secret", "203.0.113.7", "session-0000000001", 1, now + timedelta(seconds=1))

            self.assertTrue(accepted)
            self.assertFalse(rejected)
            self.assertTrue(updated)


class AnalyticsHttpTest(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        server.ANALYTICS_DB_FILE = Path(self.temp_dir.name) / "analytics.sqlite3"
        server.ANALYTICS_HASH_SECRET = b"http-test-secret"
        server.ANALYTICS_ADMIN_USER = "admin"
        server.ANALYTICS_ADMIN_PASSWORD = "correct-horse-battery-staple"
        server.ANALYTICS_RATE_BUCKETS.clear()
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

    def test_obvious_bot_is_ignored(self):
        body = json.dumps({"session_id": "session-0000000001", "active_seconds": 0}).encode()
        connection = http.client.HTTPConnection("127.0.0.1", self.httpd.server_address[1], timeout=5)
        connection.request(
            "POST",
            "/api/analytics/session",
            body=body,
            headers={
                "Content-Type": "application/json",
                "CF-Connecting-IP": "203.0.113.7",
                "User-Agent": "Mozilla/5.0 HeadlessChrome/151.0",
            },
        )
        response = connection.getresponse()
        self.assertEqual(response.status, 204)
        response.read()
        connection.request("GET", "/api/health")
        health_response = connection.getresponse()
        self.assertEqual(health_response.status, 200, "ignored bot body must not corrupt the keep-alive connection")
        health_response.read()
        connection.close()
        self.assertEqual(server.get_analytics_summary(server.ANALYTICS_DB_FILE)["days"], [])

    def test_tracking_endpoint_rate_limits_one_ip(self):
        body = json.dumps({"session_id": "session-0000000001", "active_seconds": 0}).encode()
        with patch.object(server, "ANALYTICS_MAX_POSTS_PER_MINUTE", 1):
            for expected_status in (204, 429):
                request = Request(
                    f"{self.base_url}/api/analytics/session",
                    data=body,
                    method="POST",
                    headers={"Content-Type": "application/json", "CF-Connecting-IP": "203.0.113.7"},
                )
                if expected_status == 204:
                    with urlopen(request, timeout=5) as response:
                        self.assertEqual(response.status, expected_status)
                else:
                    with self.assertRaises(HTTPError) as limited:
                        urlopen(request, timeout=5)
                    self.assertEqual(limited.exception.code, expected_status)

    def test_successful_tracking_post_is_not_written_to_access_log(self):
        body = json.dumps({"session_id": "session-0000000001", "active_seconds": 0}).encode()
        request = Request(
            f"{self.base_url}/api/analytics/session",
            data=body,
            method="POST",
            headers={"Content-Type": "application/json", "CF-Connecting-IP": "203.0.113.7"},
        )
        with patch("server.get_access_logger") as get_logger, urlopen(request, timeout=5) as response:
            self.assertEqual(response.status, 204)
        get_logger.assert_not_called()


if __name__ == "__main__":
    unittest.main()
