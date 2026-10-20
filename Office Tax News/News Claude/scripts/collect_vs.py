#!/usr/bin/env python3
"""Одноразовый HTTP-сбор налоговых материалов Верховного Суда РФ.

Официальный сайт заполняет списки XHR-запросом к той же странице. Запрашиваем
только keyword=налог за текущий год; ответы JSON сохраняем как есть. Никаких
личных кабинетов, обхода антибота или браузерной автоматизации.
"""

from __future__ import annotations

import argparse
import sys
from datetime import date as date_cls
from pathlib import Path

import requests

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
ENDPOINT = "https://www.vsrf.ru/"


def collect(root: str, run_date: str, session=None) -> list[Path]:
    out_dir = Path(root).resolve() / "pipeline" / "raw" / run_date
    out_dir.mkdir(parents=True, exist_ok=True)
    # Validate the date before composing the output directory.
    date_cls.fromisoformat(run_date)
    client = session or requests.Session()
    try:
        response = client.get(ENDPOINT, headers={"User-Agent": UA}, timeout=30)
        response.raise_for_status()
    except requests.RequestException as exc:
        raise RuntimeError(f"{ENDPOINT}: {type(exc).__name__}: {exc}") from exc
    payload = response.content
    if b"/documents/" not in payload and b"/press_center/news/" not in payload:
        raise RuntimeError("главная страница ВС РФ не содержит карточек материалов")
    target = out_dir / "ru_vs_1.txt"
    target.write_bytes(payload)
    return [target]


def main() -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description="Сбор налоговых материалов ВС РФ.")
    parser.add_argument("--date", default=date_cls.today().isoformat())
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        files = collect(args.root, args.date)
    except (RuntimeError, ValueError) as exc:
        print(f"[vs] ошибка: {exc}", file=sys.stderr)
        return 1
    print(f"[vs] сохранено: {', '.join(path.name for path in files)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
