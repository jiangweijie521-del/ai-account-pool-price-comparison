import json
import threading
from pathlib import Path

from playwright.sync_api import sync_playwright
from server import find_server


ROOT = Path(__file__).resolve().parent
EVIDENCE = ROOT / "evidence"
BASE_URL = "http://127.0.0.1:8765/"


def wait_for_inventory(page) -> None:
    page.goto(BASE_URL, wait_until="networkidle", timeout=60_000)
    page.locator("#inventoryList .inventory-group").first.wait_for(timeout=60_000)


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
        assert "最后更新" in page.locator("#updatedAt").inner_text()
        assert page.locator("#syncStamp").inner_text() in {"数据已同步", "部分同步"}
        assert page.locator("#cheapestList .cheap-pick").count() >= 3
        assert page.locator(".key-icon").count() == 3
        assert page.locator("#updatedAt").evaluate("element => element.tagName") == "TIME"
        assert page.locator("#updatedAt").get_attribute("datetime")
        assert page.evaluate("document.fonts.check('700 64px \\\"Receipt Display\\\"')")
        assert "paper-fiber.svg" in page.locator(".paper").evaluate("element => getComputedStyle(element).backgroundImage")
        assert "ink-mask.svg" in page.locator("h1").evaluate("element => getComputedStyle(element).webkitMaskImage")

        button_heights = page.locator("button").evaluate_all(
            "buttons => buttons.filter(button => !button.hidden).map(button => button.getBoundingClientRect().height)"
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

        first_link = page.locator(".product-row").first.get_attribute("href")
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
        mobile_page.evaluate("window.scrollTo(0, 0)")
        mobile_page.screenshot(path=str(EVIDENCE / "mobile-top-final.png"))
        mobile_page.locator("#inventory").scroll_into_view_if_needed()
        mobile_page.screenshot(path=str(EVIDENCE / "mobile-list-final.png"))
        mobile_page.screenshot(path=str(EVIDENCE / "mobile-final.png"), full_page=True)
        results["mobile_overflow_px"] = mobile_overflow
        mobile.close()

        browser.close()

    assert not console_errors, console_errors
    assert not page_errors, page_errors
    results["console_errors"] = console_errors
    results["page_errors"] = page_errors
    print(json.dumps(results, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    server = find_server("127.0.0.1", 8765)
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
