#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ð ÑƒÑ‡Ð½Ñ‹Ðµ Ð¿Ð¾Ð¼ÐµÑ‚ÐºÐ¸: assign / published / skip Ð¿Ð¾ Ð½Ð¾Ð¼ÐµÑ€Ñƒ Ð² ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ðµ. Stdlib + PyYAML."""

import argparse
import json
import os
import sys

try:
    import yaml  # noqa: F401
except ImportError:  # pragma: no cover
    print("ÐÑƒÐ¶ÐµÐ½ PyYAML. Ð£ÑÑ‚Ð°Ð½Ð¾Ð²ÐºÐ°: pip install pyyaml --break-system-packages", file=sys.stderr)
    sys.exit(2)

import newsdb


def load_shortlist(root, date):
    """ÐŸÑ€Ð¾Ñ‡Ð¸Ñ‚Ð°Ñ‚ÑŒ shortlist.json â†’ dict (Ð¸Ð»Ð¸ None)."""
    path = os.path.join(root, "pipeline", "shortlist", f"{date}_shortlist.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_n_to_item(shortlist):
    """ÐžÑ‚Ð¾Ð±Ñ€Ð°Ð¶ÐµÐ½Ð¸Ðµ Ð½Ð¾Ð¼ÐµÑ€_Ð²_ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ðµ(n) â†’ item_id."""
    mapping = {}
    for it in shortlist.get("items", []):
        mapping[int(it["n"])] = it.get("item_id")
    return mapping


def parse_assign_map(spec):
    """Ð Ð°Ð·Ð¾Ð±Ñ€Ð°Ñ‚ÑŒ ÑÑ‚Ñ€Ð¾ÐºÑƒ ÐºÐ°Ñ€Ñ‚Ñ‹ Ð½Ð°Ð·Ð½Ð°Ñ‡ÐµÐ½Ð¸Ð¹ '3:telegram_channel,vk;5:vk' â†’ {n: [channels]}."""
    result = {}
    for chunk in spec.split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        if ":" not in chunk:
            raise ValueError(f"Ð½ÐµÐ²ÐµÑ€Ð½Ñ‹Ð¹ Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚ ÑÐµÐ³Ð¼ÐµÐ½Ñ‚Ð°: {chunk!r} (Ð¾Ð¶Ð¸Ð´Ð°Ð»Ð¾ÑÑŒ N:ÐºÐ°Ð½Ð°Ð»,ÐºÐ°Ð½Ð°Ð»)")
        n_str, chans = chunk.split(":", 1)
        n = int(n_str.strip())
        channels = [c.strip() for c in chans.split(",") if c.strip()]
        result[n] = channels
    return result


def cmd_assign(args):
    """assign: Ð¿Ñ€Ð¾ÑÑ‚Ð°Ð²Ð¸Ñ‚ÑŒ status=assigned Ð¸ Ð·Ð°Ð¿Ð¸ÑÐ°Ñ‚ÑŒ ÐºÐ°Ð½Ð°Ð»Ñ‹ Ð´Ð»Ñ ÑƒÐºÐ°Ð·Ð°Ð½Ð½Ñ‹Ñ… n."""
    shortlist = load_shortlist(args.root, args.date)
    if shortlist is None:
        print(f"[mark] Ð½ÐµÑ‚ ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ð° Ð·Ð° {args.date}", file=sys.stderr)
        return 1
    n_to_item = build_n_to_item(shortlist)
    try:
        mapping = parse_assign_map(args.map)
    except ValueError as e:
        print(f"[mark] Ð¾ÑˆÐ¸Ð±ÐºÐ° Ñ€Ð°Ð·Ð±Ð¾Ñ€Ð° --map: {e}", file=sys.stderr)
        return 2
    conn = newsdb.connect(args.root)
    try:
        done = 0
        for n, channels in mapping.items():
            item_id = n_to_item.get(n)
            if item_id is None:
                print(f"[mark] assign: #{n} Ð½ÐµÑ‚ Ð² ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ðµ â€” Ð¿Ñ€Ð¾Ð¿ÑƒÑÐº")
                continue
            newsdb.set_status(conn, item_id, "assigned", channels=",".join(channels))
            print(f"[mark] assign #{n} (item={item_id}) â†’ {', '.join(channels)}")
            done += 1
        print(f"[mark] Ð½Ð°Ð·Ð½Ð°Ñ‡ÐµÐ½Ð¾: {done}")
    finally:
        newsdb.close(conn)
    return 0


def cmd_published(args):
    """published: Ð·Ð°Ñ„Ð¸ÐºÑÐ¸Ñ€Ð¾Ð²Ð°Ñ‚ÑŒ Ð¿ÑƒÐ±Ð»Ð¸ÐºÐ°Ñ†Ð¸ÑŽ ÑÐ»ÐµÐ¼ÐµÐ½Ñ‚Ð° #N Ð² ÐºÐ°Ð½Ð°Ð», ÑÑ‚Ð°Ñ‚ÑƒÑ=published."""
    shortlist = load_shortlist(args.root, args.date)
    if shortlist is None:
        print(f"[mark] Ð½ÐµÑ‚ ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ð° Ð·Ð° {args.date}", file=sys.stderr)
        return 1
    n_to_item = build_n_to_item(shortlist)
    item_id = n_to_item.get(int(args.item))
    if item_id is None:
        print(f"[mark] published: #{args.item} Ð½ÐµÑ‚ Ð² ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ðµ", file=sys.stderr)
        return 1
    conn = newsdb.connect(args.root)
    try:
        newsdb.add_published(conn, item_id, args.channel, post_id=args.post_id or "",
                             post_url=args.post_url or "")
        newsdb.set_status(conn, item_id, "published")
    finally:
        newsdb.close(conn)
    print(f"[mark] published #{args.item} (item={item_id}) ÐºÐ°Ð½Ð°Ð»={args.channel} "
          f"post_id={args.post_id or '-'} post_url={args.post_url or '-'}")
    return 0


def cmd_skip(args):
    """skip: Ð¿Ð¾Ð¼ÐµÑ‚Ð¸Ñ‚ÑŒ ÑÐ»ÐµÐ¼ÐµÐ½Ñ‚ #N ÐºÐ°Ðº skipped."""
    shortlist = load_shortlist(args.root, args.date)
    if shortlist is None:
        print(f"[mark] Ð½ÐµÑ‚ ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ð° Ð·Ð° {args.date}", file=sys.stderr)
        return 1
    n_to_item = build_n_to_item(shortlist)
    item_id = n_to_item.get(int(args.item))
    if item_id is None:
        print(f"[mark] skip: #{args.item} Ð½ÐµÑ‚ Ð² ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ðµ", file=sys.stderr)
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
    ap = argparse.ArgumentParser(description="Ð ÑƒÑ‡Ð½Ñ‹Ðµ Ð¿Ð¾Ð¼ÐµÑ‚ÐºÐ¸ ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ð°.")
    ap.add_argument("--root", default=".", help="ÐšÐ¾Ñ€ÐµÐ½ÑŒ Ð¿Ñ€Ð¾ÐµÐºÑ‚Ð°.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_assign = sub.add_parser("assign", help="ÐÐ°Ð·Ð½Ð°Ñ‡Ð¸Ñ‚ÑŒ ÐºÐ°Ð½Ð°Ð»Ñ‹: --map '3:telegram_channel,vk;5:vk'")
    p_assign.add_argument("--date", required=True)
    p_assign.add_argument("--map", required=True)
    p_assign.set_defaults(func=cmd_assign)

    p_pub = sub.add_parser("published", help="ÐžÑ‚Ð¼ÐµÑ‚Ð¸Ñ‚ÑŒ Ð¿ÑƒÐ±Ð»Ð¸ÐºÐ°Ñ†Ð¸ÑŽ ÑÐ»ÐµÐ¼ÐµÐ½Ñ‚Ð° Ð² ÐºÐ°Ð½Ð°Ð».")
    p_pub.add_argument("--date", required=True)
    p_pub.add_argument("--item", required=True, help="ÐÐ¾Ð¼ÐµÑ€ N Ð² ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ðµ.")
    p_pub.add_argument("--channel", required=True)
    p_pub.add_argument("--post-id", dest="post_id", default="")
    p_pub.add_argument("--post-url", dest="post_url", default="")
    p_pub.set_defaults(func=cmd_published)

    p_skip = sub.add_parser("skip", help="ÐŸÐ¾Ð¼ÐµÑ‚Ð¸Ñ‚ÑŒ ÑÐ»ÐµÐ¼ÐµÐ½Ñ‚ ÐºÐ°Ðº skipped.")
    p_skip.add_argument("--date", required=True)
    p_skip.add_argument("--item", required=True, help="ÐÐ¾Ð¼ÐµÑ€ N Ð² ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ðµ.")
    p_skip.set_defaults(func=cmd_skip)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()

