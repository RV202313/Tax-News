#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ð•Ð´Ð¸Ð½Ñ‹Ð¹ Ñ‚Ñ€Ð°Ð½ÑÐ¿Ð¾Ñ€Ñ‚Ð½Ñ‹Ð¹ ÑÐ»Ð¾Ð¹ ÑÐ±Ð¾Ñ€Ð° Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð² v2 (Ð¤Ð°Ð·Ð° 1).

ÐŸÑ€ÑÐ¼Ð¾Ð¹ HTTP (requests) Ñ Ð±Ñ€Ð°ÑƒÐ·ÐµÑ€Ð½Ñ‹Ð¼ User-Agent, Ñ€ÐµÑ‚Ñ€Ð°ÑÐ¼Ð¸ Ñ backoff Ð¸ Ñ‚Ð°Ð¹Ð¼Ð°ÑƒÑ‚Ð°Ð¼Ð¸.
ÐœÐµÑ‚Ð¾Ð´ Ð±ÐµÑ€Ñ‘Ñ‚ÑÑ Ð¸Ð· config/sources.yaml, Ñ…Ð°Ñ€Ð´ÐºÐ¾Ð´Ð° MANUAL Ð±Ð¾Ð»ÑŒÑˆÐµ Ð½ÐµÑ‚:
  - method: chrome            â†’ Ñ€ÑƒÑ‡Ð½Ð¾Ð¹ Ð´Ð¾Ð±Ð¾Ñ€ (Ð² Ð¼Ð°Ð½Ð¸Ñ„ÐµÑÑ‚Ðµ state=manual);
  - Ð¿Ð¾Ð»Ðµ collector: <script>  â†’ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº Ð¾Ð±ÑÐ»ÑƒÐ¶Ð¸Ð²Ð°ÐµÑ‚ ÑÐ²Ð¾Ð¹ ÑÐºÑ€Ð¸Ð¿Ñ‚ (nl_rechtspraak),
                                Ð·Ð´ÐµÑÑŒ Ð¿Ñ€Ð¾Ð¿ÑƒÑÐºÐ°ÐµÐ¼ (state=delegated);
  - Ð¸Ð½Ð°Ñ‡Ðµ (http / web_fetch)  â†’ Ñ„ÐµÑ‚Ñ‡Ð¸Ð¼ endpoints Ð½Ð°Ð¿Ñ€ÑÐ¼ÑƒÑŽ (RSS-first, ÐµÑÐ»Ð¸ Ð·Ð°Ð´Ð°Ð½Ñ‹
                                rss_endpoints), ÑÑ‹Ñ€ÑŒÑ‘ Ð¿Ð¸ÑˆÐµÐ¼ ÐºÐ°Ðº ÐµÑÑ‚ÑŒ.

ÐŸÐ¸ÑˆÐµÑ‚ ÑÑ‹Ñ€ÑŒÑ‘ Ð² pipeline/raw/{date}/{sid}_{n}.txt (ÐšÐÐš Ð•Ð¡Ð¢Ð¬), Ð²ÐµÐ´Ñ‘Ñ‚
pipeline/raw/{date}/collection_manifest.json Ð¸ Ð¾Ð±Ð½Ð¾Ð²Ð»ÑÐµÑ‚ runs.sources_ok/failed
(ÑˆÐ°Ð¿ÐºÐ° Ð´Ð°Ð¹Ð´Ð¶ÐµÑÑ‚Ð° Ð½Ð°ÐºÐ¾Ð½ÐµÑ† Ð¿Ð¾Ð»ÑƒÑ‡Ð¸Ñ‚ Ñ€ÐµÐ°Ð»ÑŒÐ½Ñ‹Ðµ ÑÐ¸Ð³Ð½Ð°Ð»Ñ‹ Ð¿Ð¾ÐºÑ€Ñ‹Ñ‚Ð¸Ñ).

Ð’ÐÐ–ÐÐž: Ð·Ð°Ð¿ÑƒÑÐºÐ°Ñ‚ÑŒ ÐÐ ÐœÐÐšÐ• â€” Ñƒ Ð½ÐµÐ³Ð¾ ÐµÑÑ‚ÑŒ ÑÐµÑ‚ÑŒ. Ð˜Ð· Ð¾Ð±Ð»Ð°Ñ‡Ð½Ð¾Ð¹ Ð¿ÐµÑÐ¾Ñ‡Ð½Ð¸Ñ†Ñ‹ ÐºÐ¾Ð¾Ñ€Ð´Ð¸Ð½Ð°Ñ‚Ð¾Ñ€Ð°
Ð²Ð½ÐµÑˆÐ½ÐµÐ¹ ÑÐµÑ‚Ð¸ Ð½ÐµÑ‚, Ð¿Ð¾ÑÑ‚Ð¾Ð¼Ñƒ Ð¶Ð¸Ð²Ð¾Ð¹ ÑÐ±Ð¾Ñ€ Ð·Ð´ÐµÑÑŒ Ð½Ðµ Ð²Ñ‹Ð¿Ð¾Ð»Ð½ÑÐµÑ‚ÑÑ (ÑÐ¼. ÐšÐžÐžÐ Ð”Ð˜ÐÐÐ¦Ð˜Ð¯ â†’
Â«Ð—Ð°Ð¿Ñ€Ð¾ÑÑ‹ Ðº CodexÂ»). ÐŸÐ°Ñ€ÑÐ¸Ð½Ð³ ÑÑ‹Ñ€ÑŒÑ â€” Ð¾Ñ‚Ð´ÐµÐ»ÑŒÐ½Ñ‹Ð¼ ÑˆÐ°Ð³Ð¾Ð¼ scripts/parse_feeds.py.

Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ð½Ð¸Ðµ:
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
from datetime import date as date_cls, timedelta
from pathlib import Path

try:
    import requests
except ImportError:  # pragma: no cover
    print("ÐÑƒÐ¶ÐµÐ½ requests: pip3 install requests --break-system-packages", file=sys.stderr)
    sys.exit(2)
try:
    import yaml
except ImportError:  # pragma: no cover
    print("ÐÑƒÐ¶ÐµÐ½ PyYAML: pip3 install pyyaml --break-system-packages", file=sys.stderr)
    sys.exit(2)

# newsdb Ð»ÐµÐ¶Ð¸Ñ‚ Ñ€ÑÐ´Ð¾Ð¼ (scripts/) â€” Ð´Ð»Ñ Ð¾Ð±Ð½Ð¾Ð²Ð»ÐµÐ½Ð¸Ñ runs.sources_ok/failed.
sys.path.insert(0, str(Path(__file__).resolve().parent))
try:
    import newsdb
except Exception:  # Ð¾Ð±Ð½Ð¾Ð²Ð»ÐµÐ½Ð¸Ðµ runs â€” Ð½ÐµÐ¾Ð±ÑÐ·Ð°Ñ‚ÐµÐ»ÑŒÐ½Ð¾Ðµ; Ð±ÐµÐ· newsdb Ð¿Ñ€Ð¾ÑÑ‚Ð¾ Ð¿Ñ€Ð¾Ð¿ÑƒÑÑ‚Ð¸Ð¼
    newsdb = None

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
TIMEOUT = 30
RETRIES = 3
BACKOFF = 2.0   # ÑÐµÐºÑƒÐ½Ð´Ñ‹ * Ð½Ð¾Ð¼ÐµÑ€ Ð¿Ð¾Ð¿Ñ‹Ñ‚ÐºÐ¸
PAUSE = 2.0     # Ð¿Ð°ÑƒÐ·Ð° Ð¼ÐµÐ¶Ð´Ñƒ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ°Ð¼Ð¸ (Ð²ÐµÐ¶Ð»Ð¸Ð²Ð¾ÑÑ‚ÑŒ)


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
    """Ð¢Ð¾Ñ‡ÐµÑ‡Ð½Ñ‹Ð¹ ÑÐ±Ð¾Ñ€ Ð¾Ð±Ð½Ð¾Ð²Ð»ÑÐµÑ‚ Ð¾Ð´Ð¸Ð½ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº, Ð½Ðµ ÑÑ‚Ð¸Ñ€Ð°Ñ Ð¿Ð¾ÐºÑ€Ñ‹Ñ‚Ð¸Ðµ Ð¾ÑÑ‚Ð°Ð»ÑŒÐ½Ñ‹Ñ…."""
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
        # ÐžÑ‚Ð´ÐµÐ»ÑŒÐ½Ñ‹Ð¹ receipt Ð¿Ð¾ÐºÐ°Ð·Ñ‹Ð²Ð°ÐµÑ‚ Ñ€Ð¾Ð²Ð½Ð¾ Ñ‚Ð¾, Ñ‡Ñ‚Ð¾ ÑÐ´ÐµÐ»Ð°Ð» targeted-Ð²Ñ‹Ð·Ð¾Ð².
        _atomic_json(raw / f"collection_manifest_{only}.json", manifest)
    _atomic_json(target, combined)
    return combined


def fetch(session, url):
    """GET Ñ Ñ€ÐµÑ‚Ñ€Ð°ÑÐ¼Ð¸. Ð’Ð¾Ð·Ð²Ñ€Ð°Ñ‰Ð°ÐµÑ‚ (bytes, status, content_type, final_url, error)."""
    last = None
    for attempt in range(1, RETRIES + 1):
        try:
            r = session.get(url, timeout=TIMEOUT)
            body = r.content or b""
            if r.status_code == 200 and body.strip():
                return body, r.status_code, r.headers.get("Content-Type", ""), r.url, None
            last = f"HTTP {r.status_code}, len={len(body)}"
        except requests.RequestException as e:
            last = str(e)
        if attempt < RETRIES:
            time.sleep(BACKOFF * attempt)
    return b"", None, "", url, last


def collect(root, run_date, only=None):
    """Ð¡Ð¾Ð±Ñ€Ð°Ñ‚ÑŒ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¸ Ð¿Ð¾ sources.yaml. Ð’Ð¾Ð·Ð²Ñ€Ð°Ñ‰Ð°ÐµÑ‚ Ð¼Ð°Ð½Ð¸Ñ„ÐµÑÑ‚ (dict)."""
    root = Path(root).resolve()
    cfg = yaml.safe_load((root / "config" / "sources.yaml").read_text(encoding="utf-8")) or {}
    raw = root / "pipeline" / "raw" / run_date
    raw.mkdir(parents=True, exist_ok=True)
    yesterday = (date_cls.fromisoformat(run_date) - timedelta(days=1)).isoformat()

    session = requests.Session()
    session.headers.update({"User-Agent": UA, "Accept-Language": "ru,en;q=0.8,nl;q=0.6"})

    manifest = {"date": run_date, "sources": {}}
    ok, failed, incomplete = [], [], []

    for src in cfg.get("sources", []):
        sid = src["id"]
        if only and sid != only:
            continue
        method = (src.get("method") or "web_fetch").lower()

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
                    raise OSError("node Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½ Ð´Ð»Ñ JS-ÐºÐ¾Ð»Ð»ÐµÐºÑ‚Ð¾Ñ€Ð°")
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
        if method == "chrome":
            manifest["sources"][sid] = {"state": "manual",
                                        "detail": "Ð½ÑƒÐ¶Ð½Ð° Ð±Ñ€Ð°ÑƒÐ·ÐµÑ€Ð½Ð°Ñ ÑÐµÑÑÐ¸Ñ (Chrome), Ð°Ð²Ñ‚Ð¾ÑÐ±Ð¾Ñ€ Ð½Ðµ Ð²Ñ‹Ð¿Ð¾Ð»Ð½ÑÐµÑ‚ÑÑ"}
            incomplete.append(f"{sid}:manual")
            continue

        # RSS-first: rss_endpoints Ð¿Ñ€Ð¾Ð±ÑƒÐµÐ¼ Ð¿ÐµÑ€ÐµÐ´ Ð¾Ð±Ñ‹Ñ‡Ð½Ñ‹Ð¼Ð¸ endpoints.
        endpoints = list(src.get("rss_endpoints") or []) + list(src.get("endpoints") or [])
        if not endpoints:
            manifest["sources"][sid] = {"state": "missing", "detail": "Ð½ÐµÑ‚ endpoint Ð² ÐºÐ¾Ð½Ñ„Ð¸Ð³Ðµ"}
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
                # Ð¨Ð°Ð±Ð»Ð¾Ð½ Ñ {FROM} â€” ÑÐµÐ³Ð¾Ð´Ð½Ñ+Ð²Ñ‡ÐµÑ€Ð°.
                days = [run_date, yesterday] if "{FROM}" in ep else [None]
                for day in days:
                    url = ep.replace("{FROM}", day) if day else ep
                    body, status, content_type, final_url, err = fetch(session, url)
                    if err or not body:
                        errors.append(f"{url}: {err or 'Ð¿ÑƒÑÑ‚Ð¾'}")
                        continue
                    n += 1
                    fname = f"{sid}_{n}.txt"
                    (raw / fname).write_bytes(body)
                    saved.append(fname)
                    group_saved += 1
                    fetches.append({"file": fname, "transport": transport,
                                    "url": final_url, "status": status,
                                    "content_type": content_type, "bytes": len(body)})
            # RSS-first: ÐµÑÐ»Ð¸ Ð½Ð°ÑÑ‚Ð¾ÑÑ‰Ð¸Ð¹ endpoint ÑƒÑÐ¿ÐµÑˆÐ½Ð¾ Ð¿Ð¾Ð»ÑƒÑ‡ÐµÐ½, HTML Ð½Ðµ Ð½ÑƒÐ¶ÐµÐ½.
            if transport == "rss" and group_saved:
                break
        manifest["sources"][sid] = {"state": "ok" if saved else "failed",
                                    "files": saved, "fetches": fetches,
                                    "detail": "; ".join(errors)[:600]}
        (ok if saved else failed).append(sid)
        time.sleep(PAUSE)

    manifest["_summary"] = {"ok": sorted(ok), "failed": sorted(failed),
                            "incomplete": sorted(incomplete)}
    _persist_manifest(raw, manifest, only=only)

    # ÐžÐ±Ð½Ð¾Ð²Ð¸Ñ‚ÑŒ runs.sources_ok/failed (Ð¿Ð¾Ð»Ð½Ñ‹Ð¹ Ð¿Ñ€Ð¾Ð³Ð¾Ð½, Ð½Ðµ Ñ‚Ð¾Ñ‡ÐµÑ‡Ð½Ñ‹Ð¹ --only).
    if newsdb is not None and not only:
        try:
            conn = newsdb.connect(str(root))
            try:
                newsdb.upsert_run(conn, run_date, started=newsdb.now_iso(),
                                  sources_ok=",".join(sorted(ok)),
                                  sources_failed=",".join(sorted(failed + incomplete)))
            finally:
                newsdb.close(conn)
        except Exception as e:  # Ð¾Ð±Ð½Ð¾Ð²Ð»ÐµÐ½Ð¸Ðµ runs Ð½Ðµ Ð´Ð¾Ð»Ð¶Ð½Ð¾ Ñ€Ð¾Ð½ÑÑ‚ÑŒ ÑÐ±Ð¾Ñ€
            print(f"[collect] Ð½Ðµ ÑƒÐ´Ð°Ð»Ð¾ÑÑŒ Ð¾Ð±Ð½Ð¾Ð²Ð¸Ñ‚ÑŒ runs: {e}", file=sys.stderr)

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
    ap = argparse.ArgumentParser(description="Ð•Ð´Ð¸Ð½Ñ‹Ð¹ HTTP-ÑÐ±Ð¾Ñ€ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð² (v2).")
    ap.add_argument("--date", default=date_cls.today().isoformat(), help="Ð”Ð°Ñ‚Ð° YYYY-MM-DD.")
    ap.add_argument("--root", default=".", help="ÐšÐ¾Ñ€ÐµÐ½ÑŒ Ð¿Ñ€Ð¾ÐµÐºÑ‚Ð° News Claude.")
    ap.add_argument("--only", default=None, help="Ð¡Ð¾Ð±Ñ€Ð°Ñ‚ÑŒ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº sid.")
    args = ap.parse_args()
    manifest = collect(args.root, args.date, only=args.only)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    s = manifest.get("_summary", {})
    print(f"[collect] OK={len(s.get('ok', []))} FAILED={len(s.get('failed', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

