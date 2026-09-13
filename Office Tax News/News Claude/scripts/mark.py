#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ручные пометки: assign / published / skip по номеру в шортлисте. Stdlib + PyYAML."""

import argparse
import json
import os
import sys

try:
    import yaml  # noqa: F401
except ImportError:  # pragma: no cover
    print("Нужен PyYAML. Установка: pip install pyyaml --break-system-packages", file=sys.stderr)
    sys.exit(2)

import newsdb


def load_shortlist(root, date):
    """Прочитать shortlist.json → dict (или None)."""
    path = os.path.join(root, "pipeline", "shortlist", f"{date}_shortlist.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_n_to_item(shortlist):
    """Отображение номер_в_шортлисте(n) → item_id."""
    mapping = {}
    for it in shortlist.get("items", []):
        mapping[int(it["n"])] = it.get("item_id")
    return mapping


def parse_assign_map(spec):
    """Разобрать строку карты назначений '3:telegram_channel,vk;5:vk' → {n: [channels]}."""
    result = {}
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(f"неверный формат сегмента: {chunk!r} (ожидалось N:канал,канал)")
        n_str, chans = chunk.split(":", 1)
        n = int(n_str.strip())
        channels = [c.strip() for c in chans.split(",") if c.strip()]
        result[n] = channels
    return result


def cmd_assign(args):
    """assign: проставить status=assigned и записать каналы для указанных n."""
    shortlist = load_shortlist(args.root, args.date)
    if shortlist is None:
        print(f"[mark] нет шортлиста за {args.date}", file=sys.stderr)
        return 1
    n_to_item = build_n_to_item(shortlist)
    try:
        mapping = parse_assign_map(args.map)
    except ValueError as e:
        print(f"[mark] ошибка разбора --map: {e}", file=sys.stderr)
        return 2
    conn = newsdb.connect(args.root)
    try:
        done = 0
        for n, channels in mapping.items():
            item_id = n_to_item.get(n)
            if item_id is None:
                print(f"[mark] assign: #{n} нет в шортлисте — пропуск")
                continue
            newsdb.set_status(conn, item_id, "assigned", channels=",".join(channels))
            print(f"[mark] assign #{n} (item={item_id}) → {', '.join(channels)}")
            done += 1
        print(f"[mark] назначено: {done}")
    finally:
        newsdb.close(conn)
    return 0


def cmd_published(args):
    """published: зафиксировать публикацию элемента #N в канал, статус=published."""
    shortlist = load_shortlist(args.root, args.date)
    if shortlist is None:
        print(f"[mark] нет шортлиста за {args.date}", file=sys.stderr)
        return 1
    n_to_item = build_n_to_item(shortlist)
    item_id = n_to_item.get(int(args.item))
    if item_id is None:
        print(f"[mark] published: #{args.item} нет в шортлисте", file=sys.stderr)
        return 1
    conn = newsdb.connect(args.root)
    try:
        newsdb.add_published(conn, item_id, args.channel, post_id=args.post_id or "",
                             post_url=args.post_url or "")
        newsdb.set_status(conn, item_id, "published")
    finally:
        newsdb.close(conn)
    print(f"[mark] published #{args.item} (item={item_id}) канал={args.channel} "
          f"post_id={args.post_id or '-'} post_url={args.post_url or '-'}")
    return 0


def cmd_skip(args):
    """skip: пометить элемент #N как skipped."""
    shortlist = load_shortlist(args.root, args.date)
    if shortlist is None:
        print(f"[mark] нет шортлиста за {args.date}", file=sys.stderr)
        return 1
    n_to_item = build_n_to_item(shortlist)
    item_id = n_to_item.get(int(args.item))
    if item_id is None:
        print(f"[mark] skip: #{args.item} нет в шортлисте", file=sys.stderr)
        return 1
    conn = newsdb.connect(args.root)
    try:
        newsdb.set_status(conn, item_id, "skipped")
    finally:
        newsdb.close(conn)
    print(f"[mark] skip #{args.item} (item={item_id})")
    return 0


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="Ручные пометки шортлиста.")
    ap.add_argument("--root", default=".", help="Корень проекта.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_assign = sub.add_parser("assign", help="Назначить каналы: --map '3:telegram_channel,vk;5:vk'")
    p_assign.add_argument("--date", required=True)
    p_assign.add_argument("--map", required=True)
    p_assign.set_defaults(func=cmd_assign)

    p_pub = sub.add_parser("published", help="Отметить публикацию элемента в канал.")
    p_pub.add_argument("--date", required=True)
    p_pub.add_argument("--item", required=True, help="Номер N в шортлисте.")
    p_pub.add_argument("--channel", required=True)
    p_pub.add_argument("--post-id", dest="post_id", default="")
    p_pub.add_argument("--post-url", dest="post_url", default="")
    p_pub.set_defaults(func=cmd_published)

    p_skip = sub.add_parser("skip", help="Пометить элемент как skipped.")
    p_skip.add_argument("--date", required=True)
    p_skip.add_argument("--item", required=True, help="Номер N в шортлисте.")
    p_skip.set_defaults(func=cmd_skip)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

