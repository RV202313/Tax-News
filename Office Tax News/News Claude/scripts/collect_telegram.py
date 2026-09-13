#!/usr/bin/env python3
"""Одноразовый сбор Telegram-лидов; это НЕ listener и не фоновый процесс."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import subprocess
import sys
from datetime import date as date_cls, datetime, time, timedelta, timezone
from pathlib import Path

import yaml

from session_guard import exclusive_session_lock

URL_RE = re.compile(r"https?://[^\s<>()\[\]{}]+", re.IGNORECASE)
ECLI_RE = re.compile(r"\bECLI:[A-Z]{2}:[A-Z0-9.]+:\d{4}:[A-Z0-9.]+\b", re.IGNORECASE)
CASE_RE = re.compile(r"\b[АA]\d{1,3}-\d+/\d{4}\b", re.IGNORECASE)


def load_env(path: Path) -> None:
    if not path.exists():
        return
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def load_channels(config_path: Path) -> list[str]:
    data = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    return list(dict.fromkeys(
        str(item["chat"]).strip()
        for item in data.get("monitored_chats", [])
        if item.get("purpose") == "tax_channels_digest" and item.get("chat")
    ))


def ensure_session_idle(session_path: Path) -> None:
    """Не открывать Telethon-session, если её уже держит другой процесс."""
    import sys
    if sys.platform == "win32":
        return
    lsof = shutil.which("lsof")
    if not lsof:
        raise RuntimeError("lsof не найден; безопасно проверить владельца Telethon-session нельзя")
    result = subprocess.run(
        [lsof, "-t", "--", str(session_path)],
        text=True,
        capture_output=True,
        check=False,
    )
    other_pids = {
        value for value in result.stdout.split()
        if value.isdigit() and int(value) != os.getpid()
    }
    if other_pids:
        raise RuntimeError("Telethon-session уже используется; одноразовый сбор отменён")


def load_keywords(root: Path) -> list[str]:
    data = yaml.safe_load((root / "config" / "topics.yaml").read_text(encoding="utf-8")) or {}
    values = []
    for topic in data.get("topics", []):
        for key in ("keywords_ru", "keywords_nl", "keywords_en", "keywords"):
            values.extend(str(value).casefold() for value in topic.get(key, []) or [])
    return sorted({value for value in values if value}, key=len, reverse=True)


def is_relevant(text: str, keywords: list[str]) -> bool:
    hay = text.casefold()
    return any(keyword in hay for keyword in keywords)


def reaction_count(message) -> int:
    return sum(int(getattr(result, "count", 0) or 0)
               for result in getattr(getattr(message, "reactions", None), "results", []) or [])


def extract_entity_urls(message) -> list[str]:
    urls = list(URL_RE.findall(message.message or ""))
    for entity in getattr(message, "entities", []) or []:
        value = getattr(entity, "url", None)
        if value:
            urls.append(value)
    web_url = getattr(getattr(message, "web_preview", None), "url", None)
    if web_url:
        urls.append(web_url)
    return list(dict.fromkeys(url.rstrip(".,);]") for url in urls if url))


def item_from_message(channel: str, message) -> dict:
    text = re.sub(r"\s+", " ", message.message or "").strip()
    title = text[:177] + "…" if len(text) > 180 else text
    username = channel.lstrip("@")
    permalink = f"https://t.me/{username}/{message.id}"
    urls = [url for url in extract_entity_urls(message) if "t.me/" not in url]
    reactions = reaction_count(message)
    views = int(getattr(message, "views", 0) or 0)
    forwards = int(getattr(message, "forwards", 0) or 0)
    act_match = ECLI_RE.search(text) or CASE_RE.search(text)
    return {
        "url": urls[0] if urls else permalink,
        "telegram_url": permalink,
        "ecli": ECLI_RE.search(text).group(0) if ECLI_RE.search(text) else "",
        "act": act_match.group(0) if act_match else "",
        "title": title,
        "summary": text[:4000],
        "published_at": message.date.astimezone(timezone.utc).date().isoformat(),
        "item_type": "telegram_lead",
        "lead": True,
        "channel": channel,
        "message_id": message.id,
        "views": views,
        "reactions": reactions,
        "forwards": forwards,
        "engagement": reactions + forwards + round(views / 1000, 3),
        "source_links": urls,
    }


def write_items(root: Path, run_date: str, items: list[dict], **metadata) -> Path:
    out_dir = root / "pipeline" / "raw" / run_date
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "telegram_leads_1.txt"
    target.write_text(
        json.dumps({"date": run_date, "items": items, **metadata}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


async def collect_live(args) -> tuple[list[dict], dict]:
    # Импорт только после проверок путей: fixture-тест не требует Telethon.
    from telethon import TelegramClient

    root = Path(args.root).resolve()
    session_path = Path(args.session).expanduser().resolve()
    if not session_path.is_file():
        raise RuntimeError("существующая session.session не найдена; новая не создаётся")
    with exclusive_session_lock(session_path):
        ensure_session_idle(session_path)
        load_env(Path(args.env).expanduser().resolve())
        api_id = os.getenv("TELEGRAM_API_ID", "")
        api_hash = os.getenv("TELEGRAM_API_HASH", "")
        if not api_id or not api_hash:
            raise RuntimeError("TELEGRAM_API_ID/HASH не найдены")
        channels = load_channels(Path(args.config).expanduser().resolve())
        keywords = load_keywords(root)
        run_day = date_cls.fromisoformat(args.date)
        end = datetime.combine(run_day + timedelta(days=1), time.min, tzinfo=timezone.utc)
        start = end - timedelta(days=args.days)
        client = TelegramClient(str(session_path), int(api_id), api_hash)
        items = []
        coverage = {}
        await client.connect()
        try:
            # Первое Telegram-действие — get_me(). Ни диалоги, ни каналы
            # не читаются, пока не подтверждён служебный аккаунт Академии.
            me = await client.get_me()
            if me is None:
                raise RuntimeError("сессия не авторизована; повторная авторизация запрещена")
            if (getattr(me, "username", "") or "").casefold() != "academy_of_beps":
                raise RuntimeError("неверный Telegram-аккаунт; сбор остановлен")
            for channel in channels:
                seen = accepted = 0
                try:
                    entity = await client.get_entity(channel)
                    async for message in client.iter_messages(
                        entity, limit=args.limit_per_channel, offset_date=end
                    ):
                        if not message.date:
                            continue
                        msg_date = message.date.astimezone(timezone.utc)
                        if msg_date < start:
                            break
                        text = (message.message or "").strip()
                        if len(text) < 15:
                            continue
                        seen += 1
                        if not is_relevant(text, keywords):
                            continue
                        items.append(item_from_message(channel, message))
                        accepted += 1
                    coverage[channel] = {"state": "ok", "seen": seen, "accepted": accepted}
                except Exception as exc:  # один канал не валит остальные
                    coverage[channel] = {"state": "failed", "error": f"{type(exc).__name__}: {exc}"}
        finally:
            await client.disconnect()
    # Одна и та же внешняя ссылка могла появиться в нескольких каналах.
    unique = {}
    for item in sorted(items, key=lambda value: value.get("engagement", 0), reverse=True):
        unique.setdefault(item["url"], item)
    return list(unique.values()), coverage


def main() -> int:
    parser = argparse.ArgumentParser(description="Одноразовый сбор Telegram-лидов.")
    parser.add_argument("--date", default=date_cls.today().isoformat())
    parser.add_argument("--root", default=".")
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--limit-per-channel", type=int, default=250)
    parser.add_argument("--config", required=True)
    parser.add_argument("--session", required=True)
    parser.add_argument("--env", required=True)
    parser.add_argument("--fixture", default="")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        if args.fixture:
            payload = json.loads(Path(args.fixture).read_text(encoding="utf-8"))
            items, coverage = payload.get("items", []), {"fixture": {"state": "ok"}}
        else:
            items, coverage = asyncio.run(collect_live(args))
        target = write_items(root, args.date, items, coverage=coverage)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"[telegram] ошибка: {exc}", file=sys.stderr)
        return 1
    print(f"[telegram] {len(items)} лидов → {target}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
