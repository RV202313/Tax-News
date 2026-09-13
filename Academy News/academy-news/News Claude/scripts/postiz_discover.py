#!/usr/bin/env python3
"""Discovery не-TG интеграций Postiz и опциональная запись однозначных id."""

from __future__ import annotations

import argparse
import json
import os
import sys
import tempfile
from pathlib import Path

import requests
import yaml

from common import load_env


IDENTIFIERS = {
    "vk": {"vk"},
    "linkedin": {"linkedin", "linkedin-page"},
}


def discover(root: Path, *, write: bool = False, session=None) -> dict:
    config_path = root / "config" / "postiz.yaml"
    cfg = yaml.safe_load(config_path.read_text(encoding="utf-8")) or {}
    load_env(root / ".env.postiz")
    key = os.getenv("POSTIZ_API_KEY", "")
    if not key:
        raise RuntimeError("Нет POSTIZ_API_KEY в .env.postiz")
    base = ((cfg.get("connection") or {}).get("base_url") or "http://localhost:4007").rstrip("/")
    client = session or requests.Session()
    response = client.get(
        f"{base}/api/public/v1/integrations",
        headers={"Authorization": key}, timeout=25,
    )
    if not response.ok:
        raise RuntimeError(f"Postiz discovery вернул {response.status_code}: {response.text[:300]}")
    payload = response.json()
    if not isinstance(payload, list):
        raise RuntimeError("Postiz discovery вернул не список")
    active = [item for item in payload if isinstance(item, dict) and not item.get("disabled")]
    found = {}
    for channel, identifiers in IDENTIFIERS.items():
        matches = [item for item in active if item.get("identifier") in identifiers]
        found[channel] = [
            {"id": str(item.get("id", "")), "identifier": str(item.get("identifier", "")),
             "name": str(item.get("name", ""))}
            for item in matches if item.get("id")
        ]
    written = []
    if write:
        channel_map = cfg.setdefault("channel_map", {})
        for channel, matches in found.items():
            if len(matches) == 1:
                entry = channel_map.setdefault(channel, {})
                entry["postiz_integration_id"] = matches[0]["id"]
                entry["provider_identifier"] = matches[0]["identifier"]
                entry.setdefault("enabled", True)
                written.append(channel)
        fd, temp_name = tempfile.mkstemp(prefix=".postiz.yaml.", dir=config_path.parent)
        os.close(fd)
        temp_path = Path(temp_name)
        try:
            temp_path.write_text(
                yaml.safe_dump(cfg, allow_unicode=True, sort_keys=False), encoding="utf-8"
            )
            os.replace(temp_path, config_path)
        finally:
            temp_path.unlink(missing_ok=True)
    return {"found": found, "written": written}


def main() -> int:
    parser = argparse.ArgumentParser(description="Postiz integration discovery (без Telegram).")
    parser.add_argument("--root", default=str(Path(__file__).resolve().parents[1]))
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    try:
        result = discover(Path(args.root).resolve(), write=args.write)
    except (OSError, ValueError, RuntimeError, requests.RequestException, yaml.YAMLError) as exc:
        print(f"[postiz-discover] ошибка: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
