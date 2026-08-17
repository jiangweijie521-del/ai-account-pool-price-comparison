import json
import threading
import time
from datetime import datetime, timedelta
from pathlib import Path
from tempfile import TemporaryDirectory

from playwright.sync_api import sync_playwright
import server as stock_server


ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
BASE_URL = "http://127.0.0.1:8765/"


def fixture_payload() -> dict:
    fetched_at = datetime.now().astimezone().isoformat(timespec="seconds")
    shop = {"name": "测试店", "token": "SHOP1", "url": "https://pay.ldxp.cn/shop/SHOP1"}
    specs = [
        ("旧数据 Plus 已接码", "PLUS", 0.1, 2, True),
        ("Plus 已接码 标准版", "PLUS", 5, 3, False),
        ("Plus 已接码 稳定版", "PLUS", 6, 2, False),
        ("Plus 已接码 长效版", "PLUS", 7, 1, False),
        ("Plus 已接码 备用版", "PLUS", 8, 4, False),
        ("Plus 已接码 周额度", "PLUS", 9, 5, False),
        ("Plus 已接码 月额度", "PLUS", 10, 6, False),
        ("Plus 已接码 独享版", "PLUS", 11, 7, False),
        ("Plus 已接码 缺货版", "PLUS", 4, 0, False),
        ("长效 周额team", "K12", 15, 2, False),
        ("Claude Pro 成品号", "Claude", 18, 2, False),
        ("Gemini Pro 12个月", "Gemini", 20, 2, False),
    ]
    items = []
    for index, (name, category, price, count, stale) in enumerate(specs, start=1):
        item = stock_server.transform_item(
            {
                "name": name,
                "goods_key": f"ITEM{index}",
                "price": price,
                "category": {"name": category},
                "extend": {"stock_count": count},
                "link": f"https://pay.ldxp.cn/item/ITEM{index}",
            },
            shop,
            "card",
        )
        assert item is not None
        item.update({"same_product_shops": 0, "stale": stale, "fetched_at": fetched_at})
        items.append(item)
    items.sort(
        key=lambda entry: (
            entry["group_rank"],
            entry["group"],
            entry["stale"],
            not entry["available"],
            entry["price"],
        )
    )
    available = sum(1 for item in items if item["available"])
    return {
        "ok": True,
        "partial": True,
        "generated_at": fetched_at,
        "refresh_seconds": 300,
        "summary": {
            "total": len(items),
            "available": available,
            "out_of_stock": len(items) - available,
            "groups": len({item["group"] for item in items}),
            "shops_fresh": 1,
            "shops_stale": 1,
            "shops_total": 2,
        },
        "shops": [
            {
                "name": "测试店",
                "nickname": "测试店",
                "token": "SHOP1",
                "url": shop["url"],
                "ok": True,
                "stale": False,
                "message": "读取成功",
                "fetched_at": fetched_at,
                "declared_count": len(items),
                "item_count": len(items),
            },
            {
                "name": "旧数据店",
                "nickname": "旧数据店",
                "token": "SHOP2",
                "url": "https://pay.ldxp.cn/shop/SHOP2",
                "ok": False,
                "stale": True,
                "message": "网络连接超时，显示上次数据",
                "fetched_at": fetched_at,
                "declared_count": 1,
                "item_count": 1,
            },
        ],
        "items": items,
    }


def wait_for_inventory(page) -> None:
    page.goto(BASE_URL, wait_until="networkidle", timeout=60_000)
    page.locator("#inventoryList .inventory-group").first.wait_for(timeout=60_000)


def seed_history(database: Path, payload: dict) -> None:
    targets = [item for item in payload["items"] if not item["stale"] and item["available"]]
    target = targets[0]
    start = datetime.now().astimezone() - timedelta(days=5)
    for index, stock in enumerate([14, 13, 12, 10, 9, 8]):
        observed_at = start + timedelta(days=index)
        entry = dict(target)
        entry.update(
            {
                "stock": stock,
                "available": stock > 0,
                "price": [6, 6, 5.5, 5.5, 5, 5.5][index],
                "fetched_at": observed_at.isoformat(timespec="seconds"),
            }
        )
        stock_server.record_inventory_history(
            database,
            {"generated_at": observed_at.isoformat(timespec="seconds"), "items": [entry]},
        )
    stock_server.record_inventory_history(
        database,
        {"generated_at": datetime.now().astimezone().isoformat(timespec="seconds"), "items": [targets[1]]},
    )


def main() -> None:
    EVIDENCE.mkdir(exist_ok=True)
    console_errors: list[str] = []
    page_errors: list[str] = []
    results: dict[str, object] = {}

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True)

        desktop = browser.new_context(viewport={"width": 1440, "height": 1000}, device_scale_factor=1)
        page = desktop.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("pageerror", lambda error: page_errors.append(str(error)))
        wait_for_inventory(page)
        page.evaluate("document.fonts.ready")

        initial_rows = page.locator(".inventory-group .product-row").count()
        initial_unavailable = page.locator(".inventory-group .product-row.is-unavailable").count()
        assert initial_rows > 0
        assert initial_unavailable == 0
        assert page.locator("#availabilityToggle").get_attribute("aria-pressed") == "true"
        assert "检查时间" in page.locator("#updatedAt").inner_text()
        assert page.locator("#syncStamp").inner_text() in {"数据已同步", "部分同步"}
        assert page.locator("#cheapestList .cheap-pick").count() >= 3
        assert page.locator(".key-icon").count() == 3
        assert page.locator("#updatedAt").evaluate("element => element.tagName") == "TIME"
        assert page.locator("#updatedAt").get_attribute("datetime")
        assert "Receipt Display" not in page.locator("h1").evaluate("element => getComputedStyle(element).fontFamily")
        assert not page.evaluate("performance.getEntriesByType('resource').some(entry => entry.name.includes('NotoSansSC'))")
        assert "paper-fiber.svg" in page.locator(".paper").evaluate("element => getComputedStyle(element).backgroundImage")
        assert "ink-mask.svg" in page.locator("h1").evaluate("element => getComputedStyle(element).webkitMaskImage")
        assert "sponsored" in (page.locator(".cloud-offer").get_attribute("rel") or "")
        assert "推广" in page.locator(".cloud-offer").inner_text()
        assert "官方渠道" not in page.locator(".cloud-offer").inner_text()
        assert "限时" not in page.locator(".cloud-offer").inner_text()
        assert "¥0.10" not in page.locator("#cheapestList").inner_text()

        trend_buttons = page.locator(".inventory-group .trend-button")
        assert trend_buttons.count() == initial_rows
        trend_button = page.locator(".inventory-group .product-row:not(.is-stale) .trend-button").first
        trend_button.focus()
        trend_button.click()
        panel = page.locator("#historyPanel")
        panel.wait_for(state="visible")
        assert panel.get_attribute("role") == "dialog"
        assert page.locator(".paper").evaluate("element => element.inert")
        assert page.locator(".paper").get_attribute("aria-hidden") == "true"
        assert page.locator(".skip-link").evaluate("element => element.inert")
        assert "价格与库存走势" in panel.inner_text()
        panel.locator(".history-chart svg").wait_for()
        assert panel.locator(".history-chart svg").count() == 1
        time_positions = page.evaluate(
            """() => {
                const observations = [
                    { at: '2026-08-01T00:00:00Z' },
                    { at: '2026-08-01T01:00:00Z' },
                    { at: '2026-08-05T00:00:00Z' },
                ];
                return observations.map((_, index) => historyPointX(observations, index));
            }"""
        )
        assert time_positions[1] - time_positions[0] < 20
        assert time_positions[2] - time_positions[1] > 400
        assert "预计" in panel.locator(".history-forecast").inner_text()
        page.wait_for_timeout(300)
        desktop_panel_box = panel.bounding_box()
        assert desktop_panel_box
        assert abs(desktop_panel_box["x"] + desktop_panel_box["width"] - 1440) <= 2, desktop_panel_box
        page.screenshot(path=str(EVIDENCE / "desktop-history-final.png"))
        panel.locator('[data-history-days="30"]').click()
        assert panel.locator('[data-history-days="30"]').get_attribute("aria-pressed") == "true"
        page.keyboard.press("Escape")
        panel.wait_for(state="hidden")
        assert not page.locator(".paper").evaluate("element => element.inert")
        assert page.locator(".paper").get_attribute("aria-hidden") is None
        assert not page.locator(".skip-link").evaluate("element => element.inert")
        assert trend_button.evaluate("element => document.activeElement === element")

        fresh_trends = page.locator(".inventory-group .product-row:not(.is-stale) .trend-button")
        fresh_trends.nth(1).click()
        panel.locator(".history-forecast.is-insufficient").wait_for()
        assert "暂不预测" in panel.locator(".history-forecast").inner_text()
        assert panel.locator(".history-point").count() == 2
        assert panel.locator(".history-date-label").count() == 1
        page.keyboard.press("Escape")
        panel.wait_for(state="hidden")

        fresh_trends.nth(2).click()
        panel.locator(".history-state.is-empty").wait_for()
        assert "暂无历史记录" in panel.locator(".history-state").inner_text()
        page.keyboard.press("Escape")
        panel.wait_for(state="hidden")

        page.route(
            "**/api/product-history?*",
            lambda route: route.fulfill(
                status=200,
                content_type="application/json",
                body=json.dumps({"ok": False, "message": "测试历史接口异常"}, ensure_ascii=False),
            ),
        )
        fresh_trends.nth(3).click()
        panel.locator(".history-state.is-error").wait_for()
        assert panel.locator(".history-retry").is_visible()
        page.keyboard.press("Escape")
        panel.wait_for(state="hidden")

        button_heights = page.locator("button").evaluate_all(
            "buttons => buttons.filter(button => button.offsetParent !== null).map(button => button.getBoundingClientRect().height)"
        )
        assert button_heights and min(button_heights) >= 48
        body_font = float(page.locator("body").evaluate("element => parseFloat(getComputedStyle(element).fontSize)"))
        assert body_font >= 18

        page.locator("#availabilityToggle").click()
        assert page.locator("#availabilityToggle").get_attribute("aria-pressed") == "false"
        all_unavailable = page.locator(".inventory-group .product-row.is-unavailable").count()
        assert all_unavailable > 0
        page.locator("#availabilityToggle").click()
        assert page.locator(".inventory-group .product-row.is-unavailable").count() == 0

        page.locator("#searchInput").fill("接码")
        assert page.locator("#clearSearch").is_visible()
        search_rows = page.locator(".inventory-group .product-row").count()
        assert 0 < search_rows < initial_rows
        page.locator("#clearSearch").click()
        assert page.locator("#searchInput").input_value() == ""
        assert page.locator(".inventory-group .product-row").count() == initial_rows

        first_link = page.locator(".product-link").first.get_attribute("href")
        assert first_link and first_link.startswith("https://pay.ldxp.cn/item/")

        page.locator("#refreshButton").click()
        page.locator("#refreshButton:not([disabled])").wait_for(timeout=60_000)
        assert page.locator("#syncStamp").inner_text() in {"数据已同步", "部分同步"}

        page.locator("#searchInput").focus()
        page.keyboard.press("Shift+Tab")
        assert page.evaluate("document.activeElement.id") == "refreshButton"
        focus_outline = page.locator("#refreshButton").evaluate(
            "element => ({ style: getComputedStyle(element).outlineStyle, width: parseFloat(getComputedStyle(element).outlineWidth) })"
        )
        assert focus_outline["style"] != "none" and focus_outline["width"] >= 3

        desktop_overflow = page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert desktop_overflow <= 1
        page.evaluate("window.scrollTo(0, 0)")
        page.screenshot(path=str(EVIDENCE / "desktop-top-final.png"))
        page.locator("#inventory").scroll_into_view_if_needed()
        page.screenshot(path=str(EVIDENCE / "desktop-list-final.png"))
        page.screenshot(path=str(EVIDENCE / "desktop-final.png"), full_page=True)

        results.update(
            {
                "initial_available_rows": initial_rows,
                "out_of_stock_rows_after_toggle": all_unavailable,
                "search_rows": search_rows,
                "desktop_overflow_px": desktop_overflow,
                "minimum_button_height_px": min(button_heights),
                "body_font_px": body_font,
                "focus_outline": focus_outline,
            }
        )
        desktop.close()

        mobile = browser.new_context(viewport={"width": 390, "height": 844}, device_scale_factor=1)
        mobile_page = mobile.new_page()
        mobile_page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        mobile_page.on("pageerror", lambda error: page_errors.append(str(error)))
        wait_for_inventory(mobile_page)
        mobile_overflow = mobile_page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
        assert mobile_overflow <= 1
        assert mobile_page.locator(".row-head:visible").count() == 0
        assert mobile_page.locator("#cheapestList .cheap-pick").count() >= 3
        first_price = mobile_page.locator("#cheapestList .cheap-price").first.bounding_box()
        assert first_price and first_price["y"] + first_price["height"] < 844
        expand_button = mobile_page.locator(".group-expand").first
        assert expand_button.is_visible()
        rows_before_expand = mobile_page.locator(".inventory-group .product-row").count()
        expand_button.click()
        assert mobile_page.locator(".inventory-group .product-row").count() > rows_before_expand
        mobile_trend = mobile_page.locator(".inventory-group .product-row:not(.is-stale) .trend-button").first
        mobile_trend.click()
        mobile_panel = mobile_page.locator("#historyPanel")
        mobile_panel.wait_for(state="visible")
        mobile_page.wait_for_timeout(300)
        panel_box = mobile_panel.bounding_box()
        assert panel_box
        assert abs(panel_box["y"] + panel_box["height"] - 844) <= 2, panel_box
        assert panel_box["width"] >= 389
        mobile_page.screenshot(path=str(EVIDENCE / "mobile-history-final.png"))
        mobile_page.locator("#historyClose").click()
        mobile_panel.wait_for(state="hidden")
        mobile_page.evaluate("window.scrollTo(0, 0)")
        mobile_page.screenshot(path=str(EVIDENCE / "mobile-top-final.png"))
        mobile_page.locator("#inventory").scroll_into_view_if_needed()
        mobile_page.screenshot(path=str(EVIDENCE / "mobile-list-final.png"))
        mobile_page.screenshot(path=str(EVIDENCE / "mobile-final.png"), full_page=True)
        results["mobile_overflow_px"] = mobile_overflow
        mobile.close()

        responsive_results: dict[str, dict[str, float]] = {}
        for width, height in [(320, 700), (375, 812), (414, 896), (768, 900)]:
            context = browser.new_context(viewport={"width": width, "height": height}, device_scale_factor=1)
            matrix_page = context.new_page()
            matrix_page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
            matrix_page.on("pageerror", lambda error: page_errors.append(str(error)))
            wait_for_inventory(matrix_page)
            matrix_page.locator(".inventory-group .product-row:not(.is-stale) .trend-button").first.click()
            matrix_panel = matrix_page.locator("#historyPanel")
            matrix_panel.locator(".history-chart svg").wait_for()
            matrix_page.wait_for_timeout(300)
            matrix_box = matrix_panel.bounding_box()
            assert matrix_box
            assert matrix_box["x"] >= -1
            assert matrix_box["x"] + matrix_box["width"] <= width + 1
            assert matrix_box["y"] >= -1
            assert matrix_box["y"] + matrix_box["height"] <= height + 1
            panel_overflow = matrix_panel.evaluate("element => element.scrollWidth - element.clientWidth")
            assert panel_overflow <= 1
            metric_overflow = matrix_panel.locator(".history-metrics strong").evaluate_all(
                "elements => Math.max(...elements.map(element => element.scrollWidth - element.clientWidth))"
            )
            assert metric_overflow <= 1
            panel_button_heights = matrix_panel.locator("button").evaluate_all(
                "buttons => buttons.map(button => button.getBoundingClientRect().height)"
            )
            assert min(panel_button_heights) >= 44
            page_overflow = matrix_page.evaluate("document.documentElement.scrollWidth - window.innerWidth")
            assert page_overflow <= 1
            responsive_results[str(width)] = {
                "page_overflow_px": page_overflow,
                "panel_overflow_px": panel_overflow,
                "minimum_panel_button_height_px": min(panel_button_heights),
            }
            context.close()
        results["responsive_matrix"] = responsive_results

        browser.close()

    assert not console_errors, console_errors
    assert not page_errors, page_errors
    results["console_errors"] = console_errors
    results["page_errors"] = page_errors
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    with TemporaryDirectory() as temporary:
        payload = fixture_payload()
        stock_server.ANALYTICS_DB_FILE = Path(temporary) / "analytics.sqlite3"
        seed_history(stock_server.ANALYTICS_DB_FILE, payload)
        stock_server.CACHE.update({"stored_at": time.monotonic(), "payload": payload})
        stock_server.LAST_MANUAL_REFRESH_AT = time.monotonic()
        server = stock_server.find_server("127.0.0.1", 8765)
        host, port = server.server_address[:2]
        BASE_URL = f"http://{host}:{port}/"
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            main()
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)
