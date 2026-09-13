#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Независимая проверка SLA новостного конвейера без Telegram-вызовов.

Статус сборщика или код Планировщика сам по себе не является успехом. Скрипт
проверяет фактический receipt доставки, run_record и свежесть сбора; результат
пишется в runtime-logs/health-status.json для портала и watchdog.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime, time
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "runtime-logs"
NEWS_ROOT = ROOT / "News Claude"
STATUS = LOG_DIR / "health-status.json"
ALERT_STATE = LOG_DIR / "health-alert-state.json"
SLOTS = (time(9), time(13), time(17))
COLLECTION_SLOTS = (time(8), time(12), time(16))
GRACE_MINUTES = 12


def read_json(path: Path, fallback):
    try:
        # PowerShell 5.1 writes UTF-8 with BOM for Set-Content -Encoding UTF8.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        return fallback


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


def history_by_release() -> dict[str, dict]:
    records = {}
    path = LOG_DIR / "auto-publisher-history.jsonl"
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        release = str(item.get("release") or "")
        if release:
            if release not in records or item.get("status") == "success":
                records[release] = item
    return records


def recorded_delivery_ok(release: str, date: str) -> bool:
    """Bootstrap для выпусков, сделанных до появления status-history."""
    folder = NEWS_ROOT / "pipeline" / "run_records" / date
    for path in folder.glob("*/run_record.json"):
        value = read_json(path, {})
        coverage = value.get("delivery_coverage") or {}
        if (value.get("release") == release and value.get("items_count") == 10
                and coverage.get("delivered_slugs") == 10 and not coverage.get("missing_slugs")):
            return True
    return False


def check_delivery(now: datetime, critical: list[str], details: dict) -> None:
    history = history_by_release()
    records = []
    for slot in SLOTS:
        due = now.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
        if now < due.replace(minute=due.minute + GRACE_MINUTES):
            continue
        release = f"{now:%Y-%m-%d}_{slot.hour:02d}00_editorial"
        item = history.get(release)
        ok = bool(item and item.get("status") == "success" and item.get("delivered_count") == 10
                  and item.get("run_record"))
        if not ok:
            ok = recorded_delivery_ok(release, now.strftime("%Y-%m-%d"))
        records.append({"release": release, "due_at": due.isoformat(), "ok": ok,
                        "status": item.get("status") if item else "missing",
                        "error": item.get("error", "") if item else ""})
        if not ok:
            suffix = f": {item.get('error')}" if item and item.get("error") else ""
            critical.append(f"Нет подтверждённой доставки 10/10 для {release}{suffix}")
    details["deliveries"] = records


def check_collection(now: datetime, critical: list[str], warnings: list[str], details: dict) -> None:
    last = read_json(LOG_DIR / "last-run.json", {})
    if last.get("exit_code") != 0:
        critical.append("Последний запуск сборщика отсутствует или завершился ошибкой")
    date = now.strftime("%Y-%m-%d")
    manifest = read_json(NEWS_ROOT / "pipeline" / "raw" / date / "collection_manifest.json", {})
    sources = manifest.get("sources") or {}
    if not sources:
        critical.append("Нет манифеста сбора за сегодня")
    failed = sorted(key for key, value in sources.items()
                    if value.get("state") in {"failed", "missing"})
    incomplete = sorted(key for key, value in sources.items()
                        if value.get("state") in {"manual", "delegated"})
    if failed:
        warnings.append("Сбой источников: " + ", ".join(failed))
    if incomplete:
        warnings.append("Требуют ручного добора: " + ", ".join(incomplete))
    expected_runs = sum(now >= now.replace(hour=slot.hour, minute=slot.minute + GRACE_MINUTES,
                                           second=0, microsecond=0) for slot in COLLECTION_SLOTS)
    details["collection"] = {"last_run": last, "manifest_date": manifest.get("date"),
                             "sources_ok": sorted(key for key, value in sources.items()
                                                  if value.get("state") == "ok"),
                             "sources_failed": failed, "sources_incomplete": incomplete,
                             "expected_runs_by_now": expected_runs}


def check_neuro_yurist(now: datetime, warnings: list[str], details: dict) -> None:
    journal = ROOT / "ЖУРНАЛ_ПРОГОНОВ_НейроЮрист.md"
    text = journal.read_text(encoding="utf-8", errors="replace") if journal.exists() else ""
    dates = [datetime.strptime(value, "%Y-%m-%d").date()
             for value in re.findall(r"^##\s+(\d{4}-\d{2}-\d{2})", text, re.MULTILINE)]
    last_date = max(dates).isoformat() if dates else None
    details["neuro_yurist"] = {"last_journal_date": last_date}
    if last_date != now.date().isoformat():
        warnings.append("НейроЮрист не имеет подтверждённого выпуска за сегодня")


def notify_if_changed(payload: dict) -> None:
    """Опциональный webhook: адрес хранится только в переменной окружения."""
    url = os.getenv("NEWS_ALERT_WEBHOOK_URL", "").strip()
    fingerprint = hashlib.sha256(json.dumps({"critical": payload["critical"], "warnings": payload["warnings"]},
                                             ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    previous = read_json(ALERT_STATE, {})
    write_json_atomic(ALERT_STATE, {"fingerprint": fingerprint, "updated_at": payload["checked_at"]})
    if not url or previous.get("fingerprint") == fingerprint:
        return
    body = json.dumps({"text": "Office Tax News: " + "; ".join(payload["critical"] or payload["warnings"] or ["OK"])},
                      ensure_ascii=False).encode("utf-8")
    try:
        with urlopen(Request(url, data=body, headers={"Content-Type": "application/json"}), timeout=10):
            pass
    except OSError:
        # Неработающий alert endpoint не должен скрывать основной диагноз.
        pass


def main() -> int:
    now = datetime.now().astimezone()
    critical, warnings, details = [], [], {}
    check_delivery(now, critical, details)
    check_collection(now, critical, warnings, details)
    check_neuro_yurist(now, warnings, details)
    payload = {"checked_at": now.isoformat(), "healthy": not critical and not warnings,
               "critical": critical, "warnings": warnings, "details": details}
    write_json_atomic(STATUS, payload)
    notify_if_changed(payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
