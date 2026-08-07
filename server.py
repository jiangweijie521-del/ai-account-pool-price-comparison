from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import hmac
import ipaddress
import json
import math
import os
import re
import socket
import sqlite3
import sys
import threading
import time
import webbrowser
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from html import unescape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Optional
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
API_ROOT = "https://pay.ldxp.cn"
REFRESH_SECONDS = 300
CACHE_SECONDS = 290
PERSIST_SECONDS = 15 * 60
UPSTREAM_MIN_INTERVAL = 0.25
HTTP_TIMEOUT = 20
SERVICE_VERSION = "2026-08-07.1"
MAX_RESPONSE_BYTES = 12 * 1024 * 1024
PAGE_SIZE = 200
MAX_PAGES = 20
CACHE_FILE = ROOT / "inventory-cache.json"
ANALYTICS_DB_FILE = Path(os.environ.get("ANALYTICS_DB_FILE", ROOT / "analytics.sqlite3"))
ANALYTICS_HASH_SECRET_FILE = Path(os.environ.get("ANALYTICS_HASH_SECRET_FILE", ROOT / "analytics-secret.key"))
ANALYTICS_ADMIN_PASSWORD_FILE = Path(
    os.environ.get("ANALYTICS_ADMIN_PASSWORD_FILE", ROOT / "analytics-admin-password.txt")
)
ANALYTICS_ADMIN_USER = os.environ.get("ANALYTICS_ADMIN_USER", "admin")
ANALYTICS_ADMIN_PASSWORD: Optional[str] = os.environ.get("ANALYTICS_ADMIN_PASSWORD")
ANALYTICS_HASH_SECRET: Optional[bytes] = None
ANALYTICS_RETENTION_DAYS = 90
ANALYTICS_MAX_BODY_BYTES = 4096
ANALYTICS_DURATION_GRACE_SECONDS = 5

SHOPS = (
    {"name": "硬核HENRY", "token": "VAELFLP1", "url": f"{API_ROOT}/shop/VAELFLP1"},
    {"name": "GPT2026", "token": "GH2RA4MP", "url": f"{API_ROOT}/shop/GH2RA4MP"},
    {"name": "昆仑081", "token": "JNHUK2WC", "url": f"{API_ROOT}/shop/JNHUK2WC"},
    {"name": "codex嘻嘻", "token": "BH4F39F6", "url": f"{API_ROOT}/shop/BH4F39F6"},
)

GOODS_TYPES = ("card", "article", "resource", "equity")
TYPE_LABELS = {"card": "卡密", "article": "文章", "resource": "资源", "equity": "权益"}

GROUP_ORDER = (
    "GPT Free",
    "GPT Plus · 已接码",
    "GPT Plus · 未接码",
    "GPT Plus · 成品号",
    "GPT Plus · 代充",
    "Codex 接码",
    "OpenAI K12",
    "OpenAI Team",
    "GPT Pro",
    "Gemini",
    "Claude",
    "Grok",
    "iCloud 邮箱",
    "Outlook 邮箱",
    "Gmail 邮箱",
    "Telegram",
)

STATIC_FILES = {
    "/": ("index.html", "text/html; charset=utf-8"),
    "/index.html": ("index.html", "text/html; charset=utf-8"),
    "/styles.css": ("styles.css", "text/css; charset=utf-8"),
    "/app.js": ("app.js", "text/javascript; charset=utf-8"),
    "/analytics.js": ("analytics.js", "text/javascript; charset=utf-8"),
    "/admin": ("admin.html", "text/html; charset=utf-8"),
    "/admin/": ("admin.html", "text/html; charset=utf-8"),
    "/admin.html": ("admin.html", "text/html; charset=utf-8"),
    "/admin.css": ("admin.css", "text/css; charset=utf-8"),
    "/admin.js": ("admin.js", "text/javascript; charset=utf-8"),
    "/assets/paper-fiber.svg": ("assets/paper-fiber.svg", "image/svg+xml"),
    "/assets/ink-mask.svg": ("assets/ink-mask.svg", "image/svg+xml"),
    "/assets/stamp-frame.svg": ("assets/stamp-frame.svg", "image/svg+xml"),
    "/assets/NotoSansSC-Bold.otf": ("assets/NotoSansSC-Bold.otf", "font/otf"),
}

STATE_LOCK = threading.Lock()
CACHE: dict[str, Any] = {"stored_at": 0.0, "payload": None}
LAST_GOOD: dict[str, dict[str, Any]] = {}
LAST_PERSISTED_AT = 0.0
UPSTREAM_RATE_LOCK = threading.Lock()
UPSTREAM_NEXT_REQUEST_AT = 0.0
ANALYTICS_LOCK = threading.Lock()

TAG_RE = re.compile(r"<[^>]+>")
SPACE_RE = re.compile(r"\s+")
NON_WORD_RE = re.compile(r"[\W_]+", re.UNICODE)
ANALYTICS_SESSION_RE = re.compile(r"^[A-Za-z0-9_-]{16,64}$")
ADMIN_PATHS = {"/admin", "/admin/", "/admin.html", "/admin.css", "/admin.js", "/api/admin/analytics"}


def clean_text(value: Any) -> str:
    text = unescape(str(value or ""))
    text = TAG_RE.sub(" ", text)
    return SPACE_RE.sub(" ", text).strip()


def normalized_text(*parts: Any) -> str:
    text = " ".join(clean_text(part) for part in parts).casefold()
    aliases = {
        "chat gp-t": "chatgpt",
        "chat gpt": "chatgpt",
        "open ai": "openai",
        "gptplus": "gpt plus",
        "icloud": "icloud",
        "cloude": "cloud",
    }
    for source, target in aliases.items():
        text = text.replace(source, target)
    return SPACE_RE.sub(" ", text).strip()


def canonical_name(name: Any) -> str:
    return NON_WORD_RE.sub("", normalized_text(name))


def classify(name: Any, category: Any, goods_type: str = "card") -> str:
    name_text = normalized_text(name)
    category_text = normalized_text(category)
    text = normalized_text(name, category)

    if goods_type != "card":
        label = TYPE_LABELS.get(goods_type, "资料")
        return f"{label} · {clean_text(category) or '未分类'}"[:28]

    if any(term in name_text for term in ("教程", "使用指南", "部署说明")):
        return f"教程 · {clean_text(category) or '未分类'}"[:28]

    if ("gpt" in text or "openai" in text) and re.search(r"\bpro\b|pro\s*(?:5|20)x", text):
        return "GPT Pro"

    if "gemini" in name_text or "反重力" in name_text:
        return "Gemini"
    if "claude" in name_text:
        return "Claude"
    if "grok" in name_text:
        return "Grok"

    if "free" in text and any(term in text for term in ("gpt", "openai", "codex")):
        return "GPT Free"

    codex_service = "codex" in name_text and any(term in name_text for term in ("接码", "手机验证", "实体卡"))
    account_product = any(term in name_text for term in ("成品号", "账号", "会员", "月卡", "周额度"))
    if codex_service and not account_product:
        return "Codex 接码"

    name_has_plus = "plus" in name_text or "gpt+" in name_text
    if not name_has_plus:
        if "icloud" in name_text:
            return "iCloud 邮箱"
        if any(term in name_text for term in ("outlook", "微软邮箱", "hotmail")):
            return "Outlook 邮箱"
        if any(term in name_text for term in ("gmail", "谷歌邮箱")):
            return "Gmail 邮箱"

    if name_has_plus or "plus" in category_text or "gpt+" in category_text:
        if any(term in name_text for term in ("代充", "充值", "开通", "自助充")):
            return "GPT Plus · 代充"
        if any(
            term in text
            for term in (
                "未接码",
                "没有接码",
                "没绑定手机",
                "未绑手机",
                "要接码",
                "需要接码",
                "只能登录网页版",
                "只能用网页",
                "半成品",
            )
        ):
            return "GPT Plus · 未接码"
        if any(term in text for term in ("已接码", "已绑手机", "已绑定手机")):
            return "GPT Plus · 已接码"
        return "GPT Plus · 成品号"

    if "openai普通账号" in text or ("白号" in text and any(term in text for term in ("gpt", "openai", "codex"))):
        return "GPT Free"

    if "codex" in text and any(term in text for term in ("接码", "手机验证", "实体卡")):
        return "Codex 接码"
    if "k12" in name_text or "k12" in category_text:
        return "OpenAI K12"
    if re.search(r"\bteam\b", name_text) or "团队" in name_text or "team" in category_text:
        return "OpenAI Team"
    if "gemini" in category_text or "反重力" in category_text:
        return "Gemini"
    if "claude" in category_text:
        return "Claude"
    if "grok" in category_text:
        return "Grok"
    if any(term in text for term in ("telegram", "电报", "飞机", "gram 账号", "tg/")):
        return "Telegram"
    if "icloud" in text:
        return "iCloud 邮箱"
    if any(term in text for term in ("outlook", "微软邮箱", "hotmail")):
        return "Outlook 邮箱"
    if any(term in text for term in ("gmail", "谷歌邮箱")):
        return "Gmail 邮箱"
    if "接码" in text:
        return "其他接码服务"

    fallback = clean_text(category) or TYPE_LABELS.get(goods_type, "其他商品")
    return fallback[:28]


def group_rank(group: str) -> int:
    try:
        return GROUP_ORDER.index(group)
    except ValueError:
        return len(GROUP_ORDER)


def extract_tags(name: Any, goods_type: str) -> list[str]:
    text = normalized_text(name)
    tags: list[str] = []

    if any(term in text for term in ("未接码", "要接码", "需要接码", "没绑定手机", "未绑手机")):
        tags.append("未接码")
    elif any(term in text for term in ("已接码", "已绑手机", "已绑定手机")):
        tags.append("已接码")

    if "质保" in text:
        match = re.search(r"质保\s*(\d+\s*(?:天|小时|分钟)|首登|首次登录|首次登陆)", text)
        tags.append(f"质保{SPACE_RE.sub('', match.group(1))}" if match else "含质保")

    if any(term in text for term in ("只能登录网页版", "只能用网页", "网页版本")):
        tags.append("仅网页")
    elif "反代" in text:
        tags.append("含反代说明")

    if goods_type != "card":
        tags.append(TYPE_LABELS.get(goods_type, goods_type))
    return tags[:3]


def safe_product_link(value: Any, goods_key: str) -> str:
    link = clean_text(value)
    prefix = f"{API_ROOT}/item/"
    if link.startswith(prefix) and re.fullmatch(r"[A-Za-z0-9]+", link.removeprefix(prefix)):
        return link
    if re.fullmatch(r"[A-Za-z0-9]+", goods_key):
        return f"{prefix}{goods_key}"
    return API_ROOT


def transform_item(raw: dict[str, Any], shop: dict[str, str], goods_type: str) -> dict[str, Any] | None:
    name = clean_text(raw.get("name"))
    goods_key = clean_text(raw.get("goods_key"))
    if not name or not goods_key:
        return None

    try:
        price = float(raw.get("price"))
    except (TypeError, ValueError):
        return None
    if not math.isfinite(price) or price < 0:
        return None

    category_data = raw.get("category") if isinstance(raw.get("category"), dict) else {}
    category = clean_text(category_data.get("name")) or "未分类"
    extend = raw.get("extend") if isinstance(raw.get("extend"), dict) else {}
    stock_raw = extend.get("stock_count")
    stock: int | None
    try:
        stock = None if stock_raw is None else max(0, int(stock_raw))
    except (TypeError, ValueError):
        stock = None

    available = stock > 0 if stock is not None else goods_type != "card"
    group = classify(name, category, goods_type)
    return {
        "key": goods_key,
        "name": name,
        "price": price,
        "stock": stock,
        "available": available,
        "category": category,
        "group": group,
        "group_rank": group_rank(group),
        "goods_type": goods_type,
        "goods_type_label": TYPE_LABELS.get(goods_type, goods_type),
        "shop": shop["name"],
        "shop_token": shop["token"],
        "shop_url": shop["url"],
        "link": safe_product_link(raw.get("link"), goods_key),
        "tags": extract_tags(name, goods_type),
        "canonical": canonical_name(name),
    }


def wait_for_upstream_slot() -> None:
    global UPSTREAM_NEXT_REQUEST_AT
    with UPSTREAM_RATE_LOCK:
        now = time.monotonic()
        scheduled_at = max(now, UPSTREAM_NEXT_REQUEST_AT)
        UPSTREAM_NEXT_REQUEST_AT = scheduled_at + UPSTREAM_MIN_INTERVAL
    if scheduled_at > now:
        time.sleep(scheduled_at - now)


def api_post(path: str, payload: dict[str, Any], token: str) -> dict[str, Any]:
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    request = Request(
        f"{API_ROOT}{path}",
        data=body,
        method="POST",
        headers={
            "Accept": "application/json",
            "Content-Type": "application/json; charset=utf-8",
            "Referer": f"{API_ROOT}/shop/{token}",
            "User-Agent": "InventoryComparator/1.0 (+local personal dashboard)",
        },
    )
    wait_for_upstream_slot()
    with urlopen(request, timeout=HTTP_TIMEOUT) as response:
        raw = response.read(MAX_RESPONSE_BYTES + 1)
    if len(raw) > MAX_RESPONSE_BYTES:
        raise RuntimeError("远端响应过大")
    result = json.loads(raw.decode("utf-8"))
    if not isinstance(result, dict) or result.get("code") != 1:
        raise RuntimeError("远端接口返回失败")
    return result


def fetch_goods_type(shop: dict[str, str], goods_type: str) -> list[dict[str, Any]]:
    items: list[dict[str, Any]] = []
    received = 0
    for page in range(1, MAX_PAGES + 1):
        result = api_post(
            "/shopApi/Shop/goodsList",
            {
                "token": shop["token"],
                "keywords": "",
                "category_id": 0,
                "goods_type": goods_type,
                "current": page,
                "pageSize": PAGE_SIZE,
            },
            shop["token"],
        )
        data = result.get("data") if isinstance(result.get("data"), dict) else {}
        rows = data.get("list") if isinstance(data.get("list"), list) else []
        received += len(rows)
        for row in rows:
            if isinstance(row, dict):
                item = transform_item(row, shop, goods_type)
                if item is not None:
                    items.append(item)

        try:
            total = int(data.get("total", received))
        except (TypeError, ValueError):
            total = received
        if not rows or len(rows) < PAGE_SIZE or received >= total:
            break
    return items


def fetch_shop(shop: dict[str, str]) -> dict[str, Any]:
    info_reply = api_post("/shopApi/Shop/info", {"token": shop["token"]}, shop["token"])
    info = info_reply.get("data") if isinstance(info_reply.get("data"), dict) else {}
    nickname = clean_text(info.get("nickname")) or shop["name"]

    items: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for goods_type in GOODS_TYPES:
        for item in fetch_goods_type(shop, goods_type):
            identity = (item["shop_token"], item["key"])
            if identity not in seen:
                seen.add(identity)
                items.append(item)

    return {
        "name": shop["name"],
        "nickname": nickname,
        "token": shop["token"],
        "url": shop["url"],
        "ok": True,
        "stale": False,
        "message": "读取成功",
        "declared_count": int(info.get("goods_count") or 0),
        "item_count": len(items),
        "items": items,
    }


def friendly_error(error: Exception) -> str:
    if isinstance(error, HTTPError):
        return f"远端返回 HTTP {error.code}"
    if isinstance(error, (URLError, TimeoutError, socket.timeout)):
        return "网络连接超时或中断"
    if isinstance(error, json.JSONDecodeError):
        return "远端数据格式异常"
    return "读取失败"


def collect_inventory() -> dict[str, Any]:
    results: dict[str, dict[str, Any]] = {}
    errors: dict[str, str] = {}

    with ThreadPoolExecutor(max_workers=len(SHOPS)) as pool:
        futures = {pool.submit(fetch_shop, shop): shop for shop in SHOPS}
        for future in as_completed(futures):
            shop = futures[future]
            token = shop["token"]
            try:
                result = future.result()
                LAST_GOOD[token] = copy.deepcopy(result)
                results[token] = result
            except Exception as error:  # one shop must not blank the whole page
                message = friendly_error(error)
                errors[token] = message
                if token in LAST_GOOD:
                    stale = copy.deepcopy(LAST_GOOD[token])
                    stale.update({"ok": False, "stale": True, "message": f"{message}，显示上次数据"})
                    results[token] = stale
                else:
                    results[token] = {
                        "name": shop["name"],
                        "nickname": shop["name"],
                        "token": token,
                        "url": shop["url"],
                        "ok": False,
                        "stale": False,
                        "message": message,
                        "declared_count": 0,
                        "item_count": 0,
                        "items": [],
                    }

    shops = [results[shop["token"]] for shop in SHOPS]
    items = [item for shop in shops for item in shop["items"]]

    duplicate_shops: dict[str, set[str]] = {}
    for item in items:
        if len(item["canonical"]) >= 8:
            duplicate_shops.setdefault(item["canonical"], set()).add(item["shop_token"])
    for item in items:
        item["same_product_shops"] = len(duplicate_shops.get(item["canonical"], set()))

    items.sort(key=lambda item: (item["group_rank"], item["group"], not item["available"], item["price"], item["shop"]))
    available_count = sum(1 for item in items if item["available"])
    fresh_shop_count = sum(1 for shop in shops if shop["ok"])
    stale_shop_count = sum(1 for shop in shops if shop["stale"])

    return {
        "ok": fresh_shop_count > 0 or stale_shop_count > 0,
        "partial": bool(errors),
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "refresh_seconds": REFRESH_SECONDS,
        "summary": {
            "total": len(items),
            "available": available_count,
            "out_of_stock": len(items) - available_count,
            "groups": len({item["group"] for item in items}),
            "shops_fresh": fresh_shop_count,
            "shops_stale": stale_shop_count,
            "shops_total": len(SHOPS),
        },
        "shops": [{key: value for key, value in shop.items() if key != "items"} for shop in shops],
        "items": items,
    }


def load_persisted_cache() -> Optional[dict[str, Any]]:
    try:
        payload = json.loads(CACHE_FILE.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    if not isinstance(payload, dict) or not isinstance(payload.get("shops"), list) or not isinstance(payload.get("items"), list):
        return None

    configured_tokens = {shop["token"] for shop in SHOPS}
    items_by_shop = {token: [] for token in configured_tokens}
    for item in payload["items"]:
        if isinstance(item, dict) and item.get("shop_token") in items_by_shop:
            items_by_shop[item["shop_token"]].append(copy.deepcopy(item))
    for shop in payload["shops"]:
        if not isinstance(shop, dict) or shop.get("token") not in configured_tokens:
            continue
        restored = copy.deepcopy(shop)
        restored.update({"ok": True, "stale": False, "message": "读取成功", "items": items_by_shop[shop["token"]]})
        LAST_GOOD[shop["token"]] = restored
    return payload if LAST_GOOD else None


def save_persisted_cache(payload: dict[str, Any]) -> None:
    global LAST_PERSISTED_AT
    fresh_count = payload.get("summary", {}).get("shops_fresh", 0)
    if not fresh_count or (CACHE_FILE.exists() and time.monotonic() - LAST_PERSISTED_AT < PERSIST_SECONDS):
        return
    temporary = CACHE_FILE.with_suffix(".json.tmp")
    try:
        temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
        temporary.replace(CACHE_FILE)
        LAST_PERSISTED_AT = time.monotonic()
    except OSError:
        temporary.unlink(missing_ok=True)


def get_inventory(force: bool = False) -> dict[str, Any]:
    with STATE_LOCK:
        if CACHE["payload"] is None:
            CACHE["payload"] = load_persisted_cache()
        age = time.monotonic() - float(CACHE["stored_at"])
        if CACHE["payload"] is not None and age < CACHE_SECONDS:
            return copy.deepcopy(CACHE["payload"])
        payload = collect_inventory()
        save_persisted_cache(payload)
        CACHE.update({"stored_at": time.monotonic(), "payload": copy.deepcopy(payload)})
        return payload


def get_analytics_secret() -> bytes:
    global ANALYTICS_HASH_SECRET
    if ANALYTICS_HASH_SECRET is not None:
        return ANALYTICS_HASH_SECRET
    with ANALYTICS_LOCK:
        if ANALYTICS_HASH_SECRET is not None:
            return ANALYTICS_HASH_SECRET
        try:
            secret = ANALYTICS_HASH_SECRET_FILE.read_bytes()
        except FileNotFoundError:
            ANALYTICS_HASH_SECRET_FILE.parent.mkdir(parents=True, exist_ok=True)
            secret = os.urandom(32)
            try:
                descriptor = os.open(ANALYTICS_HASH_SECRET_FILE, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
            except FileExistsError:
                secret = ANALYTICS_HASH_SECRET_FILE.read_bytes()
            else:
                with os.fdopen(descriptor, "wb") as handle:
                    handle.write(secret)
        if len(secret) < 32:
            raise ValueError("analytics hash secret must contain at least 32 bytes")
        ANALYTICS_HASH_SECRET = secret
        return secret


def get_analytics_admin_password() -> Optional[str]:
    global ANALYTICS_ADMIN_PASSWORD
    if ANALYTICS_ADMIN_PASSWORD:
        return ANALYTICS_ADMIN_PASSWORD
    try:
        password = ANALYTICS_ADMIN_PASSWORD_FILE.read_text(encoding="utf-8").strip()
    except (OSError, UnicodeDecodeError):
        return None
    if len(password) < 20:
        return None
    ANALYTICS_ADMIN_PASSWORD = password
    return password


def hash_visitor(client_ip: str, day: str, secret: bytes) -> str:
    message = f"{day}\0{client_ip}".encode("utf-8")
    return hmac.new(secret, message, hashlib.sha256).hexdigest()


def analytics_connection(database: Path) -> sqlite3.Connection:
    database.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(str(database), timeout=5)
    try:
        os.chmod(database, 0o600)
    except OSError:
        connection.close()
        raise
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS visitors (
            day TEXT NOT NULL,
            visitor_hash TEXT NOT NULL,
            PRIMARY KEY (day, visitor_hash)
        );
        CREATE TABLE IF NOT EXISTS sessions (
            session_id TEXT NOT NULL,
            day TEXT NOT NULL,
            visitor_hash TEXT NOT NULL,
            started_at INTEGER NOT NULL,
            last_seen INTEGER NOT NULL,
            active_seconds INTEGER NOT NULL DEFAULT 0,
            PRIMARY KEY (session_id, day)
        );
        CREATE INDEX IF NOT EXISTS sessions_day_idx ON sessions(day);
        """
    )
    return connection


def record_analytics_event(
    database: Path,
    secret: bytes,
    client_ip: str,
    session_id: str,
    active_seconds: int,
    now: Optional[datetime] = None,
) -> None:
    if not ANALYTICS_SESSION_RE.fullmatch(session_id):
        raise ValueError("invalid analytics session")
    moment = now or datetime.now().astimezone()
    day = moment.date().isoformat()
    timestamp = int(moment.timestamp())
    visitor_hash = hash_visitor(client_ip, day, secret)
    requested_duration = max(0, min(int(active_seconds), 24 * 60 * 60))
    cutoff = (moment.date() - timedelta(days=ANALYTICS_RETENTION_DAYS)).isoformat()

    with ANALYTICS_LOCK, analytics_connection(database) as connection:
        connection.execute(
            "INSERT OR IGNORE INTO visitors(day, visitor_hash) VALUES (?, ?)",
            (day, visitor_hash),
        )
        connection.execute(
            """
            INSERT OR IGNORE INTO sessions(
                session_id, day, visitor_hash, started_at, last_seen, active_seconds
            ) VALUES (?, ?, ?, ?, ?, 0)
            """,
            (session_id, day, visitor_hash, timestamp, timestamp),
        )
        row = connection.execute(
            "SELECT started_at FROM sessions WHERE session_id = ? AND day = ? AND visitor_hash = ?",
            (session_id, day, visitor_hash),
        ).fetchone()
        if row is not None:
            wall_time = max(0, timestamp - int(row["started_at"]))
            safe_duration = min(requested_duration, wall_time + ANALYTICS_DURATION_GRACE_SECONDS)
            connection.execute(
                """
                UPDATE sessions
                SET last_seen = MAX(last_seen, ?), active_seconds = MAX(active_seconds, ?)
                WHERE session_id = ? AND day = ? AND visitor_hash = ?
                """,
                (timestamp, safe_duration, session_id, day, visitor_hash),
            )
        connection.execute("DELETE FROM sessions WHERE day < ?", (cutoff,))
        connection.execute("DELETE FROM visitors WHERE day < ?", (cutoff,))


def get_analytics_summary(
    database: Path,
    days: int = 30,
    now: Optional[datetime] = None,
) -> dict[str, Any]:
    moment = now or datetime.now().astimezone()
    days = max(1, min(int(days), ANALYTICS_RETENTION_DAYS))
    cutoff = (moment.date() - timedelta(days=days - 1)).isoformat()
    with ANALYTICS_LOCK, analytics_connection(database) as connection:
        rows = connection.execute(
            """
            SELECT
                visitors.day AS day,
                COUNT(DISTINCT visitors.visitor_hash) AS unique_ips,
                COUNT(sessions.session_id) AS visits,
                COALESCE(ROUND(AVG(sessions.active_seconds)), 0) AS average_seconds,
                COALESCE(SUM(sessions.active_seconds), 0) AS total_seconds
            FROM visitors
            LEFT JOIN sessions
              ON sessions.day = visitors.day
             AND sessions.visitor_hash = visitors.visitor_hash
            WHERE visitors.day >= ?
            GROUP BY visitors.day
            ORDER BY visitors.day DESC
            """,
            (cutoff,),
        ).fetchall()
    return {
        "generated_at": moment.isoformat(timespec="seconds"),
        "retention_days": ANALYTICS_RETENTION_DAYS,
        "days": [
            {
                "date": row["day"],
                "unique_ips": int(row["unique_ips"]),
                "visits": int(row["visits"]),
                "average_seconds": int(row["average_seconds"]),
                "total_seconds": int(row["total_seconds"]),
            }
            for row in rows
        ],
    }


def valid_basic_auth(header: Optional[str], username: str, password: str) -> bool:
    if not header or not header.startswith("Basic "):
        return False
    try:
        decoded = base64.b64decode(header[6:], validate=True).decode("utf-8")
    except (ValueError, UnicodeDecodeError):
        return False
    supplied_user, separator, supplied_password = decoded.partition(":")
    return bool(separator) and hmac.compare_digest(supplied_user, username) and hmac.compare_digest(
        supplied_password, password
    )


def normalized_client_ip(candidate: str, fallback: str) -> str:
    try:
        return ipaddress.ip_address(candidate.strip()).compressed
    except ValueError:
        return ipaddress.ip_address(fallback).compressed


class AppHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def send_bytes(
        self,
        status: int,
        body: bytes,
        content_type: str,
        extra_headers: Optional[dict[str, str]] = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        self.send_header("Permissions-Policy", "camera=(), geolocation=(), microphone=()")
        self.send_header("Content-Security-Policy", "default-src 'self'; connect-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; base-uri 'none'; form-action 'none'; frame-ancestors 'none'")
        for name, value in (extra_headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def send_json(self, status: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
        self.send_bytes(status, body, "application/json; charset=utf-8")

    def require_admin(self) -> bool:
        password = get_analytics_admin_password()
        if password is None:
            self.send_bytes(503, "后台尚未配置".encode("utf-8"), "text/plain; charset=utf-8")
            return False
        if valid_basic_auth(self.headers.get("Authorization"), ANALYTICS_ADMIN_USER, password):
            return True
        self.send_bytes(
            401,
            "需要后台凭据".encode("utf-8"),
            "text/plain; charset=utf-8",
            {"WWW-Authenticate": 'Basic realm="Stock analytics", charset="UTF-8"'},
        )
        return False

    def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path in ADMIN_PATHS and not self.require_admin():
            return
        if parsed.path == "/api/health":
            self.send_json(200, {"ok": True, "service": "stock-comparison", "version": SERVICE_VERSION})
            return
        if parsed.path == "/api/inventory":
            try:
                force = parse_qs(parsed.query).get("refresh", ["0"])[0] == "1"
                self.send_json(200, get_inventory(force=force))
            except Exception:
                self.send_json(502, {"ok": False, "message": "库存服务暂时读取失败，请稍后点“立即刷新”。"})
            return
        if parsed.path == "/api/admin/analytics":
            try:
                days = int(parse_qs(parsed.query).get("days", ["30"])[0])
                payload = get_analytics_summary(ANALYTICS_DB_FILE, days)
                self.send_json(200, payload)
            except (OSError, sqlite3.Error, ValueError):
                self.send_json(503, {"ok": False, "message": "统计数据暂时不可用"})
            return

        static = STATIC_FILES.get(parsed.path)
        if static is None:
            self.send_bytes(404, "未找到页面".encode("utf-8"), "text/plain; charset=utf-8")
            return
        filename, content_type = static
        try:
            headers = {"X-Robots-Tag": "noindex, nofollow"} if parsed.path in ADMIN_PATHS else None
            self.send_bytes(200, (ROOT / filename).read_bytes(), content_type, headers)
        except FileNotFoundError:
            self.send_bytes(404, "页面文件缺失".encode("utf-8"), "text/plain; charset=utf-8")

    def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
        parsed = urlparse(self.path)
        if parsed.path != "/api/analytics/session":
            self.send_bytes(404, "未找到接口".encode("utf-8"), "text/plain; charset=utf-8")
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            if length <= 0 or length > ANALYTICS_MAX_BODY_BYTES:
                raise ValueError("invalid body length")
            payload = json.loads(self.rfile.read(length))
            session_id = payload.get("session_id")
            active_seconds = payload.get("active_seconds")
            if not isinstance(session_id, str) or not isinstance(active_seconds, int) or isinstance(active_seconds, bool):
                raise ValueError("invalid analytics payload")
            forwarded_ip = self.headers.get("CF-Connecting-IP", self.client_address[0])
            client_ip = normalized_client_ip(forwarded_ip, self.client_address[0])
            record_analytics_event(
                ANALYTICS_DB_FILE,
                get_analytics_secret(),
                client_ip,
                session_id,
                active_seconds,
            )
        except (ValueError, json.JSONDecodeError):
            self.send_json(400, {"ok": False, "message": "统计请求格式无效"})
            return
        except (OSError, sqlite3.Error):
            self.send_json(503, {"ok": False, "message": "统计服务暂时不可用"})
            return
        self.send_bytes(204, b"", "text/plain; charset=utf-8")

    def log_message(self, format_string: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {format_string % args}")


class AppServer(ThreadingHTTPServer):
    allow_reuse_address = False

    def server_bind(self) -> None:
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def run_self_test() -> None:
    global UPSTREAM_NEXT_REQUEST_AT
    assert classify("【Chat GP-T Free号】已绑手机，可用Codex", "gpt低价") == "GPT Free"
    assert classify("低价 Plus成品号（登录codex要接码）", "PLUS") == "GPT Plus · 未接码"
    assert classify("Plus 已接码成品号", "PLUS") == "GPT Plus · 已接码"
    assert classify("Codex 接码 美国实体卡", "接码服务") == "Codex 接码"
    assert classify("Gemini Pro 12个月", "Gemini") == "Gemini"
    assert classify("iCloud邮箱", "plus手搓商品") == "iCloud 邮箱"
    assert classify("【正规货付】Super Grok 12个月", "K12") == "Grok"
    assert classify("一键部署本地中转站", "K12", "resource") == "资源 · K12"
    assert classify("【教程】未接码plus gpt号接码并导入教程", "GPT") == "教程 · GPT"
    assert classify("美国实体卡长效接码codex绑定注册通用 PLUS接码", "接码") == "Codex 接码"
    assert classify("Codex Free(Gmail注册)", "Gpt Free") == "GPT Free"
    assert canonical_name(" Plus 成品号！ ") == canonical_name("plus-成品号")
    CACHE.update({"stored_at": time.monotonic(), "payload": {"ok": True, "marker": "shared-cache"}})
    assert get_inventory(force=True)["marker"] == "shared-cache"
    CACHE.update({"stored_at": 0.0, "payload": None})
    assert 240 <= CACHE_SECONDS < REFRESH_SECONDS
    UPSTREAM_NEXT_REQUEST_AT = 0.0
    started_at = time.monotonic()
    wait_for_upstream_slot()
    wait_for_upstream_slot()
    assert time.monotonic() - started_at >= UPSTREAM_MIN_INTERVAL * 0.9
    UPSTREAM_NEXT_REQUEST_AT = 0.0
    print("SELF_TEST_OK: 15 checks")


def find_server(host: str, preferred_port: int) -> ThreadingHTTPServer:
    for port in range(preferred_port, preferred_port + 10):
        try:
            return AppServer((host, port), AppHandler)
        except OSError:
            continue
    raise OSError(f"端口 {preferred_port}-{preferred_port + 9} 都被占用")


def main() -> int:
    parser = argparse.ArgumentParser(description="本地库存比价台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--exact-port", action="store_true", help="端口被占用时直接失败，供常驻部署使用")
    parser.add_argument("--open", action="store_true", dest="open_browser")
    parser.add_argument("--self-test", action="store_true")
    parser.add_argument("--fetch-once", action="store_true")
    args = parser.parse_args()

    if args.self_test:
        run_self_test()
        return 0
    if args.fetch_once:
        payload = get_inventory(force=True)
        print(json.dumps({"ok": payload["ok"], "partial": payload["partial"], **payload["summary"]}, ensure_ascii=False))
        return 0 if payload["ok"] else 1

    server = AppServer((args.host, args.port), AppHandler) if args.exact_port else find_server(args.host, args.port)
    host, port = server.server_address[:2]
    url = f"http://{host}:{port}/"
    print(f"库存比价台已启动：{url}")
    print("关闭这个窗口即可停止服务。")
    if args.open_browser:
        threading.Timer(0.5, lambda: webbrowser.open(url)).start()
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
