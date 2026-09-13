#!/usr/bin/env python3
"""Локальный портал управления новостным конвейером (stdlib HTTP + JSON API)."""
from __future__ import annotations

import argparse
import json
import mimetypes
import os
import re
import sys
from datetime import datetime, timezone
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import newsdb  # noqa: E402
from publishers import publish_postiz, publish_wordpress, load_env  # noqa: E402

STATIC = Path(__file__).with_name("static")
CHANNELS = {"telegram_channel", "vk", "linkedin", "site"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def write_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)


def action_path(date: str) -> Path:
    return ROOT / "pipeline" / "approved" / f"{date}_actions.json"


def delivery_path(date: str) -> Path:
    return ROOT / "pipeline" / "published" / f"{date}_delivery.jsonl"


def shortlist(date: str) -> dict:
    return read_json(ROOT / "pipeline" / "shortlist" / f"{date}_shortlist.json", {"date": date, "items": []})


def source_coverage(date: str) -> list[dict]:
    """Статус каждого настроенного источника по факту его raw-файла/манифеста."""
    import yaml
    sources = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8")) or {}
    raw_dir = ROOT / "pipeline" / "raw" / date
    manifest = read_json(raw_dir / "collection_manifest.json", {"sources": {}}).get("sources", {})
    out = []
    for src in sources.get("sources", []):
        sid = src["id"]
        files = sorted(raw_dir.glob(f"{sid}_*.txt")) if raw_dir.exists() else []
        reported = manifest.get(sid, {})
        state = reported.get("state") or ("ok" if files else "missing")
        out.append({
            "id": sid, "name": src.get("name", sid), "method": src.get("method", ""),
            "state": state, "files": [p.name for p in files], "detail": reported.get("detail", ""),
            "required": sid in {"ru_ras", "ru_fns", "ru_minfin", "ru_vs", "nl_rechtspraak", "nl_belastingdienst_rulings", "nl_fd"},
        })
    return out


def item_by_n(date: str, n: int) -> dict:
    for item in shortlist(date).get("items", []):
        if int(item.get("n", 0)) == n:
            return item
    raise ValueError(f"В шортлисте за {date} нет материала №{n}.")


def default_draft(item: dict) -> str:
    summary = (item.get("summary") or "").strip()
    lead = summary or "Материал отобран для редакционной подготовки."
    return f"{item.get('title', '')}\n\n{lead}\n\nИсточник: {item.get('url', '')}".strip()


class PortalHandler(SimpleHTTPRequestHandler):
    server_version = "AcademyNewsPortal/1.0"

    def _token_ok(self) -> bool:
        token = os.getenv("PORTAL_TOKEN", "")
        if not token:
            return True
        provided = self.headers.get("X-Portal-Token", "")
        return provided == token

    def _json(self, data, status=200):
        blob = json.dumps(data, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(blob)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(blob)

    def _body(self) -> dict:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length) if length else b"{}"
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError as exc:
            raise ValueError("Ожидался JSON-запрос.") from exc

    def do_GET(self):  # noqa: N802
        parsed = urlparse(self.path)
        if parsed.path.startswith("/api/"):
            if not self._token_ok():
                return self._json({"error": "Нужен X-Portal-Token."}, 401)
            try:
                return self.api_get(parsed)
            except Exception as exc:  # pragma: no cover - boundary
                return self._json({"error": str(exc)}, 400)
        file_name = "index.html" if parsed.path in {"/", ""} else parsed.path.lstrip("/")
        target = (STATIC / file_name).resolve()
        if STATIC not in target.parents and target != STATIC:
            self.send_error(404); return
        if not target.is_file():
            self.send_error(404); return
        content = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", mimetypes.guess_type(str(target))[0] or "application/octet-stream")
        self.send_header("Content-Length", str(len(content)))
        self.end_headers(); self.wfile.write(content)

    def do_POST(self):  # noqa: N802
        if not self.path.startswith("/api/"):
            return self._json({"error": "Not found"}, 404)
        if not self._token_ok():
            return self._json({"error": "Нужен X-Portal-Token."}, 401)
        try:
            return self.api_post(urlparse(self.path), self._body())
        except Exception as exc:
            return self._json({"error": str(exc)}, 400)

    def api_get(self, parsed):
        path, query = parsed.path, parse_qs(parsed.query)
        if path == "/api/days":
            dates = sorted((p.name[:10] for p in (ROOT / "pipeline" / "shortlist").glob("????-??-??_shortlist.json")), reverse=True)
            return self._json({"dates": dates})
        if path == "/api/dashboard":
            date = query.get("date", [""])[0]
            if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", date):
                raise ValueError("Укажите дату YYYY-MM-DD.")
            data = shortlist(date)
            actions = read_json(action_path(date), {"items": {}}).get("items", {})
            for item in data.get("items", []):
                item["action"] = actions.get(str(item.get("n")), {})
                item["default_draft"] = default_draft(item)
            return self._json({"date": date, "items": data.get("items", []), "coverage": source_coverage(date),
                               "digest_exists": (ROOT / "pipeline" / "digest" / f"{date}_digest.md").exists()})
        if path == "/api/health":
            return self._json({"postiz_key": bool(os.getenv("POSTIZ_API_KEY")),
                               "telegram_digest": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_DIGEST_CHAT_ID")),
                               "cms": bool(os.getenv("WORDPRESS_API_BASE") and os.getenv("WORDPRESS_USER") and os.getenv("WORDPRESS_APP_PASSWORD")),
                               "bind": self.server.server_address[0]})
        raise ValueError("Неизвестный API-маршрут.")

    def api_post(self, parsed, body: dict):
        match = re.fullmatch(r"/api/items/(\d{4}-\d{2}-\d{2})/(\d+)/(select|draft|publish|skip)", parsed.path)
        if not match:
            raise ValueError("Неизвестный API-маршрут.")
        date, n, action = match.group(1), int(match.group(2)), match.group(3)
        item = item_by_n(date, n)
        actions = read_json(action_path(date), {"items": {}})
        records = actions.setdefault("items", {})
        record = records.setdefault(str(n), {})
        if action == "select":
            channels = [c for c in body.get("channels", []) if c in CHANNELS]
            if not channels:
                raise ValueError("Выберите хотя бы один канал.")
            record.update({"channels": channels, "note": str(body.get("note", "")), "status": "selected", "updated_at": now()})
            if item.get("item_id"):
                conn = newsdb.connect(str(ROOT))
                try:
                    newsdb.set_status(conn, item["item_id"], "assigned", channels=",".join(channels))
                finally:
                    newsdb.close(conn)
        elif action == "draft":
            channel = body.get("channel", "")
            if channel not in CHANNELS:
                raise ValueError("Неизвестный канал.")
            content = str(body.get("content", "")).strip()
            if not content:
                raise ValueError("Черновик не может быть пустым.")
            record.setdefault("drafts", {})[channel] = {"content": content, "status": "draft", "updated_at": now()}
            record["status"] = "drafted"; record["updated_at"] = now()
        elif action == "skip":
            record.update({"status": "skipped", "updated_at": now()})
            if item.get("item_id"):
                conn = newsdb.connect(str(ROOT))
                try:
                    newsdb.set_status(conn, item["item_id"], "skipped")
                finally:
                    newsdb.close(conn)
        else:  # publish
            if body.get("confirm") is not True:
                raise ValueError("Для отправки подтвердите действие confirm=true.")
            channel, mode = body.get("channel", ""), body.get("mode", "draft")
            if channel not in CHANNELS:
                raise ValueError("Неизвестный канал.")
            content = str(body.get("content") or record.get("drafts", {}).get(channel, {}).get("content", "")).strip()
            if not content:
                raise ValueError("Сначала сохраните черновик.")
            try:
                result = publish_wordpress(ROOT, item["title"], content, mode) if channel == "site" else publish_postiz(ROOT, channel, content, mode, body.get("schedule_at"))
            except Exception as exc:
                # Не выполняем скрытый автоповтор: таймаут после приёма запроса
                # может создать дубликат. Ошибка остаётся в очереди, а повтор
                # делает редактор тем же подтверждённым действием.
                record.setdefault("drafts", {}).setdefault(channel, {})
                record["drafts"][channel].update({"content": content, "status": "failed", "error": str(exc), "updated_at": now()})
                record["status"] = "delivery_failed"; record["updated_at"] = now()
                write_json(action_path(date), actions)
                delivery_path(date).parent.mkdir(parents=True, exist_ok=True)
                with delivery_path(date).open("a", encoding="utf-8") as f:
                    f.write(json.dumps({"date": date, "n": n, "channel": channel, "at": now(), "status": "failed", "error": str(exc)}, ensure_ascii=False) + "\n")
                raise
            record.setdefault("drafts", {}).setdefault(channel, {})
            record["drafts"][channel].update({"content": content, "status": "delivered", "delivery": result, "updated_at": now()})
            record["status"] = "delivered"; record["updated_at"] = now()
            delivery_path(date).parent.mkdir(parents=True, exist_ok=True)
            with delivery_path(date).open("a", encoding="utf-8") as f:
                f.write(json.dumps({"date": date, "n": n, "channel": channel, "at": now(), **result}, ensure_ascii=False) + "\n")
            if item.get("item_id"):
                conn = newsdb.connect(str(ROOT))
                try:
                    newsdb.add_published(conn, item["item_id"], channel, result.get("post_id", ""), result.get("post_url", ""))
                    newsdb.set_status(conn, item["item_id"], "published")
                finally:
                    newsdb.close(conn)
        write_json(action_path(date), actions)
        return self._json({"ok": True, "action": record})


def main() -> None:
    parser = argparse.ArgumentParser(description="Локальный веб-портал новостей Академии.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    args = parser.parse_args()
    load_env(ROOT / ".env.portal"); load_env(ROOT / ".env.postiz")
    server = ThreadingHTTPServer((args.host, args.port), PortalHandler)
    print(f"Портал: http://{args.host}:{args.port}  (Ctrl+C для остановки)")
    server.serve_forever()


if __name__ == "__main__":
    main()
