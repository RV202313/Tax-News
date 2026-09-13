#!/usr/bin/env python3
"""Одноразовая интерактивная авторизация отдельной Telethon-session."""

from __future__ import annotations

import asyncio
import getpass
import os
import shutil
import sqlite3
import stat
import subprocess
import sys
from pathlib import Path
from urllib.parse import quote


PROJECT_ROOT = Path(__file__).resolve().parent
TELEGRAM_ROOT = PROJECT_ROOT / ".telegram_auth"
OLD_SESSION = TELEGRAM_ROOT / "session.session"
ENV_FILE = TELEGRAM_ROOT / ".env"
TARGET_DIR = PROJECT_ROOT / ".telegram_auth"
TARGET_SESSION = TARGET_DIR / "academy_news_windows.session"
EXPECTED_USERNAME = "academy_of_beps"

sys.path.insert(0, str(PROJECT_ROOT / "News Claude/scripts"))
from session_guard import exclusive_session_lock, require_private_session  # noqa: E402


def load_env(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip().strip("\"").strip("'")
    return values


def phone_for_expected_account() -> str:
    uri = OLD_SESSION.resolve().as_uri() + "?mode=ro"
    with sqlite3.connect(uri, uri=True) as connection:
        row = connection.execute(
            "SELECT phone FROM entities "
            "WHERE lower(username) = ? AND phone IS NOT NULL AND phone <> '' "
            "LIMIT 1",
            (EXPECTED_USERNAME,),
        ).fetchone()
    if not row:
        raise RuntimeError("Не удалось локально определить номер аккаунта Academy_of_BEPS")
    return str(row[0])


def prepare_private_session() -> Path:
    os.umask(0o077)
    TARGET_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
    if sys.platform != "win32":
        TARGET_DIR.chmod(0o700)
    if not TARGET_SESSION.exists():
        descriptor = os.open(TARGET_SESSION, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(descriptor)
    if sys.platform != "win32":
        TARGET_SESSION.chmod(0o600)
    return require_private_session(TARGET_SESSION)


def require_clean_lsof(path: Path) -> None:
    if sys.platform == "win32":
        return  # exclusive_session_lock uses msvcrt on Windows.
    lsof = shutil.which("lsof")
    if not lsof:
        raise RuntimeError("lsof не найден; открытие session запрещено")
    check = subprocess.run(
        [lsof, "-t", "--", str(path)],
        check=False,
        capture_output=True,
        text=True,
    )
    if check.returncode == 0 and check.stdout.strip():
        raise RuntimeError("Новая Telethon-session уже занята другим процессом")
    if check.returncode not in (0, 1):
        raise RuntimeError("Не удалось проверить session через lsof")


async def authorize() -> None:
    from telethon import TelegramClient
    from telethon.errors import SessionPasswordNeededError

    env = load_env(ENV_FILE)
    api_id = env.get("TELEGRAM_API_ID", "")
    api_hash = env.get("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        raise RuntimeError("TELEGRAM_API_ID/HASH не найдены")

    session_path = prepare_private_session()
    require_clean_lsof(session_path)
    phone = phone_for_expected_account()

    with exclusive_session_lock(session_path):
        lock_path = session_path.with_name(session_path.name + ".codex.lock")
        if lock_path.exists():
            lock_path.chmod(0o600)
        client = TelegramClient(str(session_path), int(api_id), api_hash)
        try:
            await client.connect()
            if not await client.is_user_authorized():
                sent = await client.send_code_request(phone)
                code = input("Код из Telegram: ").strip()
                try:
                    await client.sign_in(phone=phone, code=code, phone_code_hash=sent.phone_code_hash)
                except SessionPasswordNeededError:
                    password = getpass.getpass("Пароль 2FA: ")
                    await client.sign_in(password=password)

            me = await client.get_me()
            username = (me.username or "").lower()
            if username != EXPECTED_USERNAME:
                raise RuntimeError(
                    f"Авторизован неверный аккаунт @{username or '[без username]'}; "
                    "session не использовать"
                )
        finally:
            await client.disconnect()
            if sys.platform != "win32":
                session_path.chmod(0o600)

    mode = stat.S_IMODE(session_path.stat().st_mode)
    if sys.platform != "win32" and mode != 0o600:
        raise RuntimeError(f"Итоговые права session: {mode:04o}, ожидалось 0600")
    print(f"Готово: @{EXPECTED_USERNAME}; session={session_path}")


if __name__ == "__main__":
    try:
        asyncio.run(authorize())
    except KeyboardInterrupt:
        print("\nАвторизация прервана; публикаций и фоновых процессов не запускалось.")
        raise SystemExit(130)
    except Exception as exc:
        print(f"Ошибка авторизации: {exc}", file=sys.stderr)
        raise SystemExit(1)
