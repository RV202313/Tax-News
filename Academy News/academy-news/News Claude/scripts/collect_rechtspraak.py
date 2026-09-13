#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÐŸÑ€ÑÐ¼Ð¾Ð¹ HTTP-ÑÐ±Ð¾Ñ€ ÑÐ¿Ð¸ÑÐºÐ° Ð½Ð°Ð»Ð¾Ð³Ð¾Ð²Ñ‹Ñ… Ñ€ÐµÑˆÐµÐ½Ð¸Ð¹ ÑÑƒÐ´Ð¾Ð² NL (rechtspraak Open Data).

Ð—Ð°Ð¼ÐµÐ½ÑÐµÑ‚ web_fetch Ð´Ð»Ñ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ° nl_rechtspraak. Ð¡ÐµÑ€Ð²ÐµÑ€Ð½Ñ‹Ð¹ subject-Ñ„Ð¸Ð»ÑŒÑ‚Ñ€
(bestuursrecht_belastingrecht) Ð ÐÐ‘ÐžÐ¢ÐÐ•Ð¢ Ð¿Ñ€Ð¸ %23-ÐºÐ¾Ð´Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð¸Ð¸ ÑÐ¸Ð¼Ð²Ð¾Ð»Ð° '#', ÐºÐ¾Ñ‚Ð¾Ñ€Ð¾Ðµ
requests Ð²Ñ‹Ð¿Ð¾Ð»Ð½ÑÐµÑ‚ Ð°Ð²Ñ‚Ð¾Ð¼Ð°Ñ‚Ð¸Ñ‡ÐµÑÐºÐ¸, ÐµÑÐ»Ð¸ URI Ð¿ÐµÑ€ÐµÐ´Ð°Ð½ Ñ‡ÐµÑ€ÐµÐ· `params` (Ð° Ð½Ðµ Ð²ÐºÐ»ÐµÐµÐ½
Ð² ÑÑ‚Ñ€Ð¾ÐºÑƒ URL Ñ€ÑƒÐºÐ°Ð¼Ð¸). web_fetch Ñ‚ÐµÑ€ÑÐ» '#â€¦' ÐºÐ°Ðº Ñ„Ñ€Ð°Ð³Ð¼ÐµÐ½Ñ‚ URL Ð¸ Ð¾Ñ‚Ð´Ð°Ð²Ð°Ð» 0
Ñ€ÐµÐ·ÑƒÐ»ÑŒÑ‚Ð°Ñ‚Ð¾Ð² â€” Ð¾Ñ‚ÑÑŽÐ´Ð° Ð¿Ñ€ÐµÐ¶Ð½Ð¸Ð¹ Ð¾ÑˆÐ¸Ð±Ð¾Ñ‡Ð½Ñ‹Ð¹ Ð²Ñ‹Ð²Ð¾Ð´ Â«subject Ð½Ðµ Ñ„Ð¸Ð»ÑŒÑ‚Ñ€ÑƒÐµÑ‚Â».

ÐŸÐ¸ÑˆÐµÑ‚ ÑÑ‹Ñ€Ð¾Ð¹ Atom XML ÐšÐÐš Ð•Ð¡Ð¢Ð¬ Ð²:
  pipeline/raw/{date}/nl_rechtspraak_1.txt   (ÑÐµÐ³Ð¾Ð´Ð½Ñ)
  pipeline/raw/{date}/nl_rechtspraak_2.txt   (Ð²Ñ‡ÐµÑ€Ð°)
Ð¡ÑƒÑ‰ÐµÑÑ‚Ð²ÑƒÑŽÑ‰Ð¸Ð¹ parse_rechtspraak_atom Ñ€Ð°Ð·Ð±Ð¸Ñ€Ð°ÐµÑ‚ ÑÑ‚Ð¾ Ð±ÐµÐ· Ð¸Ð·Ð¼ÐµÐ½ÐµÐ½Ð¸Ð¹.

Ð ÐµÑ†ÐµÐ¿Ñ‚ Ð¿Ñ€Ð¾Ð²ÐµÑ€ÐµÐ½ Ð¶Ð¸Ð²ÑŒÑ‘Ð¼ 2026-07-17 (Ð”ÐžÐ ÐžÐ–ÐÐÐ¯_ÐšÐÐ Ð¢Ð_v2 Â§5.1):
  GET https://data.rechtspraak.nl/uitspraken/zoeken
      ?subject=http%3A%2F%2Fpsi.rechtspraak.nl%2Frechtsgebied%23bestuursrecht_belastingrecht
      &date=YYYY-MM-DD&type=Uitspraak&return=DOC&max=200
ÐŸÑ€Ð°Ð²Ð¸Ð»Ð° Ð²ÐµÐ¶Ð»Ð¸Ð²Ð¾ÑÑ‚Ð¸ API: Ð·Ð°Ð¿Ñ€Ð¾ÑÑ‹ Ð¿Ð¾ÑÐ»ÐµÐ´Ð¾Ð²Ð°Ñ‚ÐµÐ»ÑŒÐ½Ð¾, Ñ Ð¿Ð°ÑƒÐ·Ð¾Ð¹; Ð±ÐµÐ· Ð¿Ð°Ñ€Ð°Ð»Ð»ÐµÐ»ÑŒÐ½Ñ‹Ñ….

Ð˜ÑÐ¿Ð¾Ð»ÑŒÐ·Ð¾Ð²Ð°Ð½Ð¸Ðµ:
  python3 scripts/collect_rechtspraak.py --date 2026-07-17 [--root .]
ÐšÐ¾Ð´Ñ‹ Ð²Ð¾Ð·Ð²Ñ€Ð°Ñ‚Ð°: 0 â€” Ð¾Ð±Ð° Ð´Ð½Ñ ÑÐ¾Ð±Ñ€Ð°Ð½Ñ‹; 1 â€” Ñ‡Ð°ÑÑ‚ÑŒ Ð´Ð½ÐµÐ¹ Ð² ÑÐ±Ð¾Ðµ (Ð¿Ð¾Ð¼ÐµÑ‡ÐµÐ½Ñ‹), Ð¿Ñ€Ð¾Ð³Ð¾Ð½ Ð½Ðµ
Ð¿Ð°Ð´Ð°ÐµÑ‚; 2 â€” Ð½ÐµÐºÐ¾Ñ€Ñ€ÐµÐºÑ‚Ð½Ñ‹Ðµ Ð°Ñ€Ð³ÑƒÐ¼ÐµÐ½Ñ‚Ñ‹/Ð½ÐµÑ‚ requests.
"""

import argparse
import os
import sys
import time
from datetime import datetime, timedelta

try:
    import requests
except ImportError:  # pragma: no cover
    print("ÐÑƒÐ¶ÐµÐ½ requests. Ð£ÑÑ‚Ð°Ð½Ð¾Ð²ÐºÐ°: pip install requests --break-system-packages",
          file=sys.stderr)
    sys.exit(2)

ZOEKEN_URL = "https://data.rechtspraak.nl/uitspraken/zoeken"
# URI Ð¾Ð±Ð»Ð°ÑÑ‚Ð¸ Ð¿Ñ€Ð°Ð²Ð° Â«bestuursrecht â†’ belastingrechtÂ». '#' Ð·Ð°ÐºÐ¾Ð´Ð¸Ñ€ÑƒÐµÑ‚ÑÑ ÐºÐ°Ðº %23
# Ð°Ð²Ñ‚Ð¾Ð¼Ð°Ñ‚Ð¸Ñ‡ÐµÑÐºÐ¸, Ñ‚.Ðº. Ð·Ð½Ð°Ñ‡ÐµÐ½Ð¸Ðµ ÑƒÑ…Ð¾Ð´Ð¸Ñ‚ Ñ‡ÐµÑ€ÐµÐ· params, Ð½Ðµ Ñ‡ÐµÑ€ÐµÐ· ÑÑ‹Ñ€ÑƒÑŽ ÑÑ‚Ñ€Ð¾ÐºÑƒ URL.
SUBJECT_BELASTINGRECHT = (
    "http://psi.rechtspraak.nl/rechtsgebied#bestuursrecht_belastingrecht"
)
USER_AGENT = "AcademyBEPS-NewsPipeline/1.0 (rechtspraak Open Data collector)"
PAUSE_SECONDS = 5   # Ð¿Ð°ÑƒÐ·Ð° Ð¼ÐµÐ¶Ð´Ñƒ Ð´Ð²ÑƒÐ¼Ñ Ð·Ð°Ð¿Ñ€Ð¾ÑÐ°Ð¼Ð¸ (Ð²ÐµÐ¶Ð»Ð¸Ð²Ð¾ÑÑ‚ÑŒ Ðº API)
TIMEOUT = 30


def fetch_day(session, day):
    """ÐžÐ´Ð¸Ð½ Ð·Ð°Ð¿Ñ€Ð¾Ñ zoeken Ð·Ð° ÐºÐ¾Ð½ÐºÑ€ÐµÑ‚Ð½Ñ‹Ð¹ Ð´ÐµÐ½ÑŒ. Ð’Ð¾Ð·Ð²Ñ€Ð°Ñ‰Ð°ÐµÑ‚ (text, status_code, error)."""
    params = {
        "subject": SUBJECT_BELASTINGRECHT,  # requests Ð·Ð°ÐºÐ¾Ð´Ð¸Ñ€ÑƒÐµÑ‚ '#' â†’ %23
        "date": day,                         # Ð¾Ð´Ð¸Ð½ Ð´ÐµÐ½ÑŒ Ð·Ð° Ð²Ñ‹Ð·Ð¾Ð² (Ð¾ÐºÐ½Ð¾ 48Ñ‡ = 2 Ð²Ñ‹Ð·Ð¾Ð²Ð°)
        "type": "Uitspraak",
        "return": "DOC",
        "max": "200",
    }
    try:
        r = session.get(ZOEKEN_URL, params=params, timeout=TIMEOUT)
        return r.text, r.status_code, None
    except requests.RequestException as e:  # ÑÐµÑ‚ÑŒ/Ñ‚Ð°Ð¹Ð¼Ð°ÑƒÑ‚ â€” Ð½Ðµ Ñ€Ð¾Ð½ÑÐµÐ¼ Ð¿Ñ€Ð¾Ð³Ð¾Ð½
        return "", None, str(e)


def run(run_date, root):
    """Ð¡Ð¾Ð±Ñ€Ð°Ñ‚ÑŒ ÑÐ¿Ð¸ÑÐ¾Ðº Ð·Ð° ÑÐµÐ³Ð¾Ð´Ð½Ñ Ð¸ Ð²Ñ‡ÐµÑ€Ð°. Ð’Ð¾Ð·Ð²Ñ€Ð°Ñ‰Ð°ÐµÑ‚ ÐºÐ¾Ð´ Ð²Ð¾Ð·Ð²Ñ€Ð°Ñ‚Ð° Ð¿Ñ€Ð¾Ñ†ÐµÑÑÐ°."""
    try:
        rd = datetime.strptime(run_date, "%Y-%m-%d").date()
    except ValueError:
        print(f"[rechtspraak] Ð½ÐµÐºÐ¾Ñ€Ñ€ÐµÐºÑ‚Ð½Ð°Ñ Ð´Ð°Ñ‚Ð°: {run_date!r} (Ð¾Ð¶Ð¸Ð´Ð°ÐµÑ‚ÑÑ YYYY-MM-DD)",
              file=sys.stderr)
        return 2
    yesterday = rd - timedelta(days=1)

    raw_dir = os.path.join(root, "pipeline", "raw", run_date)
    os.makedirs(raw_dir, exist_ok=True)

    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "application/atom+xml, application/xml;q=0.9, */*;q=0.1",
    })

    plan = [
        (rd.isoformat(), "nl_rechtspraak_1.txt"),        # ÑÐµÐ³Ð¾Ð´Ð½Ñ
        (yesterday.isoformat(), "nl_rechtspraak_2.txt"),  # Ð²Ñ‡ÐµÑ€Ð°
    ]

    rc = 0
    for i, (day, fname) in enumerate(plan):
        if i:
            time.sleep(PAUSE_SECONDS)
        text, status, error = fetch_day(session, day)
        out_path = os.path.join(raw_dir, fname)
        if error is not None or status != 200:
            # Ð˜ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº Ð¼Ð¾Ð¶ÐµÑ‚ ÑÐ±Ð¾Ð¸Ñ‚ÑŒ â€” Ð¿Ð¾Ð¼ÐµÑ‡Ð°ÐµÐ¼ Ñ„Ð°Ð¹Ð» Ð¸ Ð¿Ñ€Ð¾Ð´Ð¾Ð»Ð¶Ð°ÐµÐ¼ (Ð¾ÑˆÐ¸Ð±ÐºÐ° Ð¾Ð´Ð½Ð¾Ð³Ð¾
            # Ð´Ð½Ñ Ð½Ðµ Ð²Ð°Ð»Ð¸Ñ‚ Ð²ÐµÑÑŒ Ð¿Ñ€Ð¾Ð³Ð¾Ð½, ÐºÐ°Ðº Ð¸ Ñ‚Ñ€ÐµÐ±ÑƒÐµÑ‚ PROCESS.md).
            note = error or f"HTTP {status}"
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(f"[collect_rechtspraak] ÑÐ±Ð¾Ð¹ Ð·Ð° {day}: {note}\n")
            print(f"[rechtspraak] {day}: Ð¡Ð‘ÐžÐ™ ({note}) â†’ Ð¿Ð¾Ð¼ÐµÑ‡ÐµÐ½Ð¾, Ð¿Ñ€Ð¾Ð´Ð¾Ð»Ð¶Ð°ÑŽ",
                  file=sys.stderr)
            rc = 1
            continue
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(text)
        # Ð“Ñ€ÑƒÐ±Ð°Ñ Ð¾Ñ†ÐµÐ½ÐºÐ° Ñ‡Ð¸ÑÐ»Ð° Ð½Ð°Ð¹Ð´ÐµÐ½Ð½Ñ‹Ñ… Ñ€ÐµÑˆÐµÐ½Ð¸Ð¹ Ð´Ð»Ñ Ð»Ð¾Ð³Ð° (Ð±ÐµÐ· Ñ€Ð°Ð·Ð±Ð¾Ñ€Ð° ÐºÐ¾Ð½Ñ‚ÐµÐ½Ñ‚Ð°).
        n_entries = text.count("<entry")
        print(f"[rechtspraak] {day}: HTTP 200, ~{n_entries} entries â†’ {out_path}")
    return rc


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(
        description="ÐŸÑ€ÑÐ¼Ð¾Ð¹ HTTP-ÑÐ±Ð¾Ñ€ ÑÐ¿Ð¸ÑÐºÐ° rechtspraak (belastingrecht).")
    ap.add_argument("--date", required=True, help="Ð”Ð°Ñ‚Ð° Ð¿Ñ€Ð¾Ð³Ð¾Ð½Ð° YYYY-MM-DD (ÑÐµÐ³Ð¾Ð´Ð½Ñ).")
    ap.add_argument("--root", default=".", help="ÐšÐ¾Ñ€ÐµÐ½ÑŒ Ð¿Ñ€Ð¾ÐµÐºÑ‚Ð° News Claude.")
    args = ap.parse_args()
    sys.exit(run(args.date, args.root))


if __name__ == "__main__":
    main()

