from __future__ import annotations

import argparse
import json
import logging
import logging.handlers
import os
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from urllib.parse import urljoin
from urllib.request import Request, urlopen


ROOT = Path(__file__).resolve().parent
DEFAULT_DATABASE = Path(os.environ.get("ANALYTICS_DB_FILE", ROOT / "analytics.sqlite3"))
DEFAULT_BACKUP_DIR = Path(os.environ.get("ANALYTICS_BACKUP_DIR", ROOT / "backups"))
DEFAULT_STATE_FILE = Path(os.environ.get("MONITOR_STATE_FILE", ROOT / "monitor-state.json"))
DEFAULT_LOG_FILE = Path(os.environ.get("OPS_LOG_FILE", ROOT / "ops.log"))
DEFAULT_BASE_URLS = ("http://127.0.0.1:18768/", "https://stock.ultraai.site/")


def get_logger(log_file: Path = DEFAULT_LOG_FILE) -> logging.Logger:
    logger = logging.getLogger(f"stock-comparison.ops.{log_file}")
    logger.setLevel(logging.INFO)
    logger.propagate = False
    if not logger.handlers:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            log_file,
            maxBytes=1024 * 1024,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        logger.addHandler(handler)
    return logger


def backup_database(
    database: Path,
    backup_dir: Path,
    keep: int = 14,
    now: Optional[datetime] = None,
) -> Path:
    if not database.is_file():
        raise FileNotFoundError(f"analytics database does not exist: {database}")
    keep = max(1, int(keep))
    moment = now or datetime.now().astimezone()
    backup_dir.mkdir(parents=True, exist_ok=True)
    destination = backup_dir / f"analytics-{moment.strftime('%Y%m%d-%H%M%S-%f')}.sqlite3"
    temporary = destination.with_suffix(".sqlite3.tmp")

    def remove_temporary_files() -> None:
        temporary.unlink(missing_ok=True)
        Path(f"{temporary}-wal").unlink(missing_ok=True)
        Path(f"{temporary}-shm").unlink(missing_ok=True)

    remove_temporary_files()
    try:
        with sqlite3.connect(database) as source, sqlite3.connect(temporary) as target:
            source.backup(target)
        os.chmod(temporary, 0o600)
        with sqlite3.connect(temporary) as check:
            result = check.execute("PRAGMA integrity_check").fetchone()[0]
        if result != "ok":
            raise sqlite3.DatabaseError(f"backup integrity check failed: {result}")
        temporary.replace(destination)
    finally:
        remove_temporary_files()

    backups = sorted(backup_dir.glob("analytics-*.sqlite3"), reverse=True)
    for expired in backups[keep:]:
        expired.unlink()
    return destination


def read_json(url: str, timeout: float = 20) -> dict[str, Any]:
    request = Request(url, headers={"Accept": "application/json", "User-Agent": "StockComparisonMonitor/1.0"})
    with urlopen(request, timeout=timeout) as response:
        if response.status != 200:
            raise RuntimeError(f"{url} returned HTTP {response.status}")
        payload = json.load(response)
    if not isinstance(payload, dict):
        raise RuntimeError(f"{url} returned a non-object payload")
    return payload


def monitor_base_url(base_url: str, timeout: float = 20) -> dict[str, Any]:
    normalized = base_url.rstrip("/") + "/"
    health = read_json(urljoin(normalized, "api/health"), timeout)
    if health.get("ok") is not True or health.get("service") != "stock-comparison":
        raise RuntimeError(f"{normalized} health payload is unhealthy")

    inventory = read_json(urljoin(normalized, "api/inventory"), timeout)
    summary = inventory.get("summary") if isinstance(inventory.get("summary"), dict) else {}
    if inventory.get("ok") is not True:
        raise RuntimeError(f"{normalized} inventory payload is unhealthy")
    if inventory.get("partial") is True:
        raise RuntimeError(f"{normalized} inventory is partial")
    if int(summary.get("shops_fresh", 0)) != int(summary.get("shops_total", 0)):
        raise RuntimeError(f"{normalized} inventory does not contain all fresh shops")
    return {
        "base_url": normalized,
        "version": health.get("version"),
        "revision": health.get("revision"),
        "items": int(summary.get("total", 0)),
        "shops_fresh": int(summary.get("shops_fresh", 0)),
    }


def write_monitor_state(state_file: Path, payload: dict[str, Any]) -> None:
    state_file.parent.mkdir(parents=True, exist_ok=True)
    temporary = state_file.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    temporary.replace(state_file)


def run_monitor(base_urls: list[str], state_file: Path, timeout: float = 20) -> dict[str, Any]:
    checked_at = datetime.now().astimezone().isoformat(timespec="seconds")
    checks = [monitor_base_url(base_url, timeout) for base_url in base_urls]
    result = {"ok": True, "checked_at": checked_at, "checks": checks}
    write_monitor_state(state_file, result)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description="Stock Comparison backup and production monitor")
    subparsers = parser.add_subparsers(dest="command", required=True)

    backup_parser = subparsers.add_parser("backup")
    backup_parser.add_argument("--database", type=Path, default=DEFAULT_DATABASE)
    backup_parser.add_argument("--backup-dir", type=Path, default=DEFAULT_BACKUP_DIR)
    backup_parser.add_argument("--keep", type=int, default=14)

    monitor_parser = subparsers.add_parser("monitor")
    monitor_parser.add_argument("--base-url", action="append", dest="base_urls")
    monitor_parser.add_argument("--state-file", type=Path, default=DEFAULT_STATE_FILE)
    monitor_parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()
    logger = get_logger()

    try:
        if args.command == "backup":
            destination = backup_database(args.database, args.backup_dir, args.keep)
            logger.info("analytics backup completed: %s", destination)
        else:
            result = run_monitor(args.base_urls or list(DEFAULT_BASE_URLS), args.state_file, args.timeout)
            logger.info("production monitor passed: %s", json.dumps(result, ensure_ascii=False, separators=(",", ":")))
    except Exception as error:
        if args.command == "monitor":
            write_monitor_state(
                args.state_file,
                {
                    "ok": False,
                    "checked_at": datetime.now().astimezone().isoformat(timespec="seconds"),
                    "error": str(error),
                },
            )
        logger.error("%s failed: %s", args.command, error)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
