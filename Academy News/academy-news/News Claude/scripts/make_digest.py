#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ð¨Ð¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚ â†’ ÑÐºÐµÐ»ÐµÑ‚ Ð´Ð°Ð¹Ð´Ð¶ÐµÑÑ‚Ð° pipeline/digest/{date}_digest.md (Ð¸Ð´ÐµÐ¼Ð¿Ð¾Ñ‚ÐµÐ½Ñ‚Ð½Ð¾). Stdlib + PyYAML."""

import argparse
import json
import os
import sys

try:
    import yaml  # noqa: F401  (Ð´Ð»Ñ ÐµÐ´Ð¸Ð½Ð¾Ð¾Ð±Ñ€Ð°Ð·Ð¸Ñ Ð·Ð°Ð²Ð¸ÑÐ¸Ð¼Ð¾ÑÑ‚ÐµÐ¹; Ð·Ð´ÐµÑÑŒ Ð½Ðµ ÐºÑ€Ð¸Ñ‚Ð¸Ñ‡ÐµÐ½)
except ImportError:  # pragma: no cover
    print("ÐÑƒÐ¶ÐµÐ½ PyYAML. Ð£ÑÑ‚Ð°Ð½Ð¾Ð²ÐºÐ°: pip install pyyaml --break-system-packages", file=sys.stderr)
    sys.exit(2)

import newsdb


def load_shortlist(root, date):
    """ÐŸÑ€Ð¾Ñ‡Ð¸Ñ‚Ð°Ñ‚ÑŒ shortlist.json Ð¸Ð»Ð¸ Ð²ÐµÑ€Ð½ÑƒÑ‚ÑŒ None."""
    path = os.path.join(root, "pipeline", "shortlist", f"{date}_shortlist.json")
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def fetch_status_line(root, date):
    """Ð¡Ñ‚Ñ€Ð¾ÐºÐ° ÑÐ¾ ÑÑ‚Ð°Ñ‚ÑƒÑÐ¾Ð¼ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð² Ð¸Ð· Ñ‚Ð°Ð±Ð»Ð¸Ñ†Ñ‹ runs (Ð¸Ð»Ð¸ Ð·Ð°Ð³Ð»ÑƒÑˆÐºÐ°)."""
    conn = newsdb.connect(root)
    try:
        run = newsdb.get_run(conn, date)
        if run is None:
            return "Ð½ÐµÑ‚ Ð´Ð°Ð½Ð½Ñ‹Ñ… Ð¾ Ð¿Ñ€Ð¾Ð³Ð¾Ð½Ðµ (runs Ð¿ÑƒÑÑ‚)"
        ok = run["sources_ok"] or "â€”"
        failed = run["sources_failed"] or "â€”"
        return (f"OK: {ok} | Ð¡Ð‘ÐžÐ™: {failed} | "
                f"ÑÐ¾Ð±Ñ€Ð°Ð½Ð¾: {run['n_collected']} | ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚: {run['n_shortlisted']}")
    finally:
        newsdb.close(conn)


def build_markdown(shortlist, fetch_status):
    """Ð¡Ð¾Ð±Ñ€Ð°Ñ‚ÑŒ Ñ‚ÐµÐºÑÑ‚ Ð´Ð°Ð¹Ð´Ð¶ÐµÑÑ‚Ð°: ÑˆÐ°Ð¿ÐºÐ° + Ð½ÑƒÐ¼ÐµÑ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ðµ Ð±Ð»Ð¾ÐºÐ¸ Ñ Ð¿Ð»ÐµÐ¹ÑÑ…Ð¾Ð»Ð´ÐµÑ€Ð¾Ð¼ ÑÑƒÑ‚Ð¸."""
    date = shortlist.get("date", "")
    items = shortlist.get("items", [])
    lines = []
    lines.append(f"# Ð”Ð°Ð¹Ð´Ð¶ÐµÑÑ‚ Ð½Ð°Ð»Ð¾Ð³Ð¾Ð²Ñ‹Ñ… Ð½Ð¾Ð²Ð¾ÑÑ‚ÐµÐ¹ â€” {date}")
    lines.append("")
    lines.append(f"- Ð¡Ñ‚Ð°Ñ‚ÑƒÑ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð²: {fetch_status}")
    lines.append(f"- ÐœÐ°Ñ‚ÐµÑ€Ð¸Ð°Ð»Ð¾Ð² Ð² Ð¿Ð¾Ð´Ð±Ð¾Ñ€ÐºÐµ: {len(items)}")
    lines.append("")
    lines.append("---")
    lines.append("")

    if not items:
        lines.append("_ÐŸÐ¾Ð´Ñ…Ð¾Ð´ÑÑ‰Ð¸Ñ… Ð¼Ð°Ñ‚ÐµÑ€Ð¸Ð°Ð»Ð¾Ð² Ð½Ðµ Ð½Ð°Ð¹Ð´ÐµÐ½Ð¾._")
        lines.append("")
        return "\n".join(lines)

    for it in items:
        n = it.get("n")
        title = it.get("title", "").strip()
        source = it.get("source", "")
        published_at = it.get("published_at") or "Ð´Ð°Ñ‚Ð° Ð½Ðµ ÑƒÐºÐ°Ð·Ð°Ð½Ð°"
        url = it.get("url") or "(Ð½ÐµÑ‚ ÑÑÑ‹Ð»ÐºÐ¸)"
        topics = ", ".join(it.get("topics", [])) or "â€”"
        jurisdictions = ", ".join(it.get("jurisdiction_names", [])) or "â€”"
        score = it.get("score", "")
        channels = ", ".join(it.get("suggested_channels", [])) or "â€”"
        ecli = it.get("ecli", "")
        act = it.get("act", "")

        lines.append(f"## {n}. {title}")
        src_line = f"- Ð˜ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº: {source} | {published_at} | {url}"
        if ecli:
            src_line += f" | {ecli}"
        elif act:
            src_line += f" | Ð°ÐºÑ‚: {act}"
        lines.append(src_line)
        if it.get("lead"):
            lines.append(
                f"- Ð¢Ð¸Ð¿: Telegram lead ({it.get('channel') or 'ÐºÐ°Ð½Ð°Ð» Ð½Ðµ ÑƒÐºÐ°Ð·Ð°Ð½'}, "
                f"engagement={it.get('engagement', 0)}) â€” Ð¿ÐµÑ€Ð²Ð¾Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº ÐžÐ‘Ð¯Ð—ÐÐ¢Ð•Ð›Ð¬ÐÐž Ð¿Ð¾Ð´Ñ‚Ð²ÐµÑ€Ð´Ð¸Ñ‚ÑŒ"
            )
        lines.append(f"- Ð¡Ñ‚Ñ€Ð°Ð½Ñ‹: {jurisdictions} | Ð¢ÐµÐ¼Ñ‹: {topics} | Ð¡ÐºÐ¾Ñ€Ð¸Ð½Ð³: {score}")
        lines.append(f"- ÐŸÑ€ÐµÐ´Ð»Ð¾Ð¶ÐµÐ½Ð½Ñ‹Ðµ ÐºÐ°Ð½Ð°Ð»Ñ‹: {channels}")
        lines.append("- Ð¡ÑƒÑ‚ÑŒ: [Ð—ÐÐŸÐžÐ›ÐÐ˜Ð¢ CLAUDE: 2â€“3 Ð¿Ñ€ÐµÐ´Ð»Ð¾Ð¶ÐµÐ½Ð¸Ñ ÑÑ‚Ñ€Ð¾Ð³Ð¾ Ð¸Ð· Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ°]")
        lines.append("")

    return "\n".join(lines)


def run(date, root):
    """Ð¡Ñ„Ð¾Ñ€Ð¼Ð¸Ñ€Ð¾Ð²Ð°Ñ‚ÑŒ Ð¸ Ð·Ð°Ð¿Ð¸ÑÐ°Ñ‚ÑŒ Ð´Ð°Ð¹Ð´Ð¶ÐµÑÑ‚ Ð·Ð° Ð´Ð°Ñ‚Ñƒ. Ð’Ð¾Ð·Ð²Ñ€Ð°Ñ‰Ð°ÐµÑ‚ Ð¿ÑƒÑ‚ÑŒ Ð¸Ð»Ð¸ None."""
    shortlist = load_shortlist(root, date)
    if shortlist is None:
        print(f"[digest] Ð½ÐµÑ‚ ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ð° Ð·Ð° {date} â€” Ð½ÐµÑ‡ÐµÐ³Ð¾ ÑÐ¾Ð±Ð¸Ñ€Ð°Ñ‚ÑŒ", file=sys.stderr)
        return None
    fetch_status = fetch_status_line(root, date)
    md = build_markdown(shortlist, fetch_status)

    out_dir = os.path.join(root, "pipeline", "digest")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{date}_digest.md")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(md)
    n = len(shortlist.get("items", []))
    print(f"[digest] {n} Ð±Ð»Ð¾ÐºÐ¾Ð² â†’ {out_path}")
    return out_path


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="Ð¡Ð±Ð¾Ñ€ÐºÐ° ÑÐºÐµÐ»ÐµÑ‚Ð° Ð´Ð°Ð¹Ð´Ð¶ÐµÑÑ‚Ð° Ð¸Ð· ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ð°.")
    ap.add_argument("--date", required=True, help="Ð”Ð°Ñ‚Ð° Ð¿Ñ€Ð¾Ð³Ð¾Ð½Ð° YYYY-MM-DD.")
    ap.add_argument("--root", default=".", help="ÐšÐ¾Ñ€ÐµÐ½ÑŒ Ð¿Ñ€Ð¾ÐµÐºÑ‚Ð°.")
    args = ap.parse_args()
    run(args.date, args.root)


if __name__ == "__main__":
    main()

