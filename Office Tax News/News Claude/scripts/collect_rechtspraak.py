#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Прямой HTTP-сбор списка налоговых решений судов NL (rechtspraak Open Data).

Заменяет web_fetch для источника nl_rechtspraak. Серверный subject-фильтр
(bestuursrecht_belastingrecht) РАБОТАЕТ при %23-кодировании символа '#', которое
requests выполняет автоматически, если URI передан через `params` (а не вклеен
в строку URL руками). web_fetch терял '#…' как фрагмент URL и отдавал 0
результатов — отсюда прежний ошибочный вывод «subject не фильтрует».

Пишет сырой Atom XML КАК ЕСТЬ в:
  pipeline/raw/{date}/nl_rechtspraak_1.txt   (сегодня)
  pipeline/raw/{date}/nl_rechtspraak_2.txt   (вчера)
Существующий parse_rechtspraak_atom разбирает это без изменений.

Рецепт проверен живьём 2026-07-17 (ДОРОЖНАЯ_КАРТА_v2 §5.1):
  GET https://data.rechtspraak.nl/uitspraken/zoeken
      ?subject=http%3A%2F%2Fpsi.rechtspraak.nl%2Frechtsgebied%23bestuursrecht_belastingrecht
      &date=YYYY-MM-DD&type=Uitspraak&return=DOC&max=200
Правила вежливости API: запросы последовательно, с паузой; без параллельных.

Использование:
  python3 scripts/collect_rechtspraak.py --date 2026-07-17 [--root .]
Коды возврата: 0 — оба дня собраны; 1 — часть дней в сбое (помечены), прогон не
падает; 2 — некорректные аргументы/нет requests.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

import http_support

try:
    import requests
except ImportError:  # pragma: no cover
    print("Нужен requests. Установка: pip install requests --break-system-packages",
          file=sys.stderr)
    sys.exit(2)

ZOEKEN_URL = "https://data.rechtspraak.nl/uitspraken/zoeken"
# URI области права «bestuursrecht → belastingrecht». '#' закодируется как %23
# автоматически, Ñ‚.к. значение уходит через params, не через сырую строку URL.
SUBJECT_BELASTINGRECHT = (
    "http://psi.rechtspraak.nl/rechtsgebied#bestuursrecht_belastingrecht"
)
USER_AGENT = "AcademyBEPS-NewsPipeline/1.0 (rechtspraak Open Data collector)"
PAUSE_SECONDS = 5   # пауза между двумя запросами (вежливость к API)
TIMEOUT = 30


def fetch_day(session, day):
    """Один запрос zoeken за конкретный день. Возвращает (text, status_code, error)."""
    params = {
        "subject": SUBJECT_BELASTINGRECHT,  # requests закодирует '#' → %23
        "date": day,                         # один день за вызов (окно 48ч = 2 вызова)
        "type": "Uitspraak",
        "return": "DOC",
        "max": "200",
    }
    try:
        r = session.get(ZOEKEN_URL, params=params, timeout=TIMEOUT)
        return r.text, r.status_code, None
    except requests.RequestException as e:  # сеть/таймаут — не роняем прогон
        return "", None, str(e)


def run(run_date, root):
    """Собрать список за сегодня и вчера. Возвращает код возврата процесса."""
    try:
        rd = datetime.strptime(run_date, "%Y-%m-%d").date()
    except ValueError:
        print(f"[rechtspraak] некорректная дата: {run_date!r} (ожидается YYYY-MM-DD)",
              file=sys.stderr)
        return 2
    yesterday = rd - timedelta(days=1)

    raw_dir = os.path.join(root, "pipeline", "raw", run_date)
    os.makedirs(raw_dir, exist_ok=True)

    session = http_support.new_session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.1",
    })

    plan = [
        (rd.isoformat(), "nl_rechtspraak_1.txt"),        # сегодня
        (yesterday.isoformat(), "nl_rechtspraak_2.txt"),  # вчера
    ]

    rc = 0
    for i, (day, fname) in enumerate(plan):
        if i:
            time.sleep(PAUSE_SECONDS)
        text, status, error = fetch_day(session, day)
        out_path = os.path.join(raw_dir, fname)
        if error is not None or status != 200:
            # Источник может сбоить — помечаем файл и продолжаем (ошибка одного
            # дня не валит весь прогон, как и требует PROCESS.md).
            note = error or f"HTTP {status}"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(f"[collect_rechtspraak] сбой за {day}: {note}\n")
            print(f"[rechtspraak] {day}: СБОЙ ({note}) → помечено, продолжаю",
                  file=sys.stderr)
            rc = 1
            continue
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        # Грубая оценка числа найденных решений для лога (без разбора контента).
        n_entries = text.count("<entry")
        print(f"[rechtspraak] {day}: HTTP 200, ~{n_entries} entries → {out_path}")
    return rc


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(
        description="Прямой HTTP-сбор списка rechtspraak (belastingrecht).")
    ap.add_argument("--date", required=True, help="Дата прогона YYYY-MM-DD (сегодня).")
    ap.add_argument("--root", default=".", help="Корень проекта News Claude.")
    args = ap.parse_args()
    sys.exit(run(args.date, args.root))


if __name__ == "__main__":
    main()
