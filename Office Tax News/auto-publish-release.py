#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Надёжная доставка уже проверенного редакционного выпуска.

Этот скрипт намеренно НЕ отбирает и НЕ "одобряет" сырые новости. Подготовка
пакета остаётся задачей Antigravity/редактора. Успехом считается только десять
подтверждённых Telegram-доставок и корректный immutable run_record.
"""
from __future__ import annotations

import argparse
import json
import os
import hashlib
import subprocess
import sys
import time
import traceback
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NEWS_ROOT = ROOT / "News Claude"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_DIR = ROOT / "runtime-logs"
STATUS_FILE = LOG_DIR / "auto-publisher-status.json"
HISTORY_FILE = LOG_DIR / "auto-publisher-history.jsonl"
LOCK_FILE = LOG_DIR / "auto-publisher.lock"
# Moscow has been UTC+3 year-round since 2014. Avoid ZoneInfo here: the
# project's Windows Python can run without the optional IANA tzdata package.
MOSCOW_TZ = timezone(timedelta(hours=3), name="MSK")
MOSCOW_SLOTS = (9, 13, 17)
SLOT_GRACE_MINUTES = 15


def _write_json_atomic(path: Path, value: dict) -> None:
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


def log(message: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    entry = f"[{stamp}] {message}"
    print(entry, flush=True)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with (LOG_DIR / "auto-publisher.log").open("a", encoding="utf-8") as handle:
        handle.write(entry + "\n")


def record_status(payload: dict) -> None:
    payload["recorded_at"] = datetime.now().astimezone().isoformat()
    _write_json_atomic(STATUS_FILE, payload)
    with HISTORY_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


@contextmanager
def single_runner():
    """Не допустить двух одновременных выпусков и дублирования Telegram-постов."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handle = LOCK_FILE.open("a+b")
    try:
        if os.name == "nt":
            import msvcrt
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise RuntimeError("Другой экземпляр auto-publisher уже выполняется") from exc
        yield
    finally:
        if os.name == "nt":
            try:
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            except OSError:
                pass
        handle.close()


def expected_release(now: datetime) -> tuple[str, Path]:
    # Редакционные слоты заданы владельцем в московском времени. Компьютер
    # работает в Europe/Amsterdam, поэтому нельзя использовать его локальный
    # час при выборе имени hand-off пакета.
    moscow_now = now.astimezone(MOSCOW_TZ)
    release = f"{moscow_now:%Y-%m-%d}_{moscow_now:%H}00_editorial"
    return release, NEWS_ROOT / "pipeline" / "approved" / f"{release}.json"


def in_moscow_delivery_window(now: datetime) -> bool:
    """Permit delivery only in the promised Moscow editorial windows."""
    moscow_now = now.astimezone(MOSCOW_TZ)
    return moscow_now.hour in MOSCOW_SLOTS and moscow_now.minute <= SLOT_GRACE_MINUTES


def load_release(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise RuntimeError("approved JSON должен содержать object.items[]")
    return value


def wait_for_editorial_handoff(path: Path, release_name: str, wait_seconds: int) -> dict:
    """Принять только завершённый и стабильный пакет редактора.

    Antigravity пишет approved JSON, а планировщик лишь доставляет его. Небольшое
    ожидание снимает гонку в момент, когда дедлайн уже наступил, а файл ещё
    дописывается; автосбор из inbox здесь намеренно запрещён.
    """
    deadline = time.monotonic() + max(0, wait_seconds)
    last_signature: tuple[int, int] | None = None
    while True:
        if path.is_file():
            stat = path.stat()
            signature = (stat.st_size, stat.st_mtime_ns)
            if signature == last_signature:
                release = load_release(path)
                if release.get("release") != release_name:
                    raise RuntimeError("Имя release в hand-off пакете не соответствует текущему слоту")
                return release
            last_signature = signature
        if time.monotonic() >= deadline:
            raise RuntimeError(
                f"Нет завершённого editorial hand-off {path.name}. "
                "Antigravity должен подготовить валидный пакет; автосбор отключён, чтобы не было конфликта."
            )
        time.sleep(3)


def verify_delivery(release: dict) -> str:
    """Проверить не stdout процесса, а durable следы десяти доставок."""
    date = str(release["date"])
    release_name = str(release["release"])
    expected_slugs = {str(item.get("slug") or "") for item in release["items"]}
    if len(expected_slugs) != 10 or "" in expected_slugs:
        raise RuntimeError("В approved JSON нет десяти уникальных slug")
    sidecar = NEWS_ROOT / "pipeline" / "published" / f"{date}.jsonl"
    if not sidecar.is_file():
        raise RuntimeError("Не создан журнал Telegram-доставки")
    delivered = set()
    for line in sidecar.read_text(encoding="utf-8").splitlines():
        try:
            row = json.loads(line)
        except json.JSONDecodeError:
            continue
        if (row.get("release") == release_name and row.get("delivery") == "telegram_editorial"
                and row.get("post_id")):
            delivered.add(str(row.get("slug") or ""))
    if not expected_slugs.issubset(delivered):
        raise RuntimeError(
            f"Неполная Telegram-доставка: доставлено {len(delivered & expected_slugs)}/10; "
            f"отсутствуют {sorted(expected_slugs - delivered)}"
        )
    candidates = sorted((NEWS_ROOT / "pipeline" / "run_records" / date).glob("*/run_record.json"),
                        key=lambda item: item.stat().st_mtime, reverse=True)
    for record in candidates:
        value = json.loads(record.read_text(encoding="utf-8"))
        coverage = value.get("delivery_coverage") or {}
        if (value.get("release") == release_name and value.get("items_count") == 10
                and coverage.get("delivered_slugs") == 10 and not coverage.get("missing_slugs")):
            return str(record)
    raise RuntimeError("Не найден подтверждённый run_record с доставкой 10/10")


def delivered_record_for_release(release: dict) -> tuple[Path, str] | None:
    """Вернуть immutable receipt уже доставленного редакционного слота."""
    date = str(release["date"])
    release_name = str(release["release"])
    for record in sorted((NEWS_ROOT / "pipeline" / "run_records" / date).glob("*/run_record.json"),
                         key=lambda item: item.stat().st_mtime, reverse=True):
        value = json.loads(record.read_text(encoding="utf-8"))
        coverage = value.get("delivery_coverage") or {}
        if (value.get("release") == release_name and value.get("items_count") == 10
                and coverage.get("delivered_slugs") == 10 and not coverage.get("missing_slugs")):
            artifact = value.get("artifacts", {}).get("approved", {})
            return record, str(artifact.get("sha256") or "")
    return None


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approved", help="Путь к проверенному approved JSON")
    parser.add_argument("--scheduled", action="store_true",
                        help="Использовать пакет текущего слота YYYY-MM-DD_HH00_editorial.json")
    parser.add_argument("--handoff-wait-seconds", type=int, default=600,
                        help="Сколько ждать стабильный hand-off редактора (0 — не ждать)")
    args = parser.parse_args()
    started = datetime.now().astimezone()
    release_name, scheduled_path = expected_release(started)
    approved = Path(args.approved).resolve() if args.approved else scheduled_path
    status = {"component": "auto_publisher", "release": release_name,
              "approved_file": str(approved), "started_at": started.isoformat(), "status": "failed"}
    try:
        if not VENV_PYTHON.is_file():
            raise RuntimeError("Не найден Python виртуальной среды проекта")
        if not in_moscow_delivery_window(started):
            raise RuntimeError(
                "Доставка разрешена только в окне 09:00/13:00/17:00 Europe/Moscow; "
                "ранняя или произвольная ручная отправка заблокирована"
            )
        wait_seconds = args.handoff_wait_seconds if args.scheduled else 0
        # Persist the state before waiting.  Previously a missing hand-off was
        # invisible for up to ten minutes, which made a Scheduler incident look
        # like a silent skipped release.  This is only local observability: it
        # never changes a package and never contacts Telegram.
        status.update({"status": "waiting_for_handoff",
                       "handoff_wait_seconds": wait_seconds})
        record_status(status)
        log(f"Ожидаю стабильный editorial hand-off: {approved.name}")
        release = wait_for_editorial_handoff(approved, release_name, wait_seconds)
        status["release"] = str(release.get("release") or release_name)
        with single_runner():
            # A retry, StartWhenAvailable, or DST companion trigger must never
            # create a second set of posts for a release that already has its
            # immutable 10/10 receipt.
            delivered_record = delivered_record_for_release(release)
            if delivered_record is not None:
                record, delivered_hash = delivered_record
                handoff_hash = hashlib.sha256(approved.read_bytes()).hexdigest()
                if delivered_hash and delivered_hash != handoff_hash:
                    raise RuntimeError(
                        "Этот редакционный слот уже доставлен, но hand-off пакет изменён; "
                        "повторная отправка заблокирована"
                    )
                run_record = verify_delivery(release)
                status.update({"status": "success", "run_record": run_record,
                               "delivered_count": 10, "already_delivered": True,
                               "finished_at": datetime.now().astimezone().isoformat()})
                log(f"SUCCESS {status['release']}: existing Telegram delivery 10/10 confirmed")
                record_status(status)
                return 0
            preflight = subprocess.run(
                [str(VENV_PYTHON), "-X", "utf8", str(NEWS_ROOT / "scripts" / "publish_batch.py"),
                 str(approved), "--root", str(NEWS_ROOT)],
                cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8"
            )
            if preflight.returncode != 0:
                raise RuntimeError("Preflight не пройден: " + (preflight.stderr or preflight.stdout).strip()[-1800:])
            delivered = subprocess.run(
                [str(VENV_PYTHON), "-X", "utf8", str(NEWS_ROOT / "scripts" / "publish_batch.py"),
                 str(approved), "--root", str(NEWS_ROOT), "--execute-editorial"],
                cwd=str(ROOT), capture_output=True, text=True, encoding="utf-8"
            )
            if delivered.returncode != 0:
                raise RuntimeError("Telegram-доставка завершилась ошибкой: " +
                                   (delivered.stderr or delivered.stdout).strip()[-1800:])
            run_record = verify_delivery(release)
        status.update({"status": "success", "run_record": run_record,
                       "delivered_count": 10, "finished_at": datetime.now().astimezone().isoformat()})
        log(f"SUCCESS {status['release']}: Telegram delivery 10/10 confirmed")
        record_status(status)
        return 0
    except Exception as exc:
        status.update({"status": "failed", "error": str(exc), "finished_at": datetime.now().astimezone().isoformat()})
        log(f"FAILED {status['release']}: {exc}")
        log(traceback.format_exc().rstrip())
        record_status(status)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
