from __future__ import annotations

import copy
import json
import threading
import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from urllib.request import urlopen

import server


def inventory_payload(marker: str) -> dict:
    return {
        "ok": True,
        "partial": False,
        "generated_at": "2026-08-15T10:00:00+08:00",
        "refresh_seconds": 300,
        "summary": {"total": 0, "available": 0, "out_of_stock": 0, "groups": 0, "shops_fresh": 1, "shops_stale": 0, "shops_total": 1},
        "shops": [],
        "items": [],
        "marker": marker,
    }


def item(shop_token: str, price: float, *, stale: bool = False, fetched_at: str = "2026-08-15T10:00:00+08:00") -> dict:
    return {
        "key": f"ITEM{shop_token}",
        "name": "Plus 已接码",
        "price": price,
        "stock": 2,
        "available": True,
        "category": "PLUS",
        "group": "GPT Plus · 已接码",
        "group_rank": 1,
        "goods_type": "card",
        "goods_type_label": "卡密",
        "shop": f"店铺{shop_token}",
        "shop_token": shop_token,
        "shop_url": f"https://pay.ldxp.cn/shop/{shop_token}",
        "link": f"https://pay.ldxp.cn/item/ITEM{shop_token}",
        "tags": ["已接码"],
        "canonical": "plus已接码",
        "stale": stale,
        "fetched_at": fetched_at,
    }


class ClassificationTest(unittest.TestCase):
    def test_team_name_wins_over_k12_upstream_category(self):
        self.assertEqual(server.classify("长效 周额team", "K12"), "OpenAI Team")
        self.assertEqual(server.classify("团队工作区账号", "K12"), "OpenAI Team")


class InventoryRefreshTest(unittest.TestCase):
    def setUp(self):
        self.cache = copy.deepcopy(server.CACHE)
        self.last_manual = getattr(server, "LAST_MANUAL_REFRESH_AT", 0.0)

    def tearDown(self):
        server.CACHE.clear()
        server.CACHE.update(self.cache)
        server.LAST_MANUAL_REFRESH_AT = self.last_manual

    def test_manual_refresh_bypasses_fresh_shared_cache(self):
        server.CACHE.update({"stored_at": 99.0, "payload": inventory_payload("cached")})
        server.LAST_MANUAL_REFRESH_AT = 0.0
        with patch("server.time.monotonic", return_value=100.0), patch(
            "server.collect_inventory", return_value=inventory_payload("fresh")
        ) as collect:
            payload = server.get_inventory(force=True)

        collect.assert_called_once_with()
        self.assertEqual(payload["marker"], "fresh")
        self.assertEqual(payload["delivery"]["refresh_status"], "refreshed")

    def test_manual_refresh_cooldown_reuses_shared_result(self):
        server.CACHE.update({"stored_at": 98.0, "payload": inventory_payload("cached")})
        server.LAST_MANUAL_REFRESH_AT = 95.0
        with patch("server.time.monotonic", return_value=100.0), patch("server.collect_inventory") as collect:
            payload = server.get_inventory(force=True)

        collect.assert_not_called()
        self.assertEqual(payload["marker"], "cached")
        self.assertEqual(payload["delivery"]["refresh_status"], "cooldown")
        self.assertGreater(payload["delivery"]["retry_after_seconds"], 0)

    def test_slow_manual_refresh_starts_cooldown_when_collection_finishes(self):
        server.CACHE.update({"stored_at": 0.0, "payload": None})
        server.LAST_MANUAL_REFRESH_AT = 0.0
        with patch("server.time.monotonic", side_effect=[100.0, 140.0, 140.0, 140.0]), patch(
            "server.collect_inventory", return_value=inventory_payload("fresh")
        ) as collect, patch("server.save_persisted_cache"):
            first = server.get_inventory(force=True)
            second = server.get_inventory(force=True)

        self.assertEqual(first["delivery"]["refresh_status"], "refreshed")
        self.assertEqual(second["delivery"]["refresh_status"], "cooldown")
        collect.assert_called_once_with()


class StaleInventoryTest(unittest.TestCase):
    def setUp(self):
        self.shops = server.SHOPS
        self.last_good = copy.deepcopy(server.LAST_GOOD)

    def tearDown(self):
        server.SHOPS = self.shops
        server.LAST_GOOD.clear()
        server.LAST_GOOD.update(self.last_good)

    def test_stale_source_keeps_age_and_sorts_after_fresh_source(self):
        shop_a = {"name": "店铺A", "token": "A", "url": "https://pay.ldxp.cn/shop/A"}
        shop_b = {"name": "店铺B", "token": "B", "url": "https://pay.ldxp.cn/shop/B"}
        server.SHOPS = (shop_a, shop_b)
        server.LAST_GOOD.clear()
        server.LAST_GOOD["A"] = {
            "name": "店铺A",
            "nickname": "店铺A",
            "token": "A",
            "url": shop_a["url"],
            "ok": True,
            "stale": False,
            "message": "读取成功",
            "fetched_at": "2026-08-14T10:00:00+08:00",
            "declared_count": 1,
            "item_count": 1,
            "items": [item("A", 1.0, fetched_at="2026-08-14T10:00:00+08:00")],
        }

        def fetch(current_shop):
            if current_shop["token"] == "A":
                raise TimeoutError("upstream timeout")
            return {
                "name": "店铺B",
                "nickname": "店铺B",
                "token": "B",
                "url": shop_b["url"],
                "ok": True,
                "stale": False,
                "message": "读取成功",
                "fetched_at": "2026-08-15T10:00:00+08:00",
                "declared_count": 1,
                "item_count": 1,
                "items": [item("B", 2.0)],
            }

        with patch("server.fetch_shop", side_effect=fetch):
            payload = server.collect_inventory()

        self.assertTrue(payload["partial"])
        self.assertEqual(payload["items"][0]["shop_token"], "B")
        stale = next(entry for entry in payload["items"] if entry["shop_token"] == "A")
        self.assertTrue(stale["stale"])
        self.assertEqual(stale["fetched_at"], "2026-08-14T10:00:00+08:00")
        self.assertEqual(payload["shops"][0]["fetched_at"], "2026-08-14T10:00:00+08:00")


class StaticAndHealthTest(unittest.TestCase):
    def setUp(self):
        self.httpd = server.AppServer(("127.0.0.1", 0), server.AppHandler)
        self.thread = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = f"http://127.0.0.1:{self.httpd.server_address[1]}"

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self.thread.join(timeout=5)

    def test_versioned_assets_are_immutable_but_html_is_not_cached(self):
        with urlopen(f"{self.base_url}/styles.css?v=release-1", timeout=5) as response:
            self.assertEqual(response.headers["Cache-Control"], "public, max-age=31536000, immutable")
        with urlopen(f"{self.base_url}/", timeout=5) as response:
            self.assertEqual(response.headers["Cache-Control"], "no-store")

    def test_health_exposes_release_revision_and_runtime(self):
        with urlopen(f"{self.base_url}/api/health", timeout=5) as response:
            payload = json.load(response)
        self.assertTrue(payload["version"])
        self.assertIn("revision", payload)
        self.assertRegex(payload["python"], r"^3\.11\.")

    def test_crawl_and_favicon_endpoints_are_live(self):
        expected_types = {
            "/robots.txt": "text/plain",
            "/sitemap.xml": "application/xml",
            "/favicon.ico": "image/svg+xml",
        }
        for path, expected_type in expected_types.items():
            with self.subTest(path=path), urlopen(f"{self.base_url}{path}", timeout=5) as response:
                self.assertEqual(response.status, 200)
                self.assertIn(expected_type, response.headers["Content-Type"])
                self.assertTrue(response.read())


class SeoSurfaceTest(unittest.TestCase):
    def test_homepage_metadata_and_crawl_files_exist(self):
        root = Path(__file__).resolve().parent
        html = (root / "index.html").read_text(encoding="utf-8")
        self.assertIn("<link rel=\"canonical\" href=\"https://stock.ultraai.site/\">", html)
        self.assertIn('property="og:title"', html)
        self.assertIn('type="application/ld+json"', html)
        self.assertIn('rel="sponsored noopener noreferrer"', html)
        self.assertNotIn("官方渠道", html)
        self.assertNotIn("限时", html)
        self.assertTrue((root / "robots.txt").is_file())
        self.assertTrue((root / "sitemap.xml").is_file())
        self.assertFalse((root / "assets" / "NotoSansSC-Bold.otf").exists())
        self.assertIn("/favicon.ico", server.STATIC_FILES)


if __name__ == "__main__":
    unittest.main()
