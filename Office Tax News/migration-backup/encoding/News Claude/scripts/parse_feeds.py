#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ÐŸÐ°Ñ€ÑÐ¸Ð½Ð³ ÑÑ‹Ñ€Ñ‹Ñ… Ð¾Ñ‚Ð²ÐµÑ‚Ð¾Ð² web_fetch â†’ pipeline/inbox/{date}_items.jsonl. Ð¢Ð¾Ð»ÑŒÐºÐ¾ stdlib + PyYAML."""

import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime
from email.utils import parsedate_to_datetime
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit
from xml.etree import ElementTree as ET

try:
    import yaml
except ImportError:  # pragma: no cover - Ð¿Ð¾Ð´ÑÐºÐ°Ð·ÐºÐ° Ð¿Ð¾ ÑƒÑÑ‚Ð°Ð½Ð¾Ð²ÐºÐµ Ð·Ð°Ð²Ð¸ÑÐ¸Ð¼Ð¾ÑÑ‚Ð¸
    print("ÐÑƒÐ¶ÐµÐ½ PyYAML. Ð£ÑÑ‚Ð°Ð½Ð¾Ð²ÐºÐ°: pip install pyyaml --break-system-packages", file=sys.stderr)
    sys.exit(2)

from court_registry import upsert_court_decisions

# --- ÐœÐµÑÑÑ†Ñ‹ Ð´Ð»Ñ Ñ€Ð°Ð·Ð±Ð¾Ñ€Ð° Ð´Ð°Ñ‚ ----------------------------------------------------
NL_MONTHS = {
    "januari": 1, "februari": 2, "maart": 3, "april": 4, "mei": 5, "juni": 6,
    "juli": 7, "augustus": 8, "september": 9, "oktober": 10, "november": 11,
    "december": 12,
}
EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6,
    "july": 7, "august": 8, "september": 9, "october": 10, "november": 11,
    "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8,
    "sep": 9, "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}

# ÐžÐ±Ñ‰Ð¸Ðµ Ð¼ÑƒÑÐ¾Ñ€Ð½Ñ‹Ðµ ÑÐ»Ð¾Ð²Ð° Ð½Ð°Ð²Ð¸Ð³Ð°Ñ†Ð¸Ð¸/ÑÐµÑ€Ð²Ð¸ÑÐ° (Ð´Ð»Ñ html_links Ñ„Ð¸Ð»ÑŒÑ‚Ñ€Ð°).
NAV_STOPWORDS = {
    "read more", "lees verder", "meer", "inloggen", "login", "zoeken", "search",
    "home", "menu", "abonneren", "aanmelden", "meer nieuws", "alle nieuws",
    "Ð´Ð°Ð»ÐµÐµ", "Ð¿Ð¾Ð´Ñ€Ð¾Ð±Ð½ÐµÐµ", "Ð²Ð¾Ð¹Ñ‚Ð¸", "Ð¿Ð¾Ð¸ÑÐº", "Ð²ÑÐµ Ð½Ð¾Ð²Ð¾ÑÑ‚Ð¸", "Ñ‡Ð¸Ñ‚Ð°Ñ‚ÑŒ Ð´Ð°Ð»ÐµÐµ",
    "rss", "contact", "over ons", "cookie", "privacy", "next", "previous",
    "volgende", "vorige", "Ð¾ÑÑ‚Ð°Ð²Ð¸Ñ‚ÑŒ Ð·Ð°ÑÐ²ÐºÑƒ",
}


# ÐœÐ¸Ð½Ð¸Ð¼Ð°Ð»ÑŒÐ½Ð°Ñ Ð´Ð»Ð¸Ð½Ð° Ð¾ÑÐ¼Ñ‹ÑÐ»ÐµÐ½Ð½Ð¾Ð³Ð¾ Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²ÐºÐ° (ÐºÐ¾Ñ€Ð¾Ñ‡Ðµ â€” ÑÑ‡Ð¸Ñ‚Ð°ÐµÐ¼ Ð½Ð°Ð²Ð¸Ð³Ð°Ñ†Ð¸ÐµÐ¹).
MIN_TITLE_LEN = 20


# =============================================================================
#  Ð’Ð¡ÐŸÐžÐœÐžÐ“ÐÐ¢Ð•Ð›Ð¬ÐÐ«Ð•
# =============================================================================
def load_sources(root):
    """Ð—Ð°Ð³Ñ€ÑƒÐ·Ð¸Ñ‚ÑŒ config/sources.yaml â†’ dict {source_id: cfg}."""
    path = os.path.join(root, "config", "sources.yaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    out = {}
    for src in data.get("sources", []):
        out[src["id"]] = src
    return out


def html_rules(src_cfg):
    """Ð•Ð´Ð¸Ð½ÑÑ‚Ð²ÐµÐ½Ð½Ñ‹Ð¹ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº Ð¿Ñ€Ð°Ð²Ð¸Ð» HTML-Ð¿Ð°Ñ€ÑÐµÑ€Ð° â€” Ð·Ð°Ð¿Ð¸ÑÑŒ Ð² sources.yaml."""
    rules = src_cfg.get("html") or {}
    return {
        "base": rules.get("base") or src_cfg.get("url") or "",
        "include": list(rules.get("include") or []),
        "exclude": list(rules.get("exclude") or []),
        "path_hint": rules.get("path_hint") or "",
        "date_from_title": rules.get("date_from_title") or "",
    }


def clean_text(s):
    """Ð¡Ð½ÑÑ‚ÑŒ HTML-ÑÑƒÑ‰Ð½Ð¾ÑÑ‚Ð¸ Ð¸ ÑÑ…Ð»Ð¾Ð¿Ð½ÑƒÑ‚ÑŒ Ð¿Ñ€Ð¾Ð±ÐµÐ»Ñ‹."""
    if not s:
        return ""
    s = unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def read_raw_text(path):
    """ÐŸÑ€Ð¾Ñ‡Ð¸Ñ‚Ð°Ñ‚ÑŒ ÑÑ‹Ñ€ÑŒÑ‘, Ð¾Ð¿Ñ€ÐµÐ´ÐµÐ»Ð¸Ð² ÐºÐ¾Ð´Ð¸Ñ€Ð¾Ð²ÐºÑƒ Ð¿Ð¾ meta charset.

    ÐŸÑ€ÑÐ¼Ð¾Ð¹ Ñ‚Ñ€Ð°Ð½ÑÐ¿Ð¾Ñ€Ñ‚ Ð¾Ñ‚Ð´Ð°Ñ‘Ñ‚ Ð¶Ð¸Ð²Ð¾Ð¹ HTML: garant.ru â€” windows-1251, Ð¾ÑÑ‚Ð°Ð»ÑŒÐ½Ñ‹Ðµ utf-8.
    ÐžÐ¿Ñ€ÐµÐ´ÐµÐ»ÑÐµÐ¼ charset Ð¿Ð¾ Ð¿ÐµÑ€Ð²Ñ‹Ð¼ 2ÐšÐ‘ (Ð¾Ð½Ð¸ ASCII-ÑÐ¾Ð²Ð¼ÐµÑÑ‚Ð¸Ð¼Ñ‹); web_fetch-Ñ„Ð¸ÐºÑÑ‚ÑƒÑ€Ñ‹
    Ð±ÐµÐ· charset Ñ‡Ð¸Ñ‚Ð°ÑŽÑ‚ÑÑ ÐºÐ°Ðº utf-8 (Ð¾Ð±Ñ€Ð°Ñ‚Ð½Ð°Ñ ÑÐ¾Ð²Ð¼ÐµÑÑ‚Ð¸Ð¼Ð¾ÑÑ‚ÑŒ).
    """
    raw = Path(path).read_bytes()
    # utf-8 ÑÑ‚Ñ€Ð¾Ð³Ð¾: Ð¿Ð¾Ð´Ñ…Ð¾Ð´Ð¸Ñ‚ Ð´Ð»Ñ markdown-Ñ„Ð¸ÐºÑÑ‚ÑƒÑ€ web_fetch Ð¸ Ð´Ð»Ñ utf-8 HTML.
    # (ÐÐµ ÑÐºÐ°Ð½Ð¸Ñ€ÑƒÐµÐ¼ Ñ‚ÐµÐºÑÑ‚ Ð½Ð° 'charset' Ð´Ð¾ ÑÑ‚Ð¾Ð³Ð¾ â€” Ð¸Ð½Ð°Ñ‡Ðµ Ð¾Ð¿Ð¸ÑÐ°Ñ‚ÐµÐ»ÑŒÐ½Ð°Ñ Ñ„Ð¸ÐºÑÑ‚ÑƒÑ€Ð°,
    # ÑƒÐ¿Ð¾Ð¼Ð¸Ð½Ð°ÑŽÑ‰Ð°Ñ 'windows-1251', Ð¾ÑˆÐ¸Ð±Ð¾Ñ‡Ð½Ð¾ Ð´ÐµÐºÐ¾Ð´Ð¸Ñ€Ð¾Ð²Ð°Ð»Ð°ÑÑŒ Ð±Ñ‹ ÐºÐ°Ðº cp1251.)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # ÐÐµ utf-8 (Ð½Ð°Ð¿Ñ€. garant Ð² windows-1251) â€” Ð±ÐµÑ€Ñ‘Ð¼ charset Ð¸Ð· <meta>, Ð¸Ð½Ð°Ñ‡Ðµ cp1251.
    head = raw[:2048].decode("ascii", "replace")
    m = re.search(r'<meta[^>]+charset=["\']?([\w\-]+)', head, re.IGNORECASE)
    enc = (m.group(1).lower() if m else "cp1251")
    if enc in ("windows-1251", "win-1251"):
        enc = "cp1251"
    try:
        return raw.decode(enc, "replace")
    except (LookupError, UnicodeDecodeError):
        return raw.decode("cp1251", "replace")


class _AnchorExtractor(HTMLParser):
    """Ð¡Ð¾Ð±Ñ€Ð°Ñ‚ÑŒ (href, Ñ‚ÐµÐºÑÑ‚) Ð²ÑÐµÑ… <a> Ð¸Ð· Ð¶Ð¸Ð²Ð¾Ð³Ð¾ HTML (stdlib)."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self._href = None
        self._buf = []

    def handle_starttag(self, tag, attrs):
        if tag == "a":
            self._href = dict(attrs).get("href")
            self._buf = []

    def handle_data(self, data):
        if self._href is not None:
            self._buf.append(data)

    def handle_endtag(self, tag):
        if tag == "a" and self._href is not None:
            text = re.sub(r"\s+", " ", "".join(self._buf)).strip()
            self.links.append((self._href, text))
            self._href = None


def looks_like_binary(text):
    """ÐžÑ‚Ð²ÐµÑ‚ Ð½ÐµÐ¿Ð°Ñ€ÑÐ¸Ð±ÐµÐ»ÐµÐ½: Ð¿ÑƒÑÑ‚Ð¾Ðµ Ñ‚ÐµÐ»Ð¾, Ñ‚Ð¾Ð»ÑŒÐºÐ¾ ÑÑ…Ð¾ URL Ð¸Ð»Ð¸ ÑÐ¿Ð»Ð¾ÑˆÐ½Ð¾Ð¹ [binary data].

    ÐžÐ´Ð¸Ð½Ð¾Ñ‡Ð½Ð¾Ðµ ÑƒÐ¿Ð¾Ð¼Ð¸Ð½Ð°Ð½Ð¸Ðµ [binary data] (Ð¾Ð¿Ð¸ÑÐ°Ð½Ð¸Ðµ Ð½ÐµÑƒÐ´Ð°Ð²ÑˆÐµÐ³Ð¾ÑÑ Ð¿Ð¾Ð´-Ñ‚ÐµÑÑ‚Ð°) ÐÐ•
    Ð´Ð¸ÑÐºÐ²Ð°Ð»Ð¸Ñ„Ð¸Ñ†Ð¸Ñ€ÑƒÐµÑ‚ Ñ„Ð¸ÐºÑÑ‚ÑƒÑ€Ñƒ, ÐµÑÐ»Ð¸ Ð² Ð½ÐµÐ¹ Ð¾ÑÑ‚Ð°Ñ‘Ñ‚ÑÑ Ñ‡Ð¸Ñ‚Ð°ÐµÐ¼Ñ‹Ð¹ Ñ‚ÐµÐºÑÑ‚. ÐžÑ†ÐµÐ½Ð¸Ð²Ð°ÐµÐ¼
    Ð¾Ð±ÑŠÑ‘Ð¼ Â«Ð¿Ð¾Ð»ÐµÐ·Ð½Ð¾Ð³Ð¾Â» Ñ‚ÐµÐºÑÑ‚Ð°: Ð²Ñ‹ÐºÐ¸Ð´Ñ‹Ð²Ð°ÐµÐ¼ ÑÑ‚Ñ€Ð¾ÐºÐ¸-ÑÑ…Ð¾ URL Ð¸ binary-Ð¼Ð°Ñ€ÐºÐµÑ€Ñ‹ Ð¸
    ÑÐ¼Ð¾Ñ‚Ñ€Ð¸Ð¼, Ñ‡Ñ‚Ð¾ Ð¾ÑÑ‚Ð°Ð»Ð¾ÑÑŒ.
    """
    if text is None:
        return True
    stripped = text.strip()
    if not stripped:
        return True

    # ÐšÐ¾Ñ€Ð¾Ñ‚ÐºÐ¸Ð¹ JSON-ÐºÐ¾Ð½Ð²ÐµÑ€Ñ‚ collector'Ð° (Ð½Ð°Ð¿Ñ€. RAS Ñ 0 Ñ€ÐµÐ·ÑƒÐ»ÑŒÑ‚Ð°Ñ‚Ð¾Ð²)
    # ÑÐ²Ð»ÑÐµÑ‚ÑÑ Ð²Ð°Ð»Ð¸Ð´Ð½Ñ‹Ð¼ ÑÑ‹Ñ€ÑŒÑ‘Ð¼, Ð´Ð°Ð¶Ðµ ÐµÑÐ»Ð¸ Ð¾Ð½ ÐºÐ¾Ñ€Ð¾Ñ‡Ðµ Ñ‚ÐµÐºÑÑ‚Ð¾Ð²Ð¾Ð³Ð¾ Ð¿Ð¾Ñ€Ð¾Ð³Ð°.
    if stripped[:1] in "[{":
        try:
            payload = json.loads(stripped)
            if isinstance(payload, list) or (
                isinstance(payload, dict) and isinstance(payload.get("items"), list)
            ):
                return False
        except json.JSONDecodeError:
            pass

    meaningful = []
    for line in stripped.splitlines():
        ln = line.strip()
        if not ln:
            continue
        if ln.lower() == "[binary data]":
            continue
        # Ð¡Ñ‚Ñ€Ð¾ÐºÐ°, ÑÐ¾ÑÑ‚Ð¾ÑÑ‰Ð°Ñ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð¸Ð· URL (ÑÑ…Ð¾ web_fetch), Ð½Ðµ Ð½ÐµÑÑ‘Ñ‚ ÐºÐ¾Ð½Ñ‚ÐµÐ½Ñ‚Ð°.
        if re.fullmatch(r"https?://\S+", ln):
            continue
        # Ð¯Ð²Ð½Ñ‹Ð¹ Ð¾Ñ‚ÐºÐ°Ð· Ð¿Ð¾Ð»Ð¸Ñ‚Ð¸ÐºÐ¸ Ð±ÐµÐ· Ð¸Ð½Ð¾Ð³Ð¾ ÐºÐ¾Ð½Ñ‚ÐµÐ½Ñ‚Ð°.
        if ln == "Web fetch was not allowed.":
            continue
        meaningful.append(ln)

    body = " ".join(meaningful).strip()
    # Ð¡Ð¾Ð²ÑÐµÐ¼ Ð¼Ð°Ð»Ð¾ Ð¾ÑÐ¼Ñ‹ÑÐ»ÐµÐ½Ð½Ð¾Ð³Ð¾ Ñ‚ÐµÐºÑÑ‚Ð° â€” ÑÑ‡Ð¸Ñ‚Ð°ÐµÐ¼ Ð½ÐµÐ¿Ð°Ñ€ÑÐ¸Ð±ÐµÐ»ÑŒÐ½Ñ‹Ð¼.
    if len(body) < 120:
        return True
    return False


# =============================================================================
#  ÐŸÐÐ Ð¡Ð•Ð  1: rechtspraak_atom (Atom 1.0 Ð¸Ð· data.rechtspraak.nl)
# =============================================================================
def parse_rechtspraak_atom(text, src_cfg):
    """Ð˜Ð·Ð²Ð»ÐµÑ‡ÑŒ <entry> Atom-Ñ„Ð¸Ð´Ð° rechtspraak: ECLI(id), title, summary, updated, deeplink."""
    items = []
    # Ð¤Ð¸ÐºÑÑ‚ÑƒÑ€Ð°/Ð¾Ñ‚Ð²ÐµÑ‚ ÑÐ¾Ð´ÐµÑ€Ð¶Ð¸Ñ‚ XML Ð³Ð´Ðµ-Ñ‚Ð¾ Ð² Ñ‚ÐµÐ»Ðµ â€” Ð±ÐµÑ€Ñ‘Ð¼ Ð²ÑÐµ <entry>...</entry>.
    for m in re.finditer(r"<entry\b[^>]*>(.*?)</entry>", text, re.DOTALL | re.IGNORECASE):
        block = m.group(1)

        def tag(name):
            mm = re.search(rf"<{name}\b[^>]*>(.*?)</{name}>", block, re.DOTALL | re.IGNORECASE)
            return clean_text(mm.group(1)) if mm else ""

        ecli = tag("id")
        title = tag("title")
        summary = tag("summary")
        updated = tag("updated")

        # deeplink: <link rel="alternate" ... href="...">
        link = ""
        lm = re.search(r'<link\b[^>]*rel="alternate"[^>]*href="([^"]+)"', block, re.IGNORECASE)
        if not lm:
            lm = re.search(r'<link\b[^>]*href="([^"]+)"[^>]*rel="alternate"', block, re.IGNORECASE)
        if lm:
            link = clean_text(lm.group(1))
        if not link and ecli.startswith("ECLI"):
            link = f"https://uitspraken.rechtspraak.nl/details?id={ecli}"

        if not ecli:
            continue
        # summary Ð¸Ð½Ð¾Ð³Ð´Ð° "-" (Ð½ÐµÑ‚ Ð°Ð½Ð½Ð¾Ñ‚Ð°Ñ†Ð¸Ð¸) â€” Ð½Ð¾Ñ€Ð¼Ð°Ð»Ð¸Ð·ÑƒÐµÐ¼ Ðº Ð¿ÑƒÑÑ‚Ð¾Ð¹ ÑÑ‚Ñ€Ð¾ÐºÐµ.
        if summary == "-":
            summary = ""

        published_at = ""
        if updated:
            # ISO8601 â†’ YYYY-MM-DD (ÑƒÑÑ‚Ð¾Ð¹Ñ‡Ð¸Ð²Ð¾ Ðº ÑÑƒÑ„Ñ„Ð¸ÐºÑÐ°Ð¼ Z/+02:00).
            dm = re.match(r"(\d{4}-\d{2}-\d{2})", updated)
            published_at = dm.group(1) if dm else updated

        items.append({
            "url": link,
            "ecli": ecli,
            "title": title or ecli,
            "summary": summary,
            "published_at": published_at,
        })
    return items


def _local_name(tag):
    """Ð›Ð¾ÐºÐ°Ð»ÑŒÐ½Ð¾Ðµ Ð¸Ð¼Ñ XML-Ñ‚ÐµÐ³Ð° Ð±ÐµÐ· namespace."""
    return tag.rsplit("}", 1)[-1].casefold()


def _xml_text(node, *names):
    """Ð¢ÐµÐºÑÑ‚ Ð¿ÐµÑ€Ð²Ð¾Ð³Ð¾ Ð´Ð¾Ñ‡ÐµÑ€Ð½ÐµÐ³Ð¾ XML-ÑÐ»ÐµÐ¼ÐµÐ½Ñ‚Ð° Ñ Ð¾Ð´Ð½Ð¸Ð¼ Ð¸Ð· Ð»Ð¾ÐºÐ°Ð»ÑŒÐ½Ñ‹Ñ… Ð¸Ð¼Ñ‘Ð½."""
    wanted = {n.casefold() for n in names}
    for child in list(node):
        if _local_name(child.tag) in wanted:
            return clean_text("".join(child.itertext()))
    return ""


def _feed_date(value):
    """RSS/Atom-Ð´Ð°Ñ‚Ð° â†’ YYYY-MM-DD."""
    value = clean_text(value)
    if not value:
        return ""
    m = re.match(r"(\d{4}-\d{2}-\d{2})", value)
    if m:
        return m.group(1)
    try:
        return parsedate_to_datetime(value).date().isoformat()
    except (TypeError, ValueError, OverflowError):
        return ""


def _ymd_from_attrs(fragment):
    """Ð”Ð°Ñ‚Ð° Ð¸Ð· data-year/month/day Ð¾Ñ„Ð¸Ñ†Ð¸Ð°Ð»ÑŒÐ½Ð¾Ð³Ð¾ Ð»Ð¸ÑÑ‚Ð¸Ð½Ð³Ð° Ð’Ð¡ Ð Ð¤."""
    values = {}
    for key in ("year", "month", "day"):
        match = re.search(rf'data-{key}=["\'](\d+)["\']', fragment, re.IGNORECASE)
        if match:
            values[key] = int(match.group(1))
    if len(values) != 3:
        return ""
    try:
        return datetime(values["year"], values["month"], values["day"]).date().isoformat()
    except ValueError:
        return ""


def parse_json_items(text, src_cfg):
    """ÐžÐ±Ñ‰Ð¸Ð¹ JSON/JSONL-ÐºÐ¾Ð½Ð²ÐµÑ€Ñ‚ ÑƒÐ¶Ðµ Ð½Ð¾Ñ€Ð¼Ð°Ð»Ð¸Ð·Ð¾Ð²Ð°Ð½Ð½Ñ‹Ñ… collector items."""
    stripped = text.strip()
    try:
        payload = json.loads(stripped)
        items = payload.get("items", []) if isinstance(payload, dict) else payload
    except json.JSONDecodeError:
        items = []
        for line in stripped.splitlines():
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return [item for item in items if isinstance(item, dict)]


def parse_vs_ajax_json(text, src_cfg):
    """JSON XHR-Ð»Ð¸ÑÑ‚Ð¸Ð½Ð³Ð° Ð¾Ñ„Ð¸Ñ†Ð¸Ð°Ð»ÑŒÐ½Ð¾Ð³Ð¾ ÑÐ°Ð¹Ñ‚Ð° Ð’ÐµÑ€Ñ…Ð¾Ð²Ð½Ð¾Ð³Ð¾ Ð¡ÑƒÐ´Ð° Ð Ð¤."""
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []
    fragments = payload.get("list", []) if isinstance(payload, dict) else []
    items = []
    for fragment in fragments:
        if not isinstance(fragment, str):
            continue
        is_review = "vs-items-title" in fragment
        base = ("https://vsrf.ru/documents/reviews/" if is_review
                else "https://vsrf.ru/press_center/news/")
        anchor_match = None
        for candidate in re.finditer(
            r'<a\s+href=["\']([^"\']+)["\'][^>]*>(.*?)</a>',
            fragment,
            re.IGNORECASE | re.DOTALL,
        ):
            if len(_strip_markup(candidate.group(2))) >= MIN_TITLE_LEN:
                anchor_match = candidate
                break
        if anchor_match is None:
            continue
        href, inner = anchor_match.group(1), anchor_match.group(2)
        annotation_pos = re.search(r'<span[^>]*data-annotation', inner, re.IGNORECASE)
        title_html = inner[:annotation_pos.start()] if annotation_pos else inner
        summary_html = inner[annotation_pos.start():] if annotation_pos else ""
        title = _strip_markup(title_html)
        summary = _strip_markup(summary_html)
        if not title:
            continue
        if is_review:
            review_hay = f"{title} {summary}".casefold()
            if not (
                "Ð½Ð°Ð»Ð¾Ð³" in review_hay
                or "Ð¾Ð±Ð·Ð¾Ñ€ ÑÑƒÐ´ÐµÐ±Ð½Ð¾Ð¹ Ð¿Ñ€Ð°ÐºÑ‚Ð¸ÐºÐ¸ Ð²ÐµÑ€Ñ…Ð¾Ð²Ð½Ð¾Ð³Ð¾ ÑÑƒÐ´Ð° Ñ€Ð¾ÑÑÐ¸Ð¹ÑÐºÐ¾Ð¹ Ñ„ÐµÐ´ÐµÑ€Ð°Ñ†Ð¸Ð¸" in review_hay
            ):
                continue
        items.append({
            "url": urljoin(base, href),
            "ecli": "",
            "act": "",
            "title": title,
            "summary": summary,
            "published_at": _ymd_from_attrs(fragment),
            "item_type": "court_review" if is_review else "court_news",
        })
    return _dedup_by_url_title(items)


def _strip_markup(value):
    """ÐšÐ¾Ð¼Ð¿Ð°ÐºÑ‚Ð½Ñ‹Ð¹ plain-text Ð¸Ð· RSS description/content."""
    return clean_text(re.sub(r"<[^>]+>", " ", unescape(value or "")))


def _canonical_feed_url(value):
    """Ð£Ð±Ñ€Ð°Ñ‚ÑŒ RSS tracking-Ð¿Ð°Ñ€Ð°Ð¼ÐµÑ‚Ñ€Ñ‹, ÑÐ¾Ñ…Ñ€Ð°Ð½Ð¸Ð² ÑÐ¼Ñ‹ÑÐ»Ð¾Ð²Ñ‹Ðµ query-Ð¿Ð¾Ð»Ñ."""
    try:
        parts = urlsplit(value)
        query = urlencode([
            (key, val) for key, val in parse_qsl(parts.query, keep_blank_values=True)
            if not key.casefold().startswith("utm_")
        ], doseq=True)
        return urlunsplit((parts.scheme, parts.netloc, parts.path, query, ""))
    except (TypeError, ValueError):
        return value


def parse_rss_atom(text, src_cfg):
    """ÐžÐ±Ñ‰Ð¸Ð¹ RSS 2.0 / Atom-Ð¿Ð°Ñ€ÑÐµÑ€ Ð´Ð»Ñ Ð¿Ñ€ÑÐ¼Ð¾Ð³Ð¾ HTTP-Ñ‚Ñ€Ð°Ð½ÑÐ¿Ð¾Ñ€Ñ‚Ð°."""
    try:
        root = ET.fromstring(text.lstrip("\ufeff\x00 \t\r\n"))
    except ET.ParseError:
        return []

    root_name = _local_name(root.tag)
    if root_name == "rss":
        nodes = [n for n in root.iter() if _local_name(n.tag) == "item"]
    elif root_name == "feed":
        nodes = [n for n in list(root) if _local_name(n.tag) == "entry"]
    else:
        return []

    items = []
    rules = html_rules(src_cfg)
    for node in nodes:
        title = _xml_text(node, "title")
        if not title:
            continue
        link = _xml_text(node, "link")
        if not link:
            for child in list(node):
                if _local_name(child.tag) == "link" and child.attrib.get("href"):
                    rel = child.attrib.get("rel", "alternate")
                    if rel in ("", "alternate"):
                        link = child.attrib["href"]
                        break
        guid = _xml_text(node, "guid", "id")
        if not link and guid.startswith(("http://", "https://")):
            link = guid
        link = _canonical_feed_url(link)
        # RSS Ð¸ÑÐ¿Ð¾Ð»ÑŒÐ·ÑƒÐµÑ‚ Ñ‚Ðµ Ð¶Ðµ URL-Ð³ÐµÐ¹Ñ‚Ñ‹, Ñ‡Ñ‚Ð¾ Ð¸ HTML-fallback. Ð­Ñ‚Ð¾ Ð½Ðµ Ð´Ð°Ñ‘Ñ‚
        # Ñ€Ð°Ð·Ð´ÐµÐ»Ð°Ð¼ agenda/tag/author Ð²ÐµÑ€Ð½ÑƒÑ‚ÑŒÑÑ Ð² Ð¿Ð¾Ñ‚Ð¾Ðº Ñ‡ÐµÑ€ÐµÐ· feed.
        if link and not _url_ok(link, rules):
            continue
        published = _xml_text(node, "pubDate", "published", "updated", "date")
        summary = _xml_text(node, "description", "summary", "content", "encoded")
        items.append({
            "url": link,
            "ecli": "",
            "title": title,
            "summary": _strip_markup(summary),
            "published_at": _feed_date(published),
        })
    return _dedup_by_url_title(items)


# =============================================================================
#  ÐŸÐÐ Ð¡Ð•Ð  2: html_links (markdown/Ñ‚ÐµÐºÑÑ‚ Ð¾Ñ‚ web_fetch)
# =============================================================================
def _url_ok(url, cfg):
    """URL Ð¿Ñ€Ð¾Ñ…Ð¾Ð´Ð¸Ñ‚ include/exclude Ñ„Ð¸Ð»ÑŒÑ‚Ñ€Ñ‹ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ°."""
    if cfg["include"] and not any(re.search(p, url, re.IGNORECASE) for p in cfg["include"]):
        return False
    if any(re.search(p, url, re.IGNORECASE) for p in cfg.get("exclude", [])):
        return False
    return True


# ÐœÐ°Ñ€ÐºÐµÑ€Ñ‹ ÑÐ»ÑƒÐ¶ÐµÐ±Ð½Ð¾Ð¹ Ð¿Ñ€Ð¾Ð·Ñ‹ probe-Ð¾Ñ‚Ñ‡Ñ‘Ñ‚Ð° / Ñ‚ÐµÑ…Ð½Ð¸Ñ‡ÐµÑÐºÐ¾Ð³Ð¾ Ð¼ÑƒÑÐ¾Ñ€Ð° Ð²Ð½ÑƒÑ‚Ñ€Ð¸ Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²ÐºÐ°.
# Ð–Ð¸Ð²Ð¾Ð¹ web_fetch-Ð²Ñ‹Ð²Ð¾Ð´ Ð¸Ñ… Ð½Ðµ ÑÐ¾Ð´ÐµÑ€Ð¶Ð¸Ñ‚; Ð½ÑƒÐ¶Ð½Ñ‹, Ñ‡Ñ‚Ð¾Ð±Ñ‹ Ð¾Ð¿Ð¸ÑÐ°Ñ‚ÐµÐ»ÑŒÐ½Ñ‹Ðµ Ñ„Ð¸ÐºÑÑ‚ÑƒÑ€Ñ‹ Ð½Ðµ
# Ð¿Ð¾Ñ€Ð¾Ð¶Ð´Ð°Ð»Ð¸ Ð»Ð¾Ð¶Ð½Ñ‹Ðµ Â«Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²ÐºÐ¸Â» Ð¸Ð· Ð¿Ð¾Ð²ÐµÑÑ‚Ð²Ð¾Ð²Ð°Ð½Ð¸Ñ Ð¾Ñ‚Ñ‡Ñ‘Ñ‚Ð°.
_PROSE_MARKERS = re.compile(
    r"(===|https?://|Content-Type|WORKS|EMPTY|binary data|"
    r"URL:|teaser|listing|pattern:|WordPress|markdown|charset|"
    r"probe|fetch|freshness|snapshot|\bnav\b)",
    re.IGNORECASE,
)


def _is_nav_title(title):
    """Ð—Ð°Ð³Ð¾Ð»Ð¾Ð²Ð¾Ðº Ð¿Ð¾Ñ…Ð¾Ð¶ Ð½Ð° Ð½Ð°Ð²Ð¸Ð³Ð°Ñ†Ð¸ÑŽ/ÑÐµÑ€Ð²Ð¸Ñ (ÑÐ»Ð¸ÑˆÐºÐ¾Ð¼ ÐºÐ¾Ñ€Ð¾Ñ‚ÐºÐ¸Ð¹ Ð¸Ð»Ð¸ ÑÑ‚Ð¾Ð¿-ÑÐ»Ð¾Ð²Ð¾)."""
    t = title.strip().casefold()
    if len(title.strip()) < MIN_TITLE_LEN:
        return True
    if t in NAV_STOPWORDS:
        return True
    # ÐžÐ´Ð½Ð¾ ÑÐ»Ð¾Ð²Ð¾ Ð±ÐµÐ· Ð¿Ñ€Ð¾Ð±ÐµÐ»Ð¾Ð² Ð¿Ð¾Ñ‡Ñ‚Ð¸ Ð²ÑÐµÐ³Ð´Ð° â€” Ð¿ÑƒÐ½ÐºÑ‚ Ð¼ÐµÐ½ÑŽ.
    if " " not in title.strip():
        return True
    return False


# Ð‘Ñ€ÐµÐ½Ð´-Ð½Ð°Ð·Ð²Ð°Ð½Ð¸Ñ ÑÑ‚Ñ€Ð°Ð½Ð¸Ñ† (page <title>), Ð½Ðµ ÑÐ²Ð»ÑÑŽÑ‰Ð¸ÐµÑÑ Ð½Ð¾Ð²Ð¾ÑÑ‚Ð½Ñ‹Ð¼Ð¸ Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²ÐºÐ°Ð¼Ð¸.
_BRAND_TITLES = {
    "taxlive | wolterskluwer", "taxence - taxence",
    "rechtspraak open data (uitspraken)",
}


def _is_prose_fragment(title):
    """Ð—Ð°Ð³Ð¾Ð»Ð¾Ð²Ð¾Ðº â€” Ñ„Ñ€Ð°Ð³Ð¼ÐµÐ½Ñ‚ Ð¿Ð¾Ð²ÐµÑÑ‚Ð²Ð¾Ð²Ð°Ð½Ð¸Ñ/Ñ‚ÐµÑ…Ð²Ñ‹Ð²Ð¾Ð´/Ð±Ñ€ÐµÐ½Ð´, Ð° Ð½Ðµ Ð½Ð¾Ð²Ð¾ÑÑ‚Ð½Ð¾Ð¹ Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²Ð¾Ðº."""
    ts = title.strip()
    if not ts:
        return True
    # ÐÐ°Ñ‡Ð¸Ð½Ð°ÐµÑ‚ÑÑ ÑÐ¾ ÑÐ»ÑƒÐ¶ÐµÐ±Ð½Ð¾Ð³Ð¾ Ð·Ð½Ð°ÐºÐ°/ÑÐºÐ¾Ð±ÐºÐ¸/ÑÑ‚Ñ€Ð¾Ñ‡Ð½Ð¾Ð¹ ÑÐ²ÑÐ·ÐºÐ¸ â€” Ð¾Ð±Ñ€Ñ‹Ð²Ð¾Ðº Ð¿Ñ€ÐµÐ´Ð»Ð¾Ð¶ÐµÐ½Ð¸Ñ.
    if ts[:1] in "â€”-â€“Â·â€¢,.;:)]}Â»([{":
        return True
    if _PROSE_MARKERS.search(ts):
        return True
    # Ð‘Ñ€ÐµÐ½Ð´-Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²Ð¾Ðº ÑÑ‚Ñ€Ð°Ð½Ð¸Ñ†Ñ‹ (Ð½Ð°Ð¿Ñ€. Â«Taxlive | WolterskluwerÂ»).
    if ts.casefold() in _BRAND_TITLES:
        return True
    # Ð—Ð°Ð³Ð¾Ð»Ð¾Ð²Ð¾Ðº Ð²Ð¸Ð´Ð° Â«Brand | SectionÂ» Ð¸Ð· <title> â€” ÑÐ»ÑƒÐ¶ÐµÐ±Ð½Ñ‹Ð¹, Ð½Ðµ Ð½Ð¾Ð²Ð¾ÑÑ‚ÑŒ.
    if " | " in ts and len(ts) < 40:
        return True
    return False


def _extract_date_near(text, span_start, span_end, lang):
    """ÐÐ°Ð¹Ñ‚Ð¸ Ð´Ð°Ñ‚Ñƒ (nl/en/iso) Ð² Ð¿Ñ€ÐµÐ´ÐµÐ»Ð°Ñ… Ð¾Ð´Ð½Ð¾Ð¹ HTML-ÐºÐ°Ñ€Ñ‚Ð¾Ñ‡ÐºÐ¸ Ð²Ð¾ÐºÑ€ÑƒÐ³ ÑÑÑ‹Ð»ÐºÐ¸."""
    # Ð£ TaxLive Ð´Ð°Ñ‚Ð° Ð¸Ð´Ñ‘Ñ‚ Ð¿Ð¾ÑÐ»Ðµ description, Ñƒ Ð¤ÐÐ¡ â€” Ð¼ÐµÐ¶Ð´Ñƒ image-link Ð¸
    # Ð¿Ð¾Ð²Ñ‚Ð¾Ñ€Ð½Ð¾Ð¹ title-link. Ð¡Ð½Ð°Ñ‡Ð°Ð»Ð° Ð±ÐµÑ€Ñ‘Ð¼ ÑÐ¿ÐµÑ†Ð¸Ð°Ð»Ð¸Ð·Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹ metadata-Ð¼Ð°Ñ€ÐºÐµÑ€,
    # Ñ‡Ñ‚Ð¾Ð±Ñ‹ Ð´Ð°Ñ‚Ð° ÑÑƒÐ´ÐµÐ±Ð½Ð¾Ð³Ð¾ Ð°ÐºÑ‚Ð° Ð²Ð½ÑƒÑ‚Ñ€Ð¸ description Ð½Ðµ ÑÑ‚Ð°Ð»Ð° Ð´Ð°Ñ‚Ð¾Ð¹ Ð¿ÑƒÐ±Ð»Ð¸ÐºÐ°Ñ†Ð¸Ð¸.
    window = text[max(0, span_start - 100): span_end + 1200]
    metadata = None
    for pattern in (
        r'news__time[^>]*>\s*([^<]{6,40})',
        r'news_date[^>]*>\s*([^<]{6,40})',
        r'wk-icon-calendar[^>]*></span>\s*([^<]{6,40})',
    ):
        mm = re.search(pattern, window, re.IGNORECASE)
        if mm:
            metadata = mm.group(1)
            break
    date_text = metadata or window
    # ISO YYYY-MM-DD
    m = re.search(r"\b(\d{4})-(\d{2})-(\d{2})\b", date_text)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    # 17.07.2026 / 17-07-2026
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{4})\b", date_text)
    if m:
        try:
            return datetime(int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime(
                "%Y-%m-%d"
            )
        except ValueError:
            return ""
    # 17.07.26 (Ð¾Ñ„Ð¸Ñ†Ð¸Ð°Ð»ÑŒÐ½Ñ‹Ð¹ Ð»Ð¸ÑÑ‚Ð¸Ð½Ð³ ÐœÐ¸Ð½Ñ„Ð¸Ð½Ð°)
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2})\b", date_text)
    if m:
        try:
            return datetime(2000 + int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime(
                "%Y-%m-%d"
            )
        except ValueError:
            return ""
    # "09 June, 2026" / "17 juni 2026" / "2 juli 2026"
    m = re.search(r"\b(\d{1,2})\s+([A-Za-zÐ-Ð¯Ð°-Ñ]+),?\s+(\d{4})\b", date_text)
    if m:
        day = int(m.group(1))
        mon_name = m.group(2).casefold()
        year = int(m.group(3))
        mon = NL_MONTHS.get(mon_name) or EN_MONTHS.get(mon_name)
        if mon:
            try:
                return datetime(year, mon, day).strftime("%Y-%m-%d")
            except ValueError:
                return ""
    return ""


def _date_from_title_url(title, url, cfg):
    """Ð˜Ð·Ð²Ð»ÐµÑ‡ÑŒ compact YYYYMMDD Ð¿Ð¾ ÐºÐ¾Ð½Ñ„Ð¸Ð³ÑƒÑ€Ð¸Ñ€ÑƒÐµÐ¼Ð¾Ð¼Ñƒ regex Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ°."""
    pattern = cfg.get("date_from_title")
    if not pattern:
        return ""
    m = re.search(pattern, f"{title} {url}", re.IGNORECASE)
    if not m:
        return ""
    value = m.group(1) if m.groups() else m.group(0)
    try:
        return datetime.strptime(value, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return ""


def _dedup_by_url_title(items):
    """Ð£Ð±Ñ€Ð°Ñ‚ÑŒ Ð¿Ð¾Ð²Ñ‚Ð¾Ñ€Ñ‹ Ð²Ð½ÑƒÑ‚Ñ€Ð¸ Ð¾Ð´Ð½Ð¾Ð³Ð¾ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ° Ð¿Ð¾ (url, Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²Ð¾Ðº)."""
    seen = set()
    out = []
    for it in items:
        key = (it.get("url", ""), it.get("title", "").casefold())
        if key in seen:
            continue
        seen.add(key)
        out.append(it)
    return out


def parse_html_anchors(text, cfg, source_id):
    """Ð Ð°Ð·Ð±Ð¾Ñ€ Ð–Ð˜Ð’ÐžÐ“Ðž HTML (Ð¿Ñ€ÑÐ¼Ð¾Ð¹ Ñ‚Ñ€Ð°Ð½ÑÐ¿Ð¾Ñ€Ñ‚): <a href> Ñ include/exclude Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ°.

    Ð—Ð°Ð³Ð¾Ð»Ð¾Ð²Ð¾Ðº = Ñ‚ÐµÐºÑÑ‚ ÑÑÑ‹Ð»ÐºÐ¸. Ð”Ð°Ñ‚Ñ‹ Ð² Ð»Ð¸ÑÑ‚Ð¸Ð½Ð³Ð°Ñ… Ñ‡Ð°ÑÑ‚Ð¾ Ð½ÐµÑ‚ (garant) â€” Ð¾ÑÑ‚Ð°Ð²Ð»ÑÐµÐ¼
    published_at Ð¿ÑƒÑÑ‚Ñ‹Ð¼, Ð´Ð°Ð»ÑŒÑˆÐµ Ñ€ÐµÑˆÐ°ÐµÑ‚ Ð´ÐµÐ´ÑƒÐ¿ Ð¸ Ð¾ÐºÐ½Ð¾ ÑÐ²ÐµÐ¶ÐµÑÑ‚Ð¸.
    """
    base = cfg["base"]
    ex = _AnchorExtractor()
    try:
        ex.feed(text)
    except Exception:  # Ð±Ð¸Ñ‚Ñ‹Ð¹ HTML Ð½Ðµ Ð´Ð¾Ð»Ð¶ÐµÐ½ Ñ€Ð¾Ð½ÑÑ‚ÑŒ Ð¿Ñ€Ð¾Ð³Ð¾Ð½
        pass
    items = []
    for href, title in ex.links:
        title = clean_text(title)
        if not href or not title:
            continue
        url = urljoin(base, href.strip())
        if _is_nav_title(title) or _is_prose_fragment(title):
            continue
        if not _url_ok(url, cfg):
            continue
        pos = text.find(href)
        published_at = _date_from_title_url(title, url, cfg)
        if not published_at and pos >= 0:
            published_at = _extract_date_near(text, pos, pos + len(href), source_id)
        items.append({"url": url, "ecli": "", "title": title,
                      "summary": "", "published_at": published_at})
    return _dedup_by_url_title(items)


def parse_html_links(text, src_cfg, source_id):
    """Ð˜Ð·Ð²Ð»ÐµÑ‡ÑŒ Ð½Ð¾Ð²Ð¾ÑÑ‚Ð½Ñ‹Ðµ ÑÑÑ‹Ð»ÐºÐ¸ Ð¿Ð¾ Ð¿Ñ€Ð°Ð²Ð¸Ð»Ð°Ð¼ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ°.

    Ð–Ð¸Ð²Ð¾Ð¹ HTML (Ð¿Ñ€ÑÐ¼Ð¾Ð¹ Ñ‚Ñ€Ð°Ð½ÑÐ¿Ð¾Ñ€Ñ‚, ÐµÑÑ‚ÑŒ Ñ‚ÐµÐ³Ð¸ `<a href>`) â†’ parse_html_anchors.
    Markdown-Ð²Ñ‹Ð²Ð¾Ð´ web_fetch (Ð½ÐµÑ‚ Ñ‚ÐµÐ³Ð¾Ð²) â†’ ÑÑ‚Ñ€Ð°Ñ‚ÐµÐ³Ð¸Ð¸ Aâ€“D (fallback-Ñ‚Ñ€Ð°Ð½ÑÐ¿Ð¾Ñ€Ñ‚).
    """
    cfg = html_rules(src_cfg)
    if not cfg["base"] or not cfg["include"]:
        return []
    base = cfg["base"]
    # ÐŸÑ€ÑÐ¼Ð¾Ð¹ Ñ‚Ñ€Ð°Ð½ÑÐ¿Ð¾Ñ€Ñ‚ Ð¾Ñ‚Ð´Ð°Ñ‘Ñ‚ Ð½Ð°ÑÑ‚Ð¾ÑÑ‰Ð¸Ð¹ HTML Ñ Ñ‚ÐµÐ³Ð°Ð¼Ð¸ <a href=â€¦> â€” Ñ€Ð°Ð·Ð±Ð¸Ñ€Ð°ÐµÐ¼ ÐµÐ³Ð¾.
    if re.search(r"<a\s[^>]*href\s*=", text, re.IGNORECASE):
        return parse_html_anchors(text, cfg, source_id)
    lang = src_cfg.get("lang", "en")
    items = []

    # --- Ð¡Ñ‚Ñ€Ð°Ñ‚ÐµÐ³Ð¸Ñ A: markdown-ÑÑÑ‹Ð»ÐºÐ¸ [title](url) -------------------------
    # ÐžÑÐ½Ð¾Ð²Ð½Ð¾Ð¹ Ñ„Ð¾Ñ€Ð¼Ð°Ñ‚ Ð¶Ð¸Ð²Ð¾Ð³Ð¾ web_fetch-Ð²Ñ‹Ð²Ð¾Ð´Ð°.
    for m in re.finditer(r"\[([^\]\n]+)\]\((https?://[^\s)]+|/[^\s)]+)\)", text):
        title = clean_text(m.group(1))
        raw_url = m.group(2).strip()
        url = urljoin(base, raw_url)
        if _is_nav_title(title):
            continue
        if not _url_ok(url, cfg):
            continue
        published_at = _extract_date_near(text, m.start(), m.end(), lang)
        items.append({
            "url": url,
            "ecli": "",
            "title": title,
            "summary": "",
            "published_at": published_at,
        })

    # Ð”Ð»Ñ ÑÑ‚Ñ€Ð°Ñ‚ÐµÐ³Ð¸Ð¹ B Ð¸ C Ñ€Ð°Ð±Ð¾Ñ‚Ð°ÐµÐ¼ Ð¿Ð¾ ÐºÐ¾Ð¿Ð¸Ð¸ Ñ ÑÑ…Ð»Ð¾Ð¿Ð½ÑƒÑ‚Ñ‹Ð¼Ð¸ Ð¿Ñ€Ð¾Ð±ÐµÐ»Ð°Ð¼Ð¸/Ð¿ÐµÑ€ÐµÐ²Ð¾Ð´Ð°Ð¼Ð¸
    # ÑÑ‚Ñ€Ð¾Ðº â€” Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²ÐºÐ¸ Ð² Ñ‚Ð¸Ð·ÐµÑ€Ð°Ñ… Ñ‡Ð°ÑÑ‚Ð¾ Ð¿ÐµÑ€ÐµÐ½Ð¾ÑÑÑ‚ÑÑ Ð½Ð° 2 ÑÑ‚Ñ€Ð¾ÐºÐ¸.
    norm_text = re.sub(r"\s+", " ", text)

    # --- Ð¡Ñ‚Ñ€Ð°Ñ‚ÐµÐ³Ð¸Ñ B: Â«"Ð—Ð°Ð³Ð¾Ð»Ð¾Ð²Ð¾Ðº" ... (Ð´Ð°Ñ‚Ð° | URL)Â» -----------------------
    # Ð’ Ñ„Ð¸ÐºÑÑ‚ÑƒÑ€Ð°Ñ…: "ÐŸÐ¾Ñ€ÑÐ´Ð¾Ðº Ð¾Ð±Ð¼ÐµÐ½Ð°..." â†’ https://www.garant.ru/news/2152202/
    # Ð¸ "Koopsom nieuwe woning..." â€” 2 juli 2026 (Ð±ÐµÐ· ÑÑÑ‹Ð»ÐºÐ¸).
    for m in re.finditer(r'["â€œâ€]([^"â€œâ€]{%d,240}?)["â€œâ€]' % MIN_TITLE_LEN, norm_text):
        title = clean_text(m.group(1))
        if _is_nav_title(title) or _is_prose_fragment(title):
            continue
        # Ð‘Ð»Ð¸Ð¶Ð°Ð¹ÑˆÐ¸Ð¹ URL Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ° Ð² Ð¿Ñ€ÐµÐ´ÐµÐ»Ð°Ñ… ~320 ÑÐ¸Ð¼Ð²Ð¾Ð»Ð¾Ð² Ð¿Ð¾ÑÐ»Ðµ Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²ÐºÐ°.
        tail = norm_text[m.end(): m.end() + 320]
        um = re.search(r"(https?://[^\s)>\]]+)", tail)
        url = ""
        if um:
            cand = um.group(1).rstrip(".,);")
            # ÐžÐ±Ñ€ÐµÐ·Ð°Ð½Ð½Ñ‹Ðµ Ð² Ñ„Ð¸ÐºÑÑ‚ÑƒÑ€Ðµ ÑÑÑ‹Ð»ÐºÐ¸ (â€¦-...) Ð½Ðµ Ð±ÐµÑ€Ñ‘Ð¼ ÐºÐ°Ðº Ñ€ÐµÐ°Ð»ÑŒÐ½Ñ‹Ð¹ URL.
            if not cand.endswith("...") and _url_ok(cand, cfg):
                url = urljoin(base, cand)
        published_at = _extract_date_near(norm_text, m.start(), m.end(), lang)
        # ÐÑƒÐ¶ÐµÐ½ ÑÐºÐ¾Ñ€ÑŒ: Ð»Ð¸Ð±Ð¾ Ð²Ð°Ð»Ð¸Ð´Ð½Ñ‹Ð¹ URL, Ð»Ð¸Ð±Ð¾ Ð´Ð°Ñ‚Ð° Ñ€ÑÐ´Ð¾Ð¼.
        if not url and not published_at:
            continue
        items.append({
            "url": url,
            "ecli": "",
            "title": title,
            "summary": "",
            "published_at": published_at,
        })

    # --- Ð¡Ñ‚Ñ€Ð°Ñ‚ÐµÐ³Ð¸Ñ C: markdown-Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²ÐºÐ¸ '## Title' + Ð´Ð°Ñ‚Ð° Ñ€ÑÐ´Ð¾Ð¼ -----------
    for m in re.finditer(r"(?m)^#{1,4}\s+(.+?)\s*$", text):
        title = clean_text(m.group(1))
        if _is_nav_title(title) or _is_prose_fragment(title):
            continue
        published_at = _extract_date_near(text, m.start(), m.end(), lang)
        if not published_at:
            continue
        items.append({
            "url": "",
            "ecli": "",
            "title": title,
            "summary": "",
            "published_at": published_at,
        })

    # --- Ð¡Ñ‚Ñ€Ð°Ñ‚ÐµÐ³Ð¸Ñ D: URL-ÑÐºÐ¾Ñ€ÑŒ â†’ Ð±Ð»Ð¸Ð¶Ð°Ð¹ÑˆÐ¸Ð¹ Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²Ð¾Ðº Ð² ÐºÐ°Ð²Ñ‹Ñ‡ÐºÐ°Ñ… ÑÐ»ÐµÐ²Ð° ------
    # Ð£ÑÑ‚Ð¾Ð¹Ñ‡Ð¸Ð²Ñ‹Ð¹ Ñ€Ð°Ð·Ð±Ð¾Ñ€ Ð¿Ð°Ñ€Ñ‹ Â«"Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²Ð¾Ðº" â†’ https://.../news/IDÂ» Ð´Ð°Ð¶Ðµ ÐºÐ¾Ð³Ð´Ð°
    # Ð¿Ð°Ñ€Ð½Ð¾ÑÑ‚ÑŒ ÐºÐ°Ð²Ñ‹Ñ‡ÐµÐº Ð² Ð¾Ð¿Ð¸ÑÐ°Ñ‚ÐµÐ»ÑŒÐ½Ð¾Ð¼ Ñ‚ÐµÐºÑÑ‚Ðµ Â«ÑÑŠÐµÐ·Ð¶Ð°ÐµÑ‚Â». Ð Ð°Ð±Ð¾Ñ‚Ð°ÐµÑ‚ Ð´Ð»Ñ Ð»ÑŽÐ±Ð¾Ð³Ð¾
    # Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ° ÑÐ¾ ÑÑ‚Ð°Ñ‚ÐµÐ¹Ð½Ñ‹Ð¼Ð¸ URL (include-Ð¿Ð°Ñ‚Ñ‚ÐµÑ€Ð½ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ° Ñ€ÐµÑˆÐ°ÐµÑ‚).
    for um in re.finditer(r"https?://[^\s)>\]]+", norm_text):
        cand = um.group(0).rstrip(".,);")
        if cand.endswith("...") or not _url_ok(cand, cfg):
            continue
        url = urljoin(base, cand)
        # Ð—Ð°Ð³Ð¾Ð»Ð¾Ð²Ð¾Ðº â€” Ñ‚ÐµÐºÑÑ‚ Ð¼ÐµÐ¶Ð´Ñƒ Ð”Ð’Ð£ÐœÐ¯ Ð¿Ð¾ÑÐ»ÐµÐ´Ð½Ð¸Ð¼Ð¸ ÐºÐ°Ð²Ñ‹Ñ‡ÐºÐ°Ð¼Ð¸ ÑÐ»ÐµÐ²Ð° Ð¾Ñ‚ URL
        # (Ð¾ÐºÐ½Ð¾ ~300). Ð‘ÐµÑ€Ñ‘Ð¼ Ð¿Ð¾ Ð¿Ð¾Ð·Ð¸Ñ†Ð¸ÑÐ¼ ÑÐ°Ð¼Ð¸Ñ… ÐºÐ°Ð²Ñ‹Ñ‡ÐµÐº, Ð½Ðµ Ð¿Ð¾Ð»Ð°Ð³Ð°ÑÑÑŒ Ð½Ð°
        # Ð³Ð»Ð¾Ð±Ð°Ð»ÑŒÐ½ÑƒÑŽ Ð¿Ð°Ñ€Ð½Ð¾ÑÑ‚ÑŒ (Ð² Ð¾Ð¿Ð¸ÑÐ°Ñ‚ÐµÐ»ÑŒÐ½Ð¾Ð¼ Ñ‚ÐµÐºÑÑ‚Ðµ Ð¾Ð½Ð° Â«ÑÑŠÐµÐ·Ð¶Ð°ÐµÑ‚Â»).
        left = norm_text[max(0, um.start() - 300): um.start()]
        qpos = [i for i, ch in enumerate(left) if ch in '"â€œâ€']
        if len(qpos) < 2:
            continue
        title = clean_text(left[qpos[-2] + 1: qpos[-1]])
        if _is_nav_title(title) or _is_prose_fragment(title):
            continue
        published_at = _extract_date_near(norm_text, um.start(), um.end(), lang)
        items.append({
            "url": url,
            "ecli": "",
            "title": title,
            "summary": "",
            "published_at": published_at,
        })

    items = _dedup_by_url_title(items)
    return items


# =============================================================================
#  Ð”Ð˜Ð¡ÐŸÐ•Ð¢Ð§Ð•Ð 
# =============================================================================
def dispatch(text, src_cfg, source_id):
    """Ð’Ñ‹Ð±Ñ€Ð°Ñ‚ÑŒ Ð¿Ð°Ñ€ÑÐµÑ€ Ð¿Ð¾ src_cfg['parser'] Ð¸ Ð²ÐµÑ€Ð½ÑƒÑ‚ÑŒ ÑÐ¿Ð¸ÑÐ¾Ðº ÑÑ‹Ñ€Ñ‹Ñ… ÑÐ»ÐµÐ¼ÐµÐ½Ñ‚Ð¾Ð²."""
    parser = src_cfg.get("parser", "none")
    if parser == "rechtspraak_atom":
        return parse_rechtspraak_atom(text, src_cfg)
    if parser == "auto":
        if re.search(r"<\s*(?:rss|feed)\b", text[:1000], re.IGNORECASE):
            return parse_rss_atom(text, src_cfg)
        return parse_html_links(text, src_cfg, source_id)
    if parser in ("html_links",):
        return parse_html_links(text, src_cfg, source_id)
    if parser in ("rss", "atom"):
        return parse_rss_atom(text, src_cfg)
    if parser == "json_items":
        return parse_json_items(text, src_cfg)
    if parser == "vs_ajax_json":
        return parse_vs_ajax_json(text, src_cfg)
    # parser == none (chrome-Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¸) â€” Ð·Ð´ÐµÑÑŒ Ð½Ðµ Ð¿Ð°Ñ€ÑÐ¸Ð¼.
    return []


def source_id_from_filename(fname):
    """Ð˜Ð· Ð¸Ð¼ÐµÐ½Ð¸ '{source_id}_{n}.txt' Ð¸Ð·Ð²Ð»ÐµÑ‡ÑŒ source_id (ÑƒÑ‡Ð¸Ñ‚Ñ‹Ð²Ð°Ñ Ð¿Ð¾Ð´Ñ‡Ñ‘Ñ€ÐºÐ¸Ð²Ð°Ð½Ð¸Ñ Ð² id)."""
    base = os.path.basename(fname)
    base = re.sub(r"\.txt$", "", base, flags=re.IGNORECASE)
    # ÐžÑ‚Ñ€ÐµÐ·Ð°ÐµÐ¼ Ñ…Ð²Ð¾ÑÑ‚Ð¾Ð²Ð¾Ð¹ _{Ñ‡Ð¸ÑÐ»Ð¾}, Ð¾ÑÑ‚Ð°Ð»ÑŒÐ½Ð¾Ðµ â€” id Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ°.
    m = re.match(r"^(.*)_(\d+)$", base)
    return m.group(1) if m else base


def run(date, root):
    """Ð Ð°Ð·Ð¾Ð±Ñ€Ð°Ñ‚ÑŒ Ð²ÑÐµ pipeline/raw/{date}/*.txt Ð¸ Ð·Ð°Ð¿Ð¸ÑÐ°Ñ‚ÑŒ inbox jsonl. Ð’Ð¾Ð·Ð²Ñ€Ð°Ñ‰Ð°ÐµÑ‚ stats."""
    raw_dir = os.path.join(root, "pipeline", "raw", date)
    inbox_dir = os.path.join(root, "pipeline", "inbox")
    os.makedirs(inbox_dir, exist_ok=True)
    out_path = os.path.join(inbox_dir, f"{date}_items.jsonl")

    sources = load_sources(root)
    files = sorted(glob.glob(os.path.join(raw_dir, "*.txt")))

    stats = {}  # source_id -> {"items": n, "status": str}
    all_items = []

    if not files:
        print(f"[parse] Ð½ÐµÑ‚ ÑÑ‹Ñ€Ñ‹Ñ… Ñ„Ð°Ð¹Ð»Ð¾Ð² Ð² {raw_dir}", file=sys.stderr)

    for fpath in files:
        sid = source_id_from_filename(fpath)
        src_cfg = sources.get(sid)
        entry = stats.setdefault(sid, {"items": 0, "status": "ok"})
        if src_cfg is None:
            entry["status"] = "unknown_source"
            print(f"[parse] {sid}: Ð½ÐµÐ¸Ð·Ð²ÐµÑÑ‚Ð½Ñ‹Ð¹ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº (Ð½ÐµÑ‚ Ð² sources.yaml) â€” Ð¿Ñ€Ð¾Ð¿ÑƒÑÐº")
            continue
        try:
            text = read_raw_text(fpath)
        except OSError as e:
            entry["status"] = f"read_error:{e}"
            print(f"[parse] {sid}: Ð¾ÑˆÐ¸Ð±ÐºÐ° Ñ‡Ñ‚ÐµÐ½Ð¸Ñ {fpath}: {e}")
            continue

        if looks_like_binary(text):
            entry["status"] = "binary_or_empty"
            print(f"[parse] {sid}: Ð¿ÑƒÑÑ‚Ð¾Ð¹/binary Ñ„Ð¸ÐºÑÑ‚ÑƒÑ€ â€” 0 ÑÐ»ÐµÐ¼ÐµÐ½Ñ‚Ð¾Ð² (Ð½Ðµ Ð¿Ð°Ð´Ð°ÐµÐ¼)")
            continue

        try:
            raw_items = dispatch(text, src_cfg, sid)
        except Exception as e:  # Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº Ð½Ðµ Ð´Ð¾Ð»Ð¶ÐµÐ½ Ñ€Ð¾Ð½ÑÑ‚ÑŒ Ð¿Ñ€Ð¾Ð³Ð¾Ð½
            entry["status"] = f"parse_error:{type(e).__name__}"
            print(f"[parse] {sid}: Ð¾ÑˆÐ¸Ð±ÐºÐ° Ð¿Ð°Ñ€ÑÐ¸Ð½Ð³Ð°: {type(e).__name__}: {e}")
            continue

        lang = src_cfg.get("lang", "en")
        n = 0
        for it in raw_items:
            title = it.get("title", "").strip()
            if not title:
                continue
            rec = {
                "source": sid,
                "url": it.get("url", "") or "",
                "ecli": it.get("ecli", "") or "",
                "act": it.get("act", "") or it.get("case_number", "") or "",
                "title": title,
                "summary": it.get("summary", "") or "",
                "published_at": it.get("published_at", "") or "",
                "lang": lang,
            }
            for key in ("item_type", "lead", "channel", "message_id",
                        "views", "reactions", "forwards", "engagement"):
                if key in it:
                    rec[key] = it[key]
            all_items.append(rec)
            n += 1
        entry["items"] += n
        print(f"[parse] {sid}: {n} ÑÐ»ÐµÐ¼ÐµÐ½Ñ‚Ð¾Ð² ({entry['status']})")

    with open(out_path, "w", encoding="utf-8") as f:
        for rec in all_items:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    exported, registry_path = upsert_court_decisions(root, date, all_items)
    if exported:
        print(f"[parse] court_registry: {exported} Ñ€ÐµÑˆÐµÐ½Ð¸Ð¹ â†’ {registry_path}")

    total = len(all_items)
    print(f"[parse] Ð˜Ð¢ÐžÐ“Ðž {total} ÑÐ»ÐµÐ¼ÐµÐ½Ñ‚Ð¾Ð² â†’ {out_path}")
    return {"out_path": out_path, "total": total, "per_source": stats}


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="ÐŸÐ°Ñ€ÑÐ¸Ð½Ð³ ÑÑ‹Ñ€Ñ‹Ñ… Ð¾Ñ‚Ð²ÐµÑ‚Ð¾Ð² Ð² inbox jsonl.")
    ap.add_argument("--date", required=True, help="Ð”Ð°Ñ‚Ð° Ð¿Ñ€Ð¾Ð³Ð¾Ð½Ð° YYYY-MM-DD.")
    ap.add_argument("--root", default=".", help="ÐšÐ¾Ñ€ÐµÐ½ÑŒ Ð¿Ñ€Ð¾ÐµÐºÑ‚Ð°.")
    args = ap.parse_args()
    run(args.date, args.root)


if __name__ == "__main__":
    main()

