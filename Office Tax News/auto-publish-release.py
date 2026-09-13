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
import subprocess
import sys
import traceback
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NEWS_ROOT = ROOT / "News Claude"
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
LOG_DIR = ROOT / "runtime-logs"
STATUS_FILE = LOG_DIR / "auto-publisher-status.json"
HISTORY_FILE = LOG_DIR / "auto-publisher-history.jsonl"
LOCK_FILE = LOG_DIR / "auto-publisher.lock"


def _write_json_atomic(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, path)


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
    release = f"{now:%Y-%m-%d}_{now:%H}00_editorial"
    return release, NEWS_ROOT / "pipeline" / "approved" / f"{release}.json"


def load_release(path: Path) -> dict:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("items"), list):
        raise RuntimeError("approved JSON должен содержать object.items[]")
    return value


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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--approved", help="Путь к проверенному approved JSON")
    parser.add_argument("--scheduled", action="store_true",
                        help="Использовать пакет текущего слота YYYY-MM-DD_HH00_editorial.json")
    args = parser.parse_args()
    started = datetime.now().astimezone()
    release_name, scheduled_path = expected_release(started)
    approved = Path(args.approved).resolve() if args.approved else scheduled_path
    status = {"component": "auto_publisher", "release": release_name,
              "approved_file": str(approved), "started_at": started.isoformat(), "status": "failed"}
    try:
        if not VENV_PYTHON.is_file():
            raise RuntimeError("Не найден Python виртуальной среды проекта")
        if not approved.is_file():
            log(f"Approved-пакет {approved.name} отсутствует. Автоматическая сборка из inbox...")
            sys.path.insert(0, str(NEWS_ROOT / "scripts"))
            import auto_build_package
            auto_build_package.build_approved_package(release_name, approved, NEWS_ROOT)
        if not approved.is_file():
            raise RuntimeError("Не удалось собрать approved-пакет")
        release = load_release(approved)
        if release.get("release") != release_name and args.scheduled:
            raise RuntimeError("Имя release в пакете не соответствует текущему слоту")
        status["release"] = str(release.get("release") or release_name)
        with single_runner():
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
        status.update({"error": str(exc), "finished_at": datetime.now().astimezone().isoformat()})
        log(f"FAILED {status['release']}: {exc}")
        log(traceback.format_exc().rstrip())
        record_status(status)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
