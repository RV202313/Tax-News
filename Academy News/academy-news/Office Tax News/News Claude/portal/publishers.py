#!/usr/bin/env python3
"""Адаптеры доставки. Внешний вызов возможен только по явному действию в портале."""
from __future__ import annotations

import base64
import mimetypes
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import requests
import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from common import load_env


def _postiz_config(root: Path) -> dict[str, Any]:
    with (root / "config" / "postiz.yaml").open(encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _upload_postiz(root: Path, base_url: str, api_key: str,
                   media_paths: list[Path]) -> list[dict[str, str]]:
    """Загрузить локальные медиа в Public API Postiz."""
    uploaded = []
    for raw_path in media_paths:
        path = Path(raw_path).expanduser().resolve()
        if not path.is_file():
            raise RuntimeError(f"Медиафайл не найден: {path}")
        mime = mimetypes.guess_type(path.name)[0] or "application/octet-stream"
        with path.open("rb") as handle:
            response = requests.post(
                f"{base_url}/api/public/v1/upload",
                files={"file": (path.name, handle, mime)},
                headers={"Authorization": api_key}, timeout=45,
            )
        if not response.ok:
            raise RuntimeError(f"Postiz upload вернул {response.status_code}: {response.text[:500]}")
        data = response.json()
        if isinstance(data, list):
            data = data[0] if data else {}
        if isinstance(data, dict) and isinstance(data.get("data"), dict):
            data = data["data"]
        media_id, media_path = str(data.get("id", "")), str(data.get("path", ""))
        if not media_id or not media_path:
            raise RuntimeError("Postiz upload не вернул id/path")
        uploaded.append({"id": media_id, "path": media_path})
    return uploaded


def publish_postiz(root: Path, channel: str, content: str, mode: str = "draft",
                   schedule_at: str | None = None,
                   media_paths: list[Path] | None = None) -> dict[str, str]:
    """Создать пост в Postiz. Публикация допускается только после UI-подтверждения."""
    load_env(root / ".env.postiz")
    api_key = os.getenv("POSTIZ_API_KEY", "")
    cfg = _postiz_config(root)
    base_url = ((cfg.get("connection") or {}).get("base_url") or "http://localhost:4007").rstrip("/")
    channel_cfg = ((cfg.get("channel_map") or {}).get(channel) or {})
    integration_id = channel_cfg.get("postiz_integration_id", "")
    if not api_key:
        raise RuntimeError("Не задан POSTIZ_API_KEY в .env.postiz.")
    if channel_cfg.get("enabled") is False:
        raise RuntimeError(f"Канал {channel} отключён в Postiz-конфиге.")
    if not integration_id:
        raise RuntimeError(f"Для канала {channel} не задан postiz_integration_id.")
    if channel == "linkedin":
        mode = "draft"
    if mode not in {"draft", "schedule", "now"}:
        raise RuntimeError("Допустимые режимы Postiz: draft, schedule, now.")
    provider = channel_cfg.get("provider_identifier") or {
        "telegram_channel": "telegram", "vk": "vk", "linkedin": "linkedin"
    }.get(channel)
    if not provider:
        raise RuntimeError(f"Канал {channel} не поддерживается Postiz-адаптером.")
    at = schedule_at or datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")
    uploaded = _upload_postiz(root, base_url, api_key, media_paths or [])
    payload = {
        "type": mode,
        "date": at,
        "shortLink": False,
        "tags": [],
        "posts": [{
            "integration": {"id": integration_id},
            "value": [{"content": content, "image": uploaded}],
            "settings": {"__type": provider},
        }],
    }
    response = requests.post(
        f"{base_url}/api/public/v1/posts", json=payload,
        headers={"Authorization": api_key}, timeout=25,
    )
    if not response.ok:
        raise RuntimeError(f"Postiz вернул {response.status_code}: {response.text[:500]}")
    data = response.json()
    first = data[0] if isinstance(data, list) and data else {}
    return {"post_id": str(first.get("postId", "")), "post_url": "", "mode": mode}


def publish_wordpress(root: Path, title: str, content: str, mode: str = "draft") -> dict[str, str]:
    """Создать черновик или публикацию в WordPress через REST API."""
    load_env(root / ".env.portal")
    if os.getenv("CMS_TYPE", "").lower() != "wordpress":
        raise RuntimeError("Поддержан только CMS_TYPE=wordpress; настройте адаптер для другой CMS.")
    base = os.getenv("WORDPRESS_API_BASE", "").rstrip("/")
    user = os.getenv("WORDPRESS_USER", "")
    password = os.getenv("WORDPRESS_APP_PASSWORD", "")
    if not all((base, user, password)):
        raise RuntimeError("Для сайта задайте WORDPRESS_API_BASE, WORDPRESS_USER и WORDPRESS_APP_PASSWORD.")
    status = "publish" if mode == "now" else "draft"
    token = base64.b64encode(f"{user}:{password}".encode()).decode()
    response = requests.post(
        f"{base}/posts", json={"title": title, "content": content, "status": status},
        headers={"Authorization": f"Basic {token}"}, timeout=25,
    )
    if not response.ok:
        raise RuntimeError(f"CMS вернула {response.status_code}: {response.text[:500]}")
    data = response.json()
    return {"post_id": str(data.get("id", "")), "post_url": str(data.get("link", "")), "mode": status}
