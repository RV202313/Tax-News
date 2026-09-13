#!/usr/bin/env python3
"""Единый движок выпуска из pipeline/approved/*.json.

Без execute-флагов выполняет только валидацию/сборку карточек. Любая
внешняя доставка требует approval по каждому посту в JSON и явный CLI-флаг.
Telegram идёт только в редакционный чат; главный канал скрипт не трогает.
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlsplit

from cards import resolve_image
from common import load_env
from session_guard import exclusive_session_lock

DEFAULT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_TELEGRAM_ROOT = DEFAULT_ROOT.parent / ".telegram_auth"
DEFAULT_SESSION = Path(os.getenv("ACADEMY_SESSION_PATH", str(DEFAULT_TELEGRAM_ROOT / "academy_news_windows.session")))
DEFAULT_ENV = Path(os.getenv("ACADEMY_ENV_PATH", str(DEFAULT_TELEGRAM_ROOT / ".env")))
EDITORIAL_CHAT_ID = -1004472011991
ALLOWED_CHANNELS = {"telegram_channel", "vk", "linkedin", "site", "email"}
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9._-]{2,120}$")
URL_RE = re.compile(r"https?://\S+", re.IGNORECASE)
HASHTAG_RE = re.compile(r"#[^\s]+")
LATIN_WORD_RE = re.compile(r"(?<![\w])([A-Za-z][A-Za-z'’.-]{2,})(?![\w])")
# Смешанное написание и официальные термины, которые нельзя надёжно отличить
# от обычных английских слов только по регистру. Аббревиатуры целиком в верхнем
# регистре (BEPS, OECD, HMRC, ECLI, MLI и т. п.) допускаются автоматически.
ALLOWED_LATIN_TERMS = {
    "globe", "pillar", "telegram", "linkedin", "wordpress", "postiz", "etims",
}


def untranslated_latin_terms(text: str) -> list[str]:
    """Найти переводимые латинские слова в предназначенном читателю тексте."""
    visible = URL_RE.sub(" ", str(text or ""))
    visible = HASHTAG_RE.sub(" ", visible)
    found = []
    for match in LATIN_WORD_RE.finditer(visible):
        token = match.group(1).strip(".'’-")
        letters = "".join(ch for ch in token if ch.isalpha())
        if len(letters) < 4 or letters.isupper():
            continue
        if token.casefold() in ALLOWED_LATIN_TERMS:
            continue
        if token not in found:
            found.append(token)
    return found


def _iso_date(value: str) -> str:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date().isoformat()
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Неверная дата выпуска: {value!r}") from exc


def parse_datetime(value: str) -> datetime:
    raw = str(value or "").strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"Неверный scheduled_at: {value!r}") from exc
    if parsed.tzinfo is None:
        raise ValueError("scheduled_at должен содержать timezone")
    return parsed


def _source_list(raw) -> list[dict]:
    out = []
    for value in raw or []:
        if isinstance(value, dict):
            label, url = str(value.get("label") or value.get("name") or "Источник"), str(value.get("url") or "")
        elif isinstance(value, (list, tuple)) and len(value) == 2:
            label, url = str(value[0]), str(value[1])
        else:
            raise ValueError(f"Неверная запись sources: {value!r}")
        parts = urlsplit(url)
        if parts.scheme not in {"http", "https"} or not parts.netloc:
            raise ValueError(f"Неверный URL источника: {url!r}")
        out.append({"label": label, "url": url})
    if not out:
        raise ValueError("У поста нет первичного источника")
    return out


def load_release(path: Path) -> dict:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        payload = {"date": path.stem[:10], "release": path.stem, "items": payload}
    if not isinstance(payload, dict) or not isinstance(payload.get("items"), list):
        raise ValueError("Approved JSON должен содержать object.items[]")
    date = _iso_date(payload.get("date"))
    items = []
    for raw in payload["items"]:
        if not isinstance(raw, dict):
            raise ValueError("Каждый items[] должен быть object")
        item = dict(raw)
        item["sources"] = _source_list(item.get("sources"))
        items.append(item)
    return {"date": date, "release": str(payload.get("release") or path.stem), "items": items}


def _approved(item: dict) -> bool:
    approval = item.get("approval") or {}
    return (
        approval.get("status") == "approved"
        and bool(str(approval.get("by") or "").strip())
        and bool(str(approval.get("evidence") or "").strip())
    )


def validate_release(release: dict, *, execution: bool, strict_count: bool = True) -> None:
    errors = []
    items = release["items"]
    if strict_count and len(items) != 10:
        errors.append(f"в выпуске должно быть ровно 10 постов, сейчас {len(items)}")
    seen = set()
    for index, item in enumerate(items, start=1):
        prefix = f"items[{index}]"
        slug = str(item.get("slug") or "")
        caption = str(item.get("caption") or "")
        title = str(item.get("title") or "").strip()
        if not SLUG_RE.fullmatch(slug):
            errors.append(f"{prefix}: неверный slug")
        if slug in seen:
            errors.append(f"{prefix}: дубль slug {slug}")
        seen.add(slug)
        if not title:
            errors.append(f"{prefix}: нет title")
        for field_name, text in (("title", title), ("caption", caption)):
            untranslated = untranslated_latin_terms(text)
            if untranslated:
                errors.append(
                    f"{prefix}: {field_name} содержит непереведённые английские "
                    f"слова: {', '.join(untranslated)}"
                )
        if not (1 <= len(caption) <= 1024):
            errors.append(f"{prefix}: caption {len(caption)} знаков (для media нужно ≤1024)")
        for hashtag in ("#АкадемияBEPS", "#АкадемияБЕПС"):
            if hashtag not in caption:
                errors.append(f"{prefix}: нет {hashtag}")
        if item.get("sources") and not any(src["url"] in caption for src in item["sources"]):
            errors.append(f"{prefix}: в caption нет прямой ссылки на первоисточник")
        channels = item.get("channels")
        if not isinstance(channels, list) or not channels:
            errors.append(f"{prefix}: channels должен быть непустым списком")
        elif set(channels) - ALLOWED_CHANNELS:
            errors.append(f"{prefix}: неизвестные channels {sorted(set(channels)-ALLOWED_CHANNELS)}")
        if not item.get("image_path") and not isinstance(item.get("image_spec"), dict):
            errors.append(f"{prefix}: нет image_path/image_spec")
        if item.get("image_path") and not (
            str(item.get("image_credit") or "").strip()
            and str(item.get("image_rights") or "").strip()
        ):
            errors.append(f"{prefix}: для image_path нужны image_credit и image_rights")
        if (item.get("court") or str(item.get("item_type") or "").startswith("court")) \
                and "не является налоговой консультацией" not in caption.casefold():
            errors.append(f"{prefix}: у судебного материала нет дисклеймера")
        if item.get("lead") and not item.get("primary_source_verified"):
            errors.append(f"{prefix}: Telegram lead не подтверждён по первоисточнику")
        if "[ЗАПОЛНИТ" in caption or "[ПРОВЕРИТЬ]" in caption:
            errors.append(f"{prefix}: в caption остался плейсхолдер")
        if item.get("scheduled_at"):
            try:
                scheduled = parse_datetime(item["scheduled_at"])
                if execution and scheduled <= datetime.now(timezone.utc):
                    errors.append(f"{prefix}: scheduled_at не в будущем")
            except ValueError as exc:
                errors.append(f"{prefix}: {exc}")
        if item.get("publish_mode") == "schedule" and not item.get("scheduled_at"):
            errors.append(f"{prefix}: publish_mode=schedule требует scheduled_at")
        if execution and not _approved(item):
            errors.append(f"{prefix}: нет индивидуального approval (status/by/evidence)")
    if errors:
        raise ValueError("Выпуск не прошёл валидацию:\n- " + "\n- ".join(errors))


def prepare_assets(root: Path, release: dict) -> dict[str, Path]:
    return {
        item["slug"]: resolve_image(root, release["date"], item)
        for item in release["items"]
    }


def delivery_path(root: Path, release_date: str) -> Path:
    return root / "pipeline" / "published" / f"{release_date}.jsonl"


def load_deliveries(root: Path, release_date: str) -> list[dict]:
    path = delivery_path(root, release_date)
    if not path.exists():
        return []
    out = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(value, dict):
            out.append(value)
    return out


def append_delivery(root: Path, record: dict) -> None:
    path = delivery_path(root, record["date"])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def release_run_id(release: dict, approved_path: Path, scope: str) -> str:
    approved_sha = _sha256(approved_path)
    safe_release = re.sub(r"[^A-Za-z0-9._-]+", "-", release["release"]).strip("-")
    return f"{safe_release}-{scope}-{approved_sha[:12]}"


def _artifact_record(source: Path, target: Path, *, role: str = "authoritative") -> dict:
    shutil.copy2(source, target)
    return {
        "state": "copied",
        "role": role,
        "path": target.name,
        "bytes": target.stat().st_size,
        "sha256": _sha256(target),
    }


def verify_run_record(summary_path: Path) -> dict:
    """Recompute hashes/sizes and release coverage of an immutable receipt."""
    summary_path = Path(summary_path).resolve()
    payload = json.loads(summary_path.read_text(encoding="utf-8"))
    if payload.get("run_id") != summary_path.parent.name:
        raise RuntimeError("run_record run_id не совпадает с именем каталога")
    artifacts = payload.get("artifacts") or {}
    for name, record in artifacts.items():
        if record.get("state") not in {"copied", "generated_release_slice"}:
            continue
        relative = Path(str(record.get("path") or ""))
        if not relative.name or relative.is_absolute() or len(relative.parts) != 1:
            raise RuntimeError(f"run_record {name}: небезопасный artifact path")
        artifact = summary_path.parent / relative
        if not artifact.is_file():
            raise RuntimeError(f"run_record {name}: артефакт отсутствует")
        if artifact.stat().st_size != record.get("bytes") or _sha256(artifact) != record.get("sha256"):
            raise RuntimeError(f"run_record {name}: SHA-256/размер не совпадает")
    approved = artifacts.get("approved") or {}
    if approved.get("sha256") != payload.get("approved_source_sha256"):
        raise RuntimeError("run_record: approved_source_sha256 не совпадает со слепком")
    approved_payload = json.loads((summary_path.parent / approved["path"]).read_text(encoding="utf-8"))
    approved_items = approved_payload if isinstance(approved_payload, list) else approved_payload.get("items", [])
    approved_slugs = {item.get("slug") for item in approved_items}
    sidecar = artifacts.get("published_sidecar") or {}
    delivered_slugs = set()
    for line in (summary_path.parent / sidecar["path"]).read_text(encoding="utf-8").splitlines():
        record = json.loads(line)
        if record.get("slug"):
            delivered_slugs.add(record["slug"])
    expected = payload.get("delivery_coverage") or {}
    recomputed = {
        "approved_slugs": len(approved_slugs),
        "delivered_slugs": len(delivered_slugs),
        "missing_slugs": sorted(approved_slugs - delivered_slugs),
        "unexpected_slugs": sorted(delivered_slugs - approved_slugs),
    }
    if recomputed != expected:
        raise RuntimeError("run_record: delivery_coverage не пересчитывается из слепков")
    return payload


def write_run_record(root: Path, release: dict, approved_path: Path, *,
                     scope: str, capture_kind: str = "execution",
                     expected_approved_sha256: str = "") -> Path:
    """Создать атомарный immutable release-of-record с SHA-256 и run_id."""
    run_id = release.get("run_id") or release_run_id(release, approved_path, scope)
    release["run_id"] = run_id
    parent = root / "pipeline" / "run_records" / release["date"]
    parent.mkdir(parents=True, exist_ok=True)
    run_dir = parent / run_id
    approved_sha = _sha256(approved_path)
    if expected_approved_sha256 and approved_sha != expected_approved_sha256:
        raise RuntimeError("Approved JSON изменился после начала execute; run-record не создан")
    if run_dir.exists():
        summary = run_dir / "run_record.json"
        if not summary.exists():
            raise RuntimeError(f"run_id уже занят неполным каталогом: {run_id}")
        payload = verify_run_record(summary)
        if payload.get("approved_source_sha256") != approved_sha:
            raise RuntimeError(f"run_id collision с другим approved: {run_id}")
        return summary

    temp_dir = Path(tempfile.mkdtemp(prefix=f".{run_id}.", dir=parent))
    try:
        artifacts = {
            "approved": _artifact_record(approved_path, temp_dir / "approved.json"),
        }
        volatile = {
            "shortlist": root / "pipeline" / "shortlist" / f"{release['date']}_shortlist.json",
            "digest": root / "pipeline" / "digest" / f"{release['date']}_digest.md",
            "collection_manifest": root / "pipeline" / "raw" / release["date"] / "collection_manifest.json",
            "collection_manifest_court": root / "pipeline" / "raw" / release["date"] / "collection_manifest_court.json",
        }
        for key, source in volatile.items():
            if capture_kind == "backfill":
                artifacts[key] = {
                    "state": "not_backfilled",
                    "reason": "артефакт изменяемый и не был зафиксирован в момент выпуска",
                }
            elif not source.exists():
                artifacts[key] = {"state": "missing", "role": "context_only"}
            else:
                artifacts[key] = _artifact_record(
                    source, temp_dir / source.name, role="context_only"
                )
                artifacts[key]["release_lineage"] = "not_asserted"

        records = [
            record for record in load_deliveries(root, release["date"])
            if record.get("release") == release["release"]
            and (
                scope in {"all", "backfill"}
                or (scope == "editorial" and record.get("delivery") == "telegram_editorial")
                or (scope == "nontelegram" and record.get("delivery") != "telegram_editorial")
            )
        ]
        sidecar = temp_dir / "published_release.jsonl"
        sidecar.write_text(
            "".join(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n" for record in records),
            encoding="utf-8",
        )
        artifacts["published_sidecar"] = {
            "state": "generated_release_slice",
            "path": sidecar.name,
            "bytes": sidecar.stat().st_size,
            "sha256": _sha256(sidecar),
            "records": len(records),
        }

        approved_slugs = {item["slug"] for item in release["items"]}
        delivery_slugs = {record.get("slug") for record in records}
        catalog_path = root.parent / "ОПУБЛИКОВАННЫЕ_НОВОСТИ.md"
        catalog_text = catalog_path.read_text(encoding="utf-8") if catalog_path.exists() else ""
        post_ids = [str(record.get("post_id") or "") for record in records if record.get("post_id")]
        catalog_ids = [post_id for post_id in post_ids if f"| {post_id} |" in catalog_text]
        payload = {
            "schema_version": 3,
            "run_id": run_id,
            "release": release["release"],
            "date": release["date"],
            "scope": scope,
            "capture_kind": capture_kind,
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "items_count": len(release["items"]),
            "approved_source_sha256": approved_sha,
            "release_source_of_truth": "approved.json",
            "daily_build_context_authoritative": False,
            "delivery_coverage": {
                "approved_slugs": len(approved_slugs),
                "delivered_slugs": len(delivery_slugs),
                "missing_slugs": sorted(approved_slugs - delivery_slugs),
                "unexpected_slugs": sorted(delivery_slugs - approved_slugs),
            },
            "catalog_coverage": {
                "post_ids": len(post_ids),
                "matched_post_ids": len(catalog_ids),
                "missing_post_ids": sorted(set(post_ids) - set(catalog_ids)),
            },
            "artifacts": artifacts,
        }
        summary_path = temp_dir / "run_record.json"
        summary_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp_dir, run_dir)
    except Exception:
        shutil.rmtree(temp_dir, ignore_errors=True)
        raise
    summary = run_dir / "run_record.json"
    verify_run_record(summary)
    return summary


def _esc(value: str) -> str:
    return str(value or "").replace("|", "\\|").replace("\n", "<br>")


def _catalog_sources(item: dict) -> str:
    return "; ".join(f"[{_esc(src['label'])}]({src['url']})" for src in item["sources"])


def upsert_catalog(catalog: Path, release_date: str, item: dict, chat_id: str) -> None:
    """Обновить строку по chat id / URL / акту или добавить одну новую."""
    if not catalog.exists():
        raise FileNotFoundError(f"Каталог не найден: {catalog}")
    row = (
        f"| {release_date} | — | {chat_id} | На обсуждении | {_esc(item['title'])} | "
        f"{_esc(item.get('theme', ''))} | {_esc(item.get('jurisdictions', ''))} | "
        f"{_esc(item.get('act', ''))} | {_catalog_sources(item)} |"
    )
    lines = catalog.read_text(encoding="utf-8").splitlines()
    urls = [src["url"] for src in item["sources"]]
    act = str(item.get("act") or "").strip().casefold()
    match = None
    for index, line in enumerate(lines):
        if not line.startswith("|") or line.startswith("|---") or "| Дата |" in line:
            continue
        if f"| {chat_id} |" in line or any(url in line for url in urls):
            match = index
            break
    if match is None:
        lines.append(row)
    else:
        lines[match] = row
    fd, tmp_name = tempfile.mkstemp(prefix=f".{catalog.name}.", dir=catalog.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text("\n".join(lines) + "\n", encoding="utf-8")
        os.replace(tmp, catalog)
    finally:
        tmp.unlink(missing_ok=True)


def ensure_session_idle(session_path: Path) -> None:
    import sys
    if sys.platform == "win32":
        return
    lsof = shutil.which("lsof")
    if not lsof:
        raise RuntimeError("lsof не найден; безопасно проверить владельца Telethon-session нельзя")
    result = subprocess.run([lsof, "-t", "--", str(session_path)], text=True,
                            capture_output=True, check=False)
    other_pids = {
        value for value in result.stdout.split()
        if value.isdigit() and int(value) != os.getpid()
    }
    if other_pids:
        raise RuntimeError("Telethon-session уже используется другим процессом")


async def execute_editorial(root: Path, release: dict, assets: dict[str, Path],
                            *, session_path: Path = DEFAULT_SESSION,
                            env_path: Path = DEFAULT_ENV, client_factory=None) -> list[dict]:
    """Отправить в редчат; в главный Telegram-канал эта функция не умеет."""
    validate_release(release, execution=True)
    existing = {
        (record.get("slug"), record.get("delivery")): record
        for record in load_deliveries(root, release["date"])
    }
    catalog = root.parent / "ОПУБЛИКОВАННЫЕ_НОВОСТИ.md"
    pending = []
    for item in release["items"]:
        old = existing.get((item["slug"], "telegram_editorial"))
        if old:
            # Если процесс раньше упал после сайдкара, каталог чинится
            # локально без повторного Telegram-вызова.
            upsert_catalog(catalog, release["date"], item, str(old["post_id"]))
        else:
            pending.append(item)
    if not pending:
        return []
    session_path = session_path.expanduser().resolve()
    if not session_path.is_file():
        raise RuntimeError("Существующая Telethon-session не найдена; новая не создаётся")
    with exclusive_session_lock(session_path):
        ensure_session_idle(session_path)
        load_env(env_path)
        api_id, api_hash = os.getenv("TELEGRAM_API_ID", ""), os.getenv("TELEGRAM_API_HASH", "")
        if not api_id or not api_hash:
            raise RuntimeError("TELEGRAM_API_ID/HASH не найдены")
        if client_factory is None:
            from telethon import TelegramClient
            client_factory = TelegramClient
        client = client_factory(str(session_path), int(api_id), api_hash)
        emitted = []
        await client.connect()
        try:
            # Первый Telegram API-вызов после connect — только get_me().
            me = await client.get_me()
            if me is None or (getattr(me, "username", "") or "").casefold() != "academy_of_beps":
                raise RuntimeError("Неверный Telegram-аккаунт; отправка остановлена")
            for item in pending:
                # Корневой мануал требует account gate непосредственно
                # перед каждым действием отправки, а не только при connect.
                me = await client.get_me()
                if me is None or (getattr(me, "username", "") or "").casefold() != "academy_of_beps":
                    raise RuntimeError("Неверный Telegram-аккаунт; отправка остановлена")
                kwargs = {"caption": item["caption"], "force_document": False}
                if item.get("scheduled_at"):
                    kwargs["schedule"] = parse_datetime(item["scheduled_at"])
                message = await client.send_file(
                    EDITORIAL_CHAT_ID, str(assets[item["slug"]]), **kwargs
                )
                record = {
                    "date": release["date"], "release": release["release"],
                    "run_id": release.get("run_id", ""),
                    "slug": item["slug"], "delivery": "telegram_editorial",
                    "post_id": str(message.id), "post_url": "",
                    "recorded_at": datetime.now(timezone.utc).isoformat(),
                }
                append_delivery(root, record)
                upsert_catalog(catalog, release["date"], item, str(message.id))
                emitted.append(record)
        finally:
            await client.disconnect()
    return emitted


def execute_non_telegram(root: Path, release: dict, assets: dict[str, Path]) -> list[dict]:
    """Доставить VK/LinkedIn/Postiz и site/WordPress; Telegram через Postiz запрещён."""
    validate_release(release, execution=True)
    sys.path.insert(0, str(root / "portal"))
    from publishers import publish_postiz, publish_wordpress
    existing = {
        (record.get("slug"), record.get("delivery")): record
        for record in load_deliveries(root, release["date"])
    }
    emitted = []
    for item in release["items"]:
        for channel in item["channels"]:
            if channel == "telegram_channel":
                continue  # никогда не дублируем TG через Postiz
            if channel == "email":
                draft = root / "pipeline" / "drafts" / "email" / release["date"] / f"{item['slug']}.md"
                draft.parent.mkdir(parents=True, exist_ok=True)
                draft.write_text(item["caption"] + "\n", encoding="utf-8")
                continue
            key = (item["slug"], channel)
            if key in existing:
                continue
            if channel in {"vk", "linkedin"}:
                mode = "draft" if channel == "linkedin" else str(item.get("publish_mode") or "draft")
                result = publish_postiz(
                    root, channel, item["caption"], mode=mode,
                    schedule_at=item.get("scheduled_at"), media_paths=[assets[item["slug"]]],
                )
            elif channel == "site":
                result = publish_wordpress(
                    root, item["title"], item["caption"],
                    mode=str(item.get("publish_mode") or "draft"),
                )
            else:  # validate_release не пропускает иные каналы
                continue
            record = {
                "date": release["date"], "release": release["release"],
                "run_id": release.get("run_id", ""),
                "slug": item["slug"], "delivery": channel,
                "post_id": str(result.get("post_id", "")),
                "post_url": str(result.get("post_url", "")),
                "mode": str(result.get("mode", "")),
                "recorded_at": datetime.now(timezone.utc).isoformat(),
            }
            append_delivery(root, record)
            emitted.append(record)
    return emitted


def dry_run_summary(release: dict, assets: dict[str, Path]) -> dict:
    return {
        "status": "DRY_RUN",
        "date": release["date"],
        "release": release["release"],
        "count": len(release["items"]),
        "items": [
            {
                "slug": item["slug"], "caption_chars": len(item["caption"]),
                "channels": item["channels"], "scheduled_at": item.get("scheduled_at", ""),
                "image": str(assets[item["slug"]]),
            }
            for item in release["items"]
        ],
    }


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
        
    parser = argparse.ArgumentParser(description="Выпуск из approved JSON; default = dry-run.")
    parser.add_argument("approved_json", nargs="?")
    parser.add_argument("--root", default=str(DEFAULT_ROOT))
    parser.add_argument("--execute-editorial", action="store_true")
    parser.add_argument("--execute-non-telegram", action="store_true")
    parser.add_argument("--backfill-run-record", action="store_true",
                        help="Без сети: честный backfill approved+release-sidecar; volatile artifacts не подменяются.")
    parser.add_argument("--verify-run-record", default="",
                        help="Без сети: пересчитать SHA-256/покрытие готового run_record.json.")
    parser.add_argument("--session", default=str(DEFAULT_SESSION))
    parser.add_argument("--env", default=str(DEFAULT_ENV))
    args = parser.parse_args()
    root = Path(args.root).resolve()
    try:
        if args.verify_run_record:
            verify_run_record(Path(args.verify_run_record))
            print(f"[publish] run_record verified: {Path(args.verify_run_record).resolve()}")
            return 0
        if not args.approved_json:
            raise ValueError("Нужен approved_json или --verify-run-record")
        approved_path = Path(args.approved_json).resolve()
        approved_sha_at_start = _sha256(approved_path)
        release = load_release(approved_path)
        execution = args.execute_editorial or args.execute_non_telegram
        if args.backfill_run_record and execution:
            raise ValueError("--backfill-run-record несовместим с execute-флагами")
        validate_release(release, execution=execution)
        if args.backfill_run_record:
            release["run_id"] = release_run_id(release, approved_path, "backfill")
            run_record = write_run_record(
                root, release, approved_path, scope="backfill", capture_kind="backfill"
            )
            print(f"[publish] run_record: {run_record}")
            return 0
        scope = "all" if args.execute_editorial and args.execute_non_telegram else (
            "editorial" if args.execute_editorial else "nontelegram"
        )
        if execution:
            release["run_id"] = release_run_id(release, approved_path, scope)
        assets = prepare_assets(root, release)
        if not execution:
            print(json.dumps(dry_run_summary(release, assets), ensure_ascii=False, indent=2))
            return 0
        if args.execute_editorial:
            sent = asyncio.run(execute_editorial(
                root, release, assets, session_path=Path(args.session), env_path=Path(args.env)
            ))
            print(f"[publish] editorial: {len(sent)} новых")
        if args.execute_non_telegram:
            sent = execute_non_telegram(root, release, assets)
            print(f"[publish] non-telegram: {len(sent)} новых")
        run_record = write_run_record(
            root, release, approved_path, scope=scope,
            expected_approved_sha256=approved_sha_at_start,
        )
        print(f"[publish] run_record: {run_record}")
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        import traceback
        traceback.print_exc()
        print(f"[publish] ошибка: {exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
