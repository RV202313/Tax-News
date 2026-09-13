#!/usr/bin/env python3
"""Плановый дневной прогон: сбор → parse/select/digest → Telegram-уведомление."""
from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from datetime import date as date_cls
from pathlib import Path

import requests

from common import load_env


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(); ap.add_argument("--date", default=date_cls.today().isoformat()); ap.add_argument("--root", default=".")
    args = ap.parse_args(); root = Path(args.root).resolve(); py = sys.executable
    collect_cmd = [py, "scripts/collect_sources.py", "--date", args.date, "--root", str(root)]
    commands = [
        [py, "scripts/collect_comments.py", "--date", args.date, "--root", str(root)],
        [py, "scripts/parse_feeds.py", "--date", args.date, "--root", str(root)],
        [py, "scripts/select_news.py", "--date", args.date, "--top", "15", "--root", str(root)],
    ]
    result = subprocess.run(collect_cmd, cwd=root, text=True)
    if result.returncode:
        return result.returncode
    for cmd in commands:
        result = subprocess.run(cmd, cwd=root, text=True)
        if result.returncode:
            return result.returncode
    # Записываем в runs фактическое покрытие ДО генерации дайджеста, чтобы оно
    # было видно и в markdown, и в веб-портале.
    manifest_path = root / "pipeline" / "raw" / args.date / "collection_manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else {"sources": {}}
    source_states = manifest.get("sources", {})
    ok = [sid for sid, rec in source_states.items() if rec.get("state") == "ok"]
    failed = [f"{sid}:{rec.get('state', 'unknown')}" for sid, rec in source_states.items()
              if rec.get("state") in {"failed", "missing"}]
    incomplete = [f"{sid}:{rec.get('state')}" for sid, rec in source_states.items()
                  if rec.get("state") in {"manual", "delegated"}]
    sys.path.insert(0, str(root / "scripts"))
    import newsdb
    conn = newsdb.connect(str(root))
    try:
        newsdb.upsert_run(conn, args.date, sources_ok=",".join(ok),
                          sources_failed=",".join(failed + incomplete))
    finally:
        newsdb.close(conn)
    result = subprocess.run([py, "scripts/make_digest.py", "--date", args.date, "--root", str(root)], cwd=root, text=True)
    if result.returncode:
        return result.returncode
    load_env(root / ".env.portal")
    token, chat = os.getenv("TELEGRAM_BOT_TOKEN", ""), os.getenv("TELEGRAM_DIGEST_CHAT_ID", "")
    if token and chat:
        digest = (root / "pipeline" / "digest" / f"{args.date}_digest.md").read_text(encoding="utf-8")
        warning = ("\n\n⚠ Сбои автосбора: " + ", ".join(sorted(failed)) if failed else "")
        coverage = ("\n\nℹ Ручной добор: " + ", ".join(sorted(incomplete))
                    if incomplete else "")
        text = f"Дайджест готов: {args.date}\n\n{digest[:3500]}{warning}{coverage}\n\nПортал: http://127.0.0.1:8765"
        response = requests.post(f"https://api.telegram.org/bot{token}/sendMessage", json={"chat_id": chat, "text": text}, timeout=20)
        response.raise_for_status()
    else:
        print("[daily] Telegram не настроен: дайджест доступен в портале.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
