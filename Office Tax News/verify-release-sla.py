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
import subprocess
import sys
from datetime import datetime, time, timedelta
from pathlib import Path
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parent
LOG_DIR = ROOT / "runtime-logs"
NEWS_ROOT = ROOT / "News Claude"
STATUS = LOG_DIR / "health-status.json"
ALERT_STATE = LOG_DIR / "health-alert-state.json"
# Moscow is fixed at UTC+3; do not depend on an optional IANA tzdata package
# that is absent from the project's Windows Python distribution.
MOSCOW_TZ = timezone(timedelta(hours=3), name="MSK")
# Editorial and collection commitments are Moscow-time commitments, regardless
# of the Windows machine's local European timezone.
SLOTS = (time(9), time(13), time(17))
COLLECTION_SLOTS = (time(8), time(12), time(16))
GRACE_MINUTES = 15


def read_json(path: Path, fallback):
    try:
        # PowerShell 5.1 writes UTF-8 with BOM for Set-Content -Encoding UTF8.
        return json.loads(path.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError, json.JSONDecodeError):
        return fallback


def write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    content = json.dumps(value, ensure_ascii=False, indent=2)
    tmp.write_text(content, encoding="utf-8")
    for attempt in range(5):
        try:
            os.replace(tmp, path)
            return
        except (OSError, PermissionError):
            if attempt == 4:
                try:
                    path.write_text(content, encoding="utf-8")
                    tmp.unlink(missing_ok=True)
                    return
                except Exception:
                    pass
                raise
            import time
            time.sleep(0.15)


def history_records() -> list[dict]:
    """Return every durable publisher status; timing incidents must not be masked."""
    records = []
    path = LOG_DIR / "auto-publisher-history.jsonl"
    if not path.exists():
        return records
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            item = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(item.get("release") or ""):
            records.append(item)
    return records


def history_by_release() -> dict[str, dict]:
    records = {}
    for item in history_records():
        release = str(item["release"])
        if release not in records or item.get("status") == "success":
            records[release] = item
    return records


def recorded_delivery_ok(release: str, date: str) -> tuple[bool, str]:
    """Check the immutable receipt and its Moscow-time delivery window.

    A run_record alone can be created after the promised slot.  For historical
    releases without publisher history, accept delivery only when all ten
    Telegram receipts were recorded inside that release's own Moscow window.
    """
    match = re.fullmatch(r"\d{4}-\d{2}-\d{2}_(\d{2})00_editorial", release)
    if not match:
        return False, "некорректное имя release"
    slot_hour = int(match.group(1))
    sidecar = NEWS_ROOT / "pipeline" / "published" / f"{date}.jsonl"
    delivered = []
    if sidecar.is_file():
        for line in sidecar.read_text(encoding="utf-8", errors="replace").splitlines():
            row = read_json_line(line)
            if (row.get("release") == release and row.get("delivery") == "telegram_editorial"
                    and row.get("post_id")):
                delivered.append(row)
    if len({str(row.get("slug") or "") for row in delivered if row.get("slug")}) != 10:
        return False, "нет десяти Telegram-receipt"
    for row in delivered:
        stamp = str(row.get("recorded_at") or "")
        try:
            delivered_at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(MOSCOW_TZ)
        except ValueError:
            return False, "в receipt отсутствует проверяемое время"
        if delivered_at.hour != slot_hour or delivered_at.minute > GRACE_MINUTES:
            return False, f"receipt записан вне окна: {delivered_at:%H:%M} МСК"
    folder = NEWS_ROOT / "pipeline" / "run_records" / date
    for path in folder.glob("*/run_record.json"):
        value = read_json(path, {})
        coverage = value.get("delivery_coverage") or {}
        if (value.get("release") == release and value.get("items_count") == 10
                and coverage.get("delivered_slugs") == 10 and not coverage.get("missing_slugs")):
            return True, ""
    return False, "нет подтверждённого run_record 10/10"


def read_json_line(value: str) -> dict:
    try:
        parsed = json.loads(value)
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def check_delivery(now: datetime, critical: list[str], details: dict) -> None:
    history = history_by_release()
    records = []
    for slot in SLOTS:
        due = now.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
        if now < due.replace(minute=due.minute + GRACE_MINUTES):
            continue
        release = f"{now:%Y-%m-%d}_{slot.hour:02d}00_editorial"
        item = history.get(release)
        # Publisher history is diagnostic only.  A success flag must not
        # replace the ten timestamped sidecar receipts and run record.
        ok, receipt_error = recorded_delivery_ok(release, now.strftime("%Y-%m-%d"))
        records.append({"release": release, "due_at": due.isoformat(), "ok": ok,
                        "status": item.get("status") if item else "missing",
                        "error": item.get("error", "") if item else "",
                        "receipt_error": receipt_error})
        if not ok:
            reason = receipt_error or (item.get("error") if item else "")
            suffix = f": {reason}" if reason else ""
            critical.append(f"Нет подтверждённой доставки 10/10 для {release}{suffix}")
    details["deliveries"] = records


def check_delivery_timing(now: datetime, critical: list[str], details: dict) -> None:
    """Detect a delivery that happened before/after its named Moscow slot."""
    observed = []
    date_prefix = f"{now:%Y-%m-%d}_"
    for item in history_records():
        release = str(item["release"])
        if not release.startswith(date_prefix) or item.get("status") != "success":
            continue
        match = re.fullmatch(r"\d{4}-\d{2}-\d{2}_(\d{2})00_editorial", release)
        if not match or int(match.group(1)) not in {slot.hour for slot in SLOTS}:
            continue
        stamp = str(item.get("finished_at") or item.get("recorded_at") or "")
        try:
            delivered_at = datetime.fromisoformat(stamp.replace("Z", "+00:00")).astimezone(MOSCOW_TZ)
        except ValueError:
            critical.append(f"Невозможно проверить время доставки для {release}")
            continue
        slot_hour = int(match.group(1))
        in_window = delivered_at.hour == slot_hour and delivered_at.minute <= GRACE_MINUTES
        observed.append({"release": release, "delivered_at": delivered_at.isoformat(), "in_window": in_window})
        if not in_window:
            critical.append(
                f"Доставка {release} произошла вне окна {slot_hour:02d}:00–"
                f"{slot_hour:02d}:{GRACE_MINUTES:02d} МСК ({delivered_at:%H:%M} МСК)"
            )
    details["delivery_timing"] = observed


def check_handoff_readiness(now: datetime, critical: list[str], warnings: list[str], details: dict) -> None:
    """Detect a missing editorial package before its delivery slot is lost.

    The publisher may only deliver an already verified package.  Checking this
    thirty minutes before the slot gives the watchdog and the owner a real
    recovery window; treating it as a post-deadline-only problem is too late.
    """
    observed = []
    today = now.strftime("%Y-%m-%d")
    approved = NEWS_ROOT / "pipeline" / "approved"
    for slot in SLOTS:
        due = now.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
        minutes_to_due = (due - now).total_seconds() / 60
        if not 0 < minutes_to_due <= 30:
            continue
        release = f"{today}_{slot.hour:02d}00_editorial"
        handoff = approved / f"{release}.json"
        package = read_json(handoff, {}) if handoff.exists() else {}
        items = package.get("items") if isinstance(package, dict) else None
        valid_shape = isinstance(items, list) and len(items) == 10
        status = {"release": release, "due_at": due.isoformat(),
                  "minutes_to_due": round(minutes_to_due, 1),
                  "handoff": str(handoff), "valid_shape": valid_shape}
        observed.append(status)
        if not handoff.exists():
            critical.append(
                f"Нет hand-off для {release} за {minutes_to_due:.0f} мин. до слота; "
                "Antigravity должен немедленно завершить подготовку"
            )
        elif not valid_shape:
            critical.append(
                f"Hand-off {release} существует, но не содержит ровно 10 материалов "
                f"за {minutes_to_due:.0f} мин. до слота"
            )
        else:
            command = [
                str(ROOT / ".venv" / "Scripts" / "python.exe"), "-X", "utf8",
                str(NEWS_ROOT / "scripts" / "publish_batch.py"), str(handoff),
                "--root", str(NEWS_ROOT), "--verify-sources-live",
            ]
            try:
                checked = subprocess.run(command, cwd=str(ROOT), capture_output=True,
                                         text=True, encoding="utf-8", timeout=240)
                status["source_verification_exit"] = checked.returncode
                if checked.returncode != 0:
                    detail = (checked.stderr or checked.stdout).strip().replace("\n", " ")[-900:]
                    status["source_verification_error"] = detail
                    critical.append(
                        f"Hand-off {release} не прошёл live-проверку источников за "
                        f"{minutes_to_due:.0f} мин. до слота: {detail}"
                    )
                else:
                    warnings.append(
                        f"Hand-off {release} и первоисточники проверены за "
                        f"{minutes_to_due:.0f} мин. до слота"
                    )
            except (OSError, subprocess.TimeoutExpired) as exc:
                status["source_verification_error"] = str(exc)
                critical.append(
                    f"Не удалось live-проверить источники для {release} за "
                    f"{minutes_to_due:.0f} мин. до слота: {exc}"
                )
    details["handoff_preflight"] = observed


def check_collection(now: datetime, critical: list[str], warnings: list[str], details: dict) -> None:
    last = read_json(LOG_DIR / "last-run.json", {})
    if last.get("exit_code") != 0:
        critical.append("Последний запуск сборщика отсутствует или завершился ошибкой")
    due_slots = [now.replace(hour=hour, minute=12, second=0, microsecond=0)
                 for hour in (8, 12, 16)
                 if now >= now.replace(hour=hour, minute=0, second=0, microsecond=0)
                 + timedelta(minutes=12)]
    finished_at = None
    if last.get("finished"):
        try:
            finished_at = datetime.fromisoformat(last["finished"])
            if finished_at.tzinfo is None:
                finished_at = finished_at.replace(tzinfo=now.tzinfo)
            finished_at = finished_at.astimezone(now.tzinfo)
        except (TypeError, ValueError):
            pass
    if due_slots and (finished_at is None or finished_at < due_slots[-1]):
        critical.append("Сбор новостей пропущен по расписанию или давно не завершался")
    date = now.strftime("%Y-%m-%d")
    manifest = read_json(NEWS_ROOT / "pipeline" / "raw" / date / "collection_manifest.json", {})
    sources = manifest.get("sources") or {}
    expected_runs = sum(now >= now.replace(hour=slot.hour, minute=slot.minute + GRACE_MINUTES,
                                           second=0, microsecond=0) for slot in COLLECTION_SLOTS)
    last_finished = None
    try:
        last_finished = datetime.fromisoformat(
            str(last.get("finished") or "").replace("Z", "+00:00")
        ).astimezone(MOSCOW_TZ)
    except ValueError:
        pass
    # Before the first promised collection window there is intentionally no
    # current-day manifest. Do not wake the owner overnight with a false SLA
    # breach; after the first window absence is a real incident.
    if expected_runs:
        if last.get("exit_code") != 0 or last_finished is None or last_finished.date() != now.date():
            critical.append("Последний запуск сборщика отсутствует или завершился ошибкой")
        if not sources:
            critical.append("Нет манифеста сбора за сегодня")
        latest_due = max(
            now.replace(hour=slot.hour, minute=slot.minute, second=0, microsecond=0)
            for slot in COLLECTION_SLOTS
            if now >= now.replace(hour=slot.hour, minute=slot.minute + GRACE_MINUTES,
                                  second=0, microsecond=0)
        )
        if last_finished is None or last_finished < latest_due:
            critical.append(
                f"Нет завершённого сбора после слота {latest_due:%H:%M} МСК"
            )
    failed = sorted(key for key, value in sources.items()
                    if value.get("state") in {"failed", "missing"})
    incomplete = sorted(key for key, value in sources.items()
                        if value.get("state") in {"manual", "delegated"})
    if failed:
        warnings.append("Сбой источников: " + ", ".join(failed))
    if incomplete:
        warnings.append("Необязательные источники недоступны: " + ", ".join(incomplete))
    details["collection"] = {"last_run": last, "manifest_date": manifest.get("date"),
                             "sources_ok": sorted(key for key, value in sources.items()
                                                  if value.get("state") == "ok"),
                             "sources_failed": failed, "sources_incomplete": incomplete,
                             "expected_runs_by_now": expected_runs,
                             "latest_required_run_after": due_slots[-1].isoformat() if due_slots else None}


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
    now = datetime.now().astimezone(MOSCOW_TZ)
    critical, warnings, details = [], [], {}
    check_delivery(now, critical, details)
    check_delivery_timing(now, critical, details)
    check_handoff_readiness(now, critical, warnings, details)
    check_collection(now, critical, warnings, details)
    payload = {"checked_at": now.isoformat(), "healthy": not critical and not warnings,
               "critical": critical, "warnings": warnings, "details": details}
    write_json_atomic(STATUS, payload)
    notify_if_changed(payload)
    print(json.dumps(payload, ensure_ascii=False))
    return 1 if critical else 0


if __name__ == "__main__":
    raise SystemExit(main())
