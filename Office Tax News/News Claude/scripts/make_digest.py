#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Шортлист → скелет дайджеста pipeline/digest/{date}_digest.md (идемпотентно). Stdlib + PyYAML."""

import argparse
import json
import os
import sys

try:
    import yaml  # noqa: F401  (для единообразия зависимостей; здесь не критичен)
except ImportError:  # pragma: no cover
    print("Нужен PyYAML. Установка: pip install pyyaml --break-system-packages", file=sys.stderr)
    sys.exit(2)

import newsdb


def load_shortlist(root, date):
    """Прочитать shortlist.json или вернуть None."""
    path = os.path.join(root, "pipeline", "shortlist", f"{date}_shortlist.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_status_line(root, date):
    """Строка со статусом источников из таблицы runs (или заглушка)."""
    conn = newsdb.connect(root)
    try:
        run = newsdb.get_run(conn, date)
        if run is None:
            return "нет данных о прогоне (runs пуст)"
        ok = run["sources_ok"] or "—"
        failed = run["sources_failed"] or "—"
        return (f"OK: {ok} | СБОЙ: {failed} | "
                f"собрано: {run['n_collected']} | шортлист: {run['n_shortlisted']}")
    finally:
        newsdb.close(conn)


def build_markdown(shortlist, fetch_status):
    """Собрать текст дайджеста: шапка + нумерованные блоки с плейсхолдером сути."""
    date = shortlist.get("date", "")
    items = shortlist.get("items", [])
    lines = []
    lines.append(f"# Дайджест налоговых новостей — {date}")
    lines.append("")
    lines.append(f"- Статус источников: {fetch_status}")
    lines.append(f"- Материалов в подборке: {len(items)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    if not items:
        lines.append("_Подходящих материалов не найдено._")
        lines.append("")
        return "\n".join(lines)

    for it in items:
        n = it.get("n")
        title = it.get("title", "").strip()
        source = it.get("source", "")
        published_at = it.get("published_at") or "дата не указана"
        url = it.get("url") or "(нет ссылки)"
        topics = ", ".join(it.get("topics", [])) or "—"
        jurisdictions = ", ".join(it.get("jurisdiction_names", [])) or "—"
        score = it.get("score", "")
        channels = ", ".join(it.get("suggested_channels", [])) or "—"
        ecli = it.get("ecli", "")
        act = it.get("act", "")

        lines.append(f"## {n}. {title}")
        src_line = f"- Источник: {source} | {published_at} | {url}"
        if ecli:
            src_line += f" | {ecli}"
        elif act:
            src_line += f" | акт: {act}"
        lines.append(src_line)
        if it.get("lead"):
            lines.append(
                f"- Тип: Telegram lead ({it.get('channel') or 'канал не указан'}, "
                f"engagement={it.get('engagement', 0)}) — первоисточник ОБЯЗАТЕЛЬНО подтвердить"
            )
        lines.append(f"- Страны: {jurisdictions} | Темы: {topics} | Скоринг: {score}")
        lines.append(f"- Предложенные каналы: {channels}")
        lines.append("- Суть: [ЗАПОЛНИТ CLAUDE: 2–3 предложения строго из источника]")
        lines.append("")

    return "\n".join(lines)


def run(date, root):
    """Сформировать и записать дайджест за дату. Возвращает путь или None."""
    shortlist = load_shortlist(root, date)
    if shortlist is None:
        print(f"[digest] нет шортлиста за {date} — нечего собирать", file=sys.stderr)
        return None
    fetch_status = fetch_status_line(root, date)
    md = build_markdown(shortlist, fetch_status)

    out_dir = os.path.join(root, "pipeline", "digest")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{date}_digest.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    n = len(shortlist.get("items", []))
    print(f"[digest] {n} блоков → {out_path}")
    return out_path


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="Сборка скелета дайджеста из шортлиста.")
    ap.add_argument("--date", required=True, help="Дата прогона YYYY-MM-DD.")
    ap.add_argument("--root", default=".", help="Корень проекта.")
    args = ap.parse_args()
    run(args.date, args.root)


if __name__ == "__main__":
    main()

