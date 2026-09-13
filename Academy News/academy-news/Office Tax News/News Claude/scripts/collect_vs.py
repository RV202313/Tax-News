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
ENDPOINTS = (
    ("https://vsrf.ru/documents/reviews/", None),
    ("https://vsrf.ru/press_center/news/", "налог"),
)


def collect(root: str, run_date: str, session=None) -> list[Path]:
    out_dir = Path(root).resolve() / "pipeline" / "raw" / run_date
    out_dir.mkdir(parents=True, exist_ok=True)
    year = date_cls.fromisoformat(run_date).year
    client = session or requests.Session()
    headers = {"User-Agent": UA, "X-Requested-With": "XMLHttpRequest"}
    saved = []
    errors = []
    for number, (endpoint, keyword) in enumerate(ENDPOINTS, start=1):
        try:
            params = {"init": "y", "year": str(year)}
            if keyword:
                params["keyword"] = keyword
            response = client.get(
                endpoint,
                params=params,
                headers=headers,
                timeout=30,
            )
            response.raise_for_status()
            payload = response.content
            # Проверяем JSON до записи, но сохраняем исходные байты ответа.
            parsed = response.json()
            if not isinstance(parsed, dict) or "list" not in parsed:
                raise ValueError("ответ не похож на XHR-листинг ВС РФ")
            target = out_dir / f"ru_vs_{number}.txt"
            target.write_bytes(payload)
            saved.append(target)
        except (requests.RequestException, ValueError) as exc:
            errors.append(f"{endpoint}: {type(exc).__name__}: {exc}")
    for message in errors:
        print(f"[vs] {message}", file=sys.stderr)
    if not saved:
        raise RuntimeError("ни один официальный endpoint ВС РФ не собран")
    return saved


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
