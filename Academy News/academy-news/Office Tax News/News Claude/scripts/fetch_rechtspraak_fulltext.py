#!/usr/bin/env python3
"""Скачать полные тексты Rechtspraak только для позиций текущего shortlist."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import tempfile
import time
from datetime import date as date_cls
from pathlib import Path
from xml.etree import ElementTree as ET

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
CONTENT_URL = "https://data.rechtspraak.nl/uitspraken/content"


def safe_name(ecli: str) -> str:
    return re.sub(r"[^A-Za-z0-9._-]+", "_", ecli).strip("_")


def xml_plain_text(payload: bytes) -> str:
    """Читаемый текст XML без потери исходного raw-файла."""
    try:
        root = ET.fromstring(payload)
    except ET.ParseError:
        return ""
    parts = []
    for value in root.itertext():
        value = re.sub(r"\s+", " ", value or "").strip()
        if value:
            parts.append(value)
    return "\n".join(parts)


def shortlist_eclis(root: Path, run_date: str) -> list[str]:
    path = root / "pipeline" / "shortlist" / f"{run_date}_shortlist.json"
    payload = json.loads(path.read_text(encoding="utf-8"))
    return list(dict.fromkeys(
        item.get("ecli", "").strip()
        for item in payload.get("items", [])
        if item.get("source") == "nl_rechtspraak" and item.get("ecli", "").strip()
    ))


def _atomic_manifest(path: Path, manifest: dict) -> None:
    fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    os.close(fd)
    tmp = Path(tmp_name)
    try:
        tmp.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


def fetch(root: str, run_date: str, *, only_ecli: str = "", eclis=None,
          session=None, pause: float = 2.0) -> dict:
    project = Path(root).resolve()
    if eclis is not None:
        requested = list(dict.fromkeys(str(value).strip() for value in eclis if str(value).strip()))
    else:
        requested = [only_ecli] if only_ecli else shortlist_eclis(project, run_date)
    out_dir = project / "pipeline" / "raw" / run_date / "rechtspraak_fulltext"
    out_dir.mkdir(parents=True, exist_ok=True)
    client = session or requests.Session()
    headers = {"User-Agent": UA, "Accept": "application/xml,text/xml;q=0.9,*/*;q=0.1"}
    manifest_path = out_dir / "manifest.json"
    existing = {}
    if manifest_path.exists():
        try:
            previous = json.loads(manifest_path.read_text(encoding="utf-8"))
            if previous.get("date") == run_date:
                existing = {
                    item.get("ecli"): item for item in previous.get("items", [])
                    if item.get("ecli")
                }
        except (OSError, ValueError, json.JSONDecodeError):
            existing = {}
    for index, ecli in enumerate(requested):
        target = out_dir / f"{safe_name(ecli)}.xml"
        text_target = target.with_suffix(".txt")
        if target.exists() and target.stat().st_size > 100 and text_target.exists():
            existing[ecli] = {
                "ecli": ecli,
                "state": "existing",
                "file": target.name,
                "text_file": text_target.name,
                "bytes": target.stat().st_size,
            }
            continue
        try:
            response = client.get(
                CONTENT_URL,
                params={"id": ecli, "return": "DOC"},
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            body = response.content
            if not body.strip():
                raise ValueError("пустой ответ")
            plain = xml_plain_text(body)
            if not plain:
                raise ValueError("ответ не является читаемым XML")
            target.write_bytes(body)
            text_target.write_text(
                f"ECLI: {ecli}\nИсточник: {response.url}\n\n{plain}\n",
                encoding="utf-8",
            )
            existing[ecli] = {
                "ecli": ecli,
                "state": "ok",
                "file": target.name,
                "text_file": text_target.name,
                "bytes": len(body),
            }
        except (requests.RequestException, ValueError, OSError) as exc:
            existing[ecli] = {
                "ecli": ecli,
                "state": "failed",
                "error": f"{type(exc).__name__}: {exc}",
            }
        if index + 1 < len(requested) and pause:
            time.sleep(pause)
    manifest = {"date": run_date, "items": [existing[key] for key in sorted(existing)]}
    _atomic_manifest(manifest_path, manifest)
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser(description="Полные тексты shortlist Rechtspraak.")
    parser.add_argument("--date", default=date_cls.today().isoformat())
    parser.add_argument("--root", default=".")
    parser.add_argument("--ecli", default="", help="Скачать только один ECLI.")
    args = parser.parse_args()
    try:
        manifest = fetch(args.root, args.date, only_ecli=args.ecli)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"[rechtspraak-full] ошибка: {exc}", file=sys.stderr)
        return 1
    ok = sum(item["state"] in {"ok", "existing"} for item in manifest["items"])
    failed = sum(item["state"] == "failed" for item in manifest["items"])
    print(f"[rechtspraak-full] OK={ok} FAILED={failed}")
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
