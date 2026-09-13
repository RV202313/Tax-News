#!/usr/bin/env python3
"""Сбор комментариев и инструкций из редакционного чата Telegram с дедупликацией."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from datetime import date as date_cls, timezone
from pathlib import Path

# Добавляем папку скриптов в sys.path
sys.path.insert(0, str(Path(__file__).resolve().parent))
from session_guard import exclusive_session_lock
from common import load_env

EDITORIAL_CHAT_ID = -1004472011991


async def collect_comments(session_path: Path, env_path: Path, date_str: str) -> list[dict]:
    from telethon import TelegramClient
    
    api_id = os.getenv("TELEGRAM_API_ID", "")
    api_hash = os.getenv("TELEGRAM_API_HASH", "")
    if not api_id or not api_hash:
        raise RuntimeError("TELEGRAM_API_ID/HASH не найдены")
        
    client = TelegramClient(str(session_path), int(api_id), api_hash)
    await client.connect()
    
    comments = []
    try:
        me = await client.get_me()
        if me is None:
            raise RuntimeError("Сессия не авторизована")
        if (me.username or "").lower() != "academy_of_beps":
            raise RuntimeError("Wrong Telegram account; expected Academy_of_BEPS")
        my_id = me.id
        
        entity = await client.get_entity(EDITORIAL_CHAT_ID)
        # Получаем последние 50 сообщений
        async for msg in client.iter_messages(entity, limit=50):
            # Пропускаем сообщения от себя
            if msg.sender_id == my_id:
                continue
                
            sender = await msg.get_sender()
            sender_name = getattr(sender, "username", "") or getattr(sender, "first_name", "") or "Unknown"
            
            # Проверяем, является ли сообщение ответом
            replied_to_text = ""
            if msg.reply_to:
                try:
                    replied_msg = await client.get_messages(entity, ids=msg.reply_to.reply_to_msg_id)
                    if replied_msg:
                        replied_to_text = replied_msg.message or ""
                except Exception:
                    pass
            
            comments.append({
                "message_id": msg.id,
                "sender_id": msg.sender_id,
                "sender_name": sender_name,
                "date": msg.date.astimezone(timezone.utc).isoformat(),
                "text": msg.message or "",
                "is_reply": msg.reply_to is not None,
                "replied_to_msg_id": msg.reply_to.reply_to_msg_id if msg.reply_to else None,
                "replied_to_text": replied_to_text
            })
    finally:
        await client.disconnect()
        
    return comments


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
        
    parser = argparse.ArgumentParser(description="Сбор отзывов и инструкций из редакционного чата Telegram.")
    parser.add_argument("--date", default=date_cls.today().isoformat())
    parser.add_argument("--root", default=".")
    parser.add_argument("--session", default="")
    parser.add_argument("--env", default="")
    args = parser.parse_args()
    
    root = Path(args.root).resolve()
    
    # Пути по умолчанию для сессии и env
    default_telegram_root = root.parent / ".telegram_auth"
    session_path = Path(args.session) if args.session else default_telegram_root / "academy_news_windows.session"
    env_path = Path(args.env) if args.env else default_telegram_root / ".env"
    
    session_path = session_path.resolve()
    env_path = env_path.resolve()
    
    if not session_path.is_file():
        print(f"[comments] Файл сессии не найден: {session_path}", file=sys.stderr)
        return 1
        
    load_env(env_path)
    
    try:
        with exclusive_session_lock(session_path):
            comments = asyncio.run(collect_comments(session_path, env_path, args.date))
    except Exception as exc:
        print(f"[comments] Ошибка: {exc}", file=sys.stderr)
        return 1
        
    # Дедупликация и определение новых инструкций
    state_dir = root / "pipeline" / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    seen_file = state_dir / "seen_comments.json"
    
    seen_ids = set()
    if seen_file.exists():
        try:
            seen_ids = set(json.loads(seen_file.read_text(encoding="utf-8")))
        except Exception:
            pass
            
    new_comments = [c for c in comments if c["message_id"] not in seen_ids]
    
    # Записываем результат в raw
    out_dir = root / "pipeline" / "raw" / args.date
    out_dir.mkdir(parents=True, exist_ok=True)
    target = out_dir / "chat_instructions.json"
    target.write_text(json.dumps(comments, ensure_ascii=False, indent=2), encoding="utf-8")
    
    if new_comments:
        print(f"\n[NEW_INSTRUCTIONS_FOUND] Найдено {len(new_comments)} новых сообщений от участников:")
        for c in new_comments:
            print(f"- {c['sender_name']} (ID: {c['sender_id']}): {c['text']}")
            seen_ids.add(c["message_id"])
        
        # Обновляем список просмотренных
        seen_file.write_text(json.dumps(list(seen_ids)), encoding="utf-8")
    else:
        print("[comments] Новых комментариев не найдено.")
        
    return 0


if __name__ == "__main__":
    sys.exit(main())
