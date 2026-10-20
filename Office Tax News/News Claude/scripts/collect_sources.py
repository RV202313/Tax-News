#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Единый транспортный слой сбора источников v2 (Фаза 1).

Прямой HTTP (requests) с браузерным User-Agent, ретраями с backoff и таймаутами.
Метод берётся из config/sources.yaml, хардкода MANUAL больше нет:
  - method: chrome            → ручной добор (в манифесте state=manual);
  - поле collector: <script>  → источник обслуживает свой скрипт (nl_rechtspraak),
                                здесь пропускаем (state=delegated);
  - иначе (http / web_fetch)  → фетчим endpoints напрямую (RSS-first, если заданы
                                rss_endpoints), сырьё пишем как есть.

Пишет сырьё в pipeline/raw/{date}/{sid}_{n}.txt (КАК ЕСТЬ), ведёт
pipeline/raw/{date}/collection_manifest.json и обновляет runs.sources_ok/failed
(шапка дайджеста наконец получит реальные сигналы покрытия).

ВАЖНО: запускать НА МАКЕ — у него есть сеть. Из облачной песочницы координатора
внешней сети нет, поэтому живой сбор здесь не выполняется (см. КООРДИНАЦИЯ →
«Запросы к Codex»). Парсинг сырья — отдельным шагом scripts/parse_feeds.py.

Использование:
  python3 scripts/collect_sources.py --date 2026-07-17 [--root .] [--only ru_garant]
"""

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from source_http import source_headers
from datetime import date as date_cls, timedelta
from pathlib import Path

import http_support

try:
    import requests
except ImportError:  # pragma: no cover
    print("Нужен requests: pip3 install requests --break-system-packages", file=sys.stderr)
    sys.exit(2)
try:
    import yaml
except ImportError:  # pragma: no cover
    print("Нужен PyYAML: pip3 install pyyaml --break-system-packages", file=sys.stderr)
    sys.exit(2)

# newsdb лежит рядом (scripts/) — для обновления runs.sources_ok/failed.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import newsdb
except Exception:  # обновление runs — необязательное; без newsdb просто пропустим
    newsdb = None

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TIMEOUT = 30
RETRIES = 3
BACKOFF = 2.0   # секунды * номер попытки
PAUSE = 2.0     # пауза между источниками (вежливость)


def _manifest_summary(sources):
    ok, failed, incomplete = [], [], []
    for sid, record in (sources or {}).items():
        state = record.get("state")
        if state == "ok":
            ok.append(sid)
        elif state in {"failed", "missing"}:
            failed.append(sid)
        elif state in {"manual", "delegated"}:
            incomplete.append(f"{sid}:{state}")
    return {
        "ok": sorted(ok),
        "failed": sorted(failed),
        "incomplete": sorted(incomplete),
    }


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def _persist_manifest(raw: Path, manifest: dict, *, only: str | None) -> dict:
    """Точечный сбор обновляет один источник, не стирая покрытие остальных."""
    target = raw / "collection_manifest.json"
    if not only:
        combined = manifest
    else:
        existing = {}
        if target.exists():
            try:
                value = json.loads(target.read_text(encoding="utf-8"))
                if value.get("date") == manifest.get("date"):
                    existing = dict(value.get("sources") or {})
            except (OSError, ValueError, json.JSONDecodeError):
                existing = {}
        existing.update(manifest.get("sources") or {})
        combined = {
            "date": manifest["date"],
            "sources": existing,
            "_summary": _manifest_summary(existing),
        }
        # Отдельный receipt показывает ровно то, что сделал targeted-вызов.
        _atomic_json(raw / f"collection_manifest_{only}.json", manifest)
    _atomic_json(target, combined)
    return combined


def fetch(session, url):
    """GET с ретраями. Возвращает (bytes, status, content_type, final_url, error)."""
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT, headers=source_headers(url))
            body = r.content or b""
            if r.status_code == 200 and body.strip():
                return body, r.status_code, r.headers.get("Content-Type", ""), r.url, None
            last = f"HTTP {r.status_code}, len={len(body)}"
        except requests.RequestException as e:
            last = str(e)
        if attempt < RETRIES:
            time.sleep(BACKOFF * attempt)
    return b"", None, "", url, last


def collect(root, run_date, only=None, skip_telegram=False):
    """Собрать источники по sources.yaml. Возвращает манифест (dict)."""
    root = Path(root).resolve()
    cfg = yaml.safe_load((root / "config" / "sources.yaml").read_text(encoding="utf-8")) or {}
    raw = root / "pipeline" / "raw" / run_date
    raw.mkdir(parents=True, exist_ok=True)
    yesterday = (date_cls.fromisoformat(run_date) - timedelta(days=1)).isoformat()

    session = http_support.new_session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8,nl;q=0.6"})

    manifest = {"date": run_date, "sources": {}}
    ok, failed, incomplete = [], [], []

    for src in cfg.get("sources", []):
        sid = src["id"]
        if only and sid != only:
            continue
        print(f"[collect] Fetching {sid}", flush=True)
        method = (src.get("method") or "web_fetch").lower()

        # Один календарный день может собираться несколько раз. Удаляем только
        # предыдущие файлы этого источника до новой попытки: иначе после 403/404
        # parse_feeds подхватит старый raw-файл и ошибочно отметит его свежим.
        for previous in raw.glob(f"{sid}_*.txt"):
            previous.unlink()

        if skip_telegram and "telegram" in str(src.get("collector", "")).lower():
            manifest["sources"][sid] = {"state": "manual", "detail": "Telegram disabled for local collection"}
            incomplete.append(f"{sid}:manual")
            continue

        if method == "chrome":
            manifest["sources"][sid] = {"state": "manual",
                                        "detail": "нужна браузерная сессия (Chrome), автосбор не выполняется"}
            incomplete.append(f"{sid}:manual")
            continue

        if src.get("collector"):
            script = root / src["collector"]
            if script.suffix.casefold() == ".js":
                node = shutil.which("node")
                cmd = ([node, str(script)] if node else [])
            else:
                interpreter = src.get("interpreter") or sys.executable
                cmd = [str(interpreter), str(script)]
            cmd += ["--date", run_date, "--root", str(root)] if cmd else []
            cmd += [str(value) for value in src.get("collector_args", []) or []]
            try:
                if not cmd:
                    raise OSError("node не найден для JS-коллектора")
                timeout = int(src.get("collector_timeout") or 120)
                result = subprocess.run(cmd, cwd=root, encoding="utf-8", capture_output=True,
                                        timeout=timeout, check=False)
                files = sorted(p.name for p in raw.glob(f"{sid}_*.txt"))
                if result.returncode == 0 and files:
                    state = "ok"
                elif result.returncode == 3:
                    state = "manual"
                else:
                    state = "failed"
                detail = (result.stdout + "\n" + result.stderr).strip()[-1200:]
            except (OSError, subprocess.SubprocessError) as exc:
                files, state, detail = [], "failed", str(exc)
            manifest["sources"][sid] = {
                "state": state, "files": files,
                "detail": f"collector={src['collector']}; {detail}"[:1400],
            }
            if state == "ok":
                ok.append(sid)
            elif state == "manual":
                incomplete.append(f"{sid}:manual")
            else:
                failed.append(sid)
            continue
        # RSS-first: rss_endpoints пробуем перед обычными endpoints.
        endpoints = list(src.get("rss_endpoints") or []) + list(src.get("endpoints") or [])
        if not endpoints:
            manifest["sources"][sid] = {"state": "missing", "detail": "нет endpoint в конфиге"}
            failed.append(sid)
            continue

        saved, errors, fetches = [], [], []
        n = 0
        groups = []
        if src.get("rss_endpoints"):
            groups.append(("rss", list(src.get("rss_endpoints") or [])))
        groups.append(("html", list(src.get("endpoints") or [])))
        for transport, group_endpoints in groups:
            group_saved = 0
            for ep in group_endpoints:
                # Шаблон с {FROM} — сегодня+вчера.
                days = [run_date, yesterday] if "{FROM}" in ep else [None]
                for day in days:
                    url = ep.replace("{FROM}", day) if day else ep
                    body, status, content_type, final_url, err = fetch(session, url)
                    if err or not body:
                        errors.append(f"{url}: {err or 'пусто'}")
                        continue
                    n += 1
                    fname = f"{sid}_{n}.txt"
                    (raw / fname).write_bytes(body)
                    saved.append(fname)
                    group_saved += 1
                    fetches.append({"file": fname, "transport": transport,
                                    "url": final_url, "status": status,
                                    "content_type": content_type, "bytes": len(body)})
            # RSS-first: если настоящий endpoint успешно получен, HTML не нужен.
            if transport == "rss" and group_saved:
                break
        manifest["sources"][sid] = {"state": "ok" if saved else "failed",
                                    "files": saved, "fetches": fetches,
                                    "detail": "; ".join(errors)[:600]}
        (ok if saved else failed).append(sid)
        time.sleep(PAUSE)

    optional_ids = {s.get("id") for s in cfg.get("sources", []) if s.get("optional")}
    for sid in [s for s in failed if s in optional_ids]:
        manifest["sources"][sid]["state"] = "degraded"
        failed.remove(sid)
        incomplete.append(f"{sid}:degraded")

    manifest["_summary"] = {"ok": sorted(ok), "failed": sorted(failed),
                            "incomplete": sorted(incomplete)}
    _persist_manifest(raw, manifest, only=only)

    # Обновить runs.sources_ok/failed (полный прогон, не точечный --only).
    if newsdb is not None and not only:
        try:
            conn = newsdb.connect(str(root))
            try:
                newsdb.upsert_run(conn, run_date, started=newsdb.now_iso(),
                                  sources_ok=",".join(sorted(ok)),
                                  sources_failed=",".join(sorted(failed + incomplete)))
            finally:
                newsdb.close(conn)
        except Exception as e:  # обновление runs не должно ронять сбор
            print(f"[collect] не удалось обновить runs: {e}", file=sys.stderr)

    return manifest


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="Единый HTTP-сбор источников (v2).")
    ap.add_argument("--date", default=date_cls.today().isoformat(), help="Дата YYYY-MM-DD.")
    ap.add_argument("--root", default=".", help="Корень проекта News Claude.")
    ap.add_argument("--only", default=None, help="Собрать только источник sid.")
    ap.add_argument("--skip-telegram", action="store_true")
    args = ap.parse_args()
    manifest = collect(args.root, args.date, only=args.only, skip_telegram=args.skip_telegram)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    s = manifest.get("_summary", {})
    print(f"[collect] OK={len(s.get('ok', []))} FAILED={len(s.get('failed', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
