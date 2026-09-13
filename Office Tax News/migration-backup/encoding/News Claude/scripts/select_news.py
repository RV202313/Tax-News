#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Ð¡ÐºÐ¾Ñ€Ð¸Ð½Ð³ Ð¸ Ð¾Ñ‚Ð±Ð¾Ñ€ Ð½Ð¾Ð²Ð¾ÑÑ‚ÐµÐ¹ â†’ pipeline/shortlist/{date}_shortlist.json. Stdlib + PyYAML."""

import argparse
import difflib
import json
import math
import os
import re
import sys
from datetime import date as date_cls
from datetime import datetime, timezone
from pathlib import Path

try:
    import yaml
except ImportError:  # pragma: no cover
    print("ÐÑƒÐ¶ÐµÐ½ PyYAML. Ð£ÑÑ‚Ð°Ð½Ð¾Ð²ÐºÐ°: pip install pyyaml --break-system-packages", file=sys.stderr)
    sys.exit(2)

import newsdb  # Ð»Ð¾ÐºÐ°Ð»ÑŒÐ½Ñ‹Ð¹ Ð¼Ð¾Ð´ÑƒÐ»ÑŒ ÑÐ¾ÑÑ‚Ð¾ÑÐ½Ð¸Ñ

# Ð’ÐµÑ Ð¿Ñ€Ð¸Ð¾Ñ€Ð¸Ñ‚ÐµÑ‚Ð° Ñ‚ÐµÐ¼Ñ‹.
PRIORITY_WEIGHT = {1: 3.0, 2: 2.0, 3: 1.0}
# Ð‘Ð¾Ð½ÑƒÑ Ð·Ð° ÑÐ²ÐµÐ¶ÐµÑÑ‚ÑŒ (Ð¿ÑƒÐ±Ð»Ð¸ÐºÐ°Ñ†Ð¸Ñ Ð·Ð° Ð¿Ð¾ÑÐ»ÐµÐ´Ð½Ð¸Ðµ 24 Ñ‡Ð°ÑÐ°).
FRESHNESS_BONUS = 0.5
# Ð¡ÑƒÐ´ÐµÐ±Ð½Ñ‹Ðµ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¸ â€” Ð¾ÑÐ¾Ð±Ñ‹Ðµ Ð¿Ñ€Ð°Ð²Ð¸Ð»Ð° Ð¿Ñ€Ð¾Ñ…Ð¾Ð¶Ð´ÐµÐ½Ð¸Ñ.
COURT_SOURCES = {"nl_rechtspraak", "ru_ras", "ru_vs"}
DEFAULT_UNSCOPED_CAP = 1
DEFAULT_THIRD_LINE_CAP = 2
# ÐŸÑ€Ð¸Ð¾Ñ€Ð¸Ñ‚ÐµÑ‚ Ð¿Ð¾ ÑƒÐ¼Ð¾Ð»Ñ‡Ð°Ð½Ð¸ÑŽ Ð´Ð»Ñ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð² Ñ ÑÐµÑ€Ð²ÐµÑ€Ð½Ð¾Ð¹ Ð¿Ñ€ÐµÐ´Ñ„Ð¸Ð»ÑŒÑ‚Ñ€Ð°Ñ†Ð¸ÐµÐ¹ Ñ‚ÐµÐ¼Ñ‹
# (prefiltered: true Ð² sources.yaml): ÑÐµÑ€Ð²ÐµÑ€ ÑƒÐ¶Ðµ Ð¾Ñ‚Ð¾Ð±Ñ€Ð°Ð» Ð¿Ð¾ Ñ‚ÐµÐ¼Ðµ, Ð¿Ð¾ÑÑ‚Ð¾Ð¼Ñƒ Ñ‚Ð°ÐºÐ¾Ð¹
# Ð¼Ð°Ñ‚ÐµÑ€Ð¸Ð°Ð» Ð¿Ñ€Ð¾Ñ…Ð¾Ð´Ð¸Ñ‚ Ð³ÐµÐ¹Ñ‚ Ð¸ Ð±ÐµÐ· Ð¼Ð°Ñ‚Ñ‡Ð° ÐºÐ»ÑŽÑ‡ÐµÐ²Ñ‹Ñ… ÑÐ»Ð¾Ð² â€” Ñ ÑÑ‚Ð¸Ð¼ Ð¿Ñ€Ð¸Ð¾Ñ€Ð¸Ñ‚ÐµÑ‚Ð¾Ð¼.
PREFILTERED_DEFAULT_PRIORITY = 2

# ÐŸÑ€Ð°Ð²Ð¸Ð»Ð° Ð¿Ñ€ÐµÐ´Ð»Ð¾Ð¶ÐµÐ½Ð½Ñ‹Ñ… ÐºÐ°Ð½Ð°Ð»Ð¾Ð² Ð¿Ð¾ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÑƒ.
RU_NEWS_SOURCES = {"ru_garant", "ru_fns", "ru_minfin", "ru_vs"}
NL_EN_MEDIA = {"intl_regfollower", "nl_taxlive", "nl_taxence", "nl_fd"}


def load_yaml(path):
    """ÐŸÑ€Ð¾Ñ‡Ð¸Ñ‚Ð°Ñ‚ÑŒ YAML-Ñ„Ð°Ð¹Ð» Ð² Ð¾Ð±ÑŠÐµÐºÑ‚."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_topics(root):
    """Ð¡Ð¿Ð¸ÑÐ¾Ðº Ñ‚ÐµÐ¼ Ñ Ð¿Ð»Ð¾ÑÐºÐ¸Ð¼ Ð½Ð°Ð±Ð¾Ñ€Ð¾Ð¼ ÐºÐ»ÑŽÑ‡ÐµÐ²Ñ‹Ñ… ÑÐ»Ð¾Ð² (ru+nl+en+plain)."""
    data = load_yaml(os.path.join(root, "config", "topics.yaml"))
    topics = []
    for t in data.get("topics", []):
        kws = []
        for key in ("keywords_ru", "keywords_nl", "keywords_en", "keywords"):
            for kw in t.get(key, []) or []:
                kw = str(kw).strip()
                if kw:
                    kws.append(kw.casefold())
        topics.append({
            "id": t["id"],
            "priority": int(t.get("priority", 3)),
            "keywords": kws,
        })
    return topics


def load_source_weights(root):
    """Ð’ÐµÑÐ° Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð² Ð¸Ð· sources.yaml â†’ {source_id: weight}."""
    data = load_yaml(os.path.join(root, "config", "sources.yaml"))
    out = {}
    for s in data.get("sources", []):
        out[s["id"]] = float(s.get("weight", 1.0))
    return out


def load_source_windows(root):
    """ÐžÐºÐ½Ð¾ ÑÐ²ÐµÐ¶ÐµÑÑ‚Ð¸ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð² Ð¸Ð· sources.yaml â†’ {source_id: window_days}."""
    data = load_yaml(os.path.join(root, "config", "sources.yaml"))
    default_h = int((data.get("defaults") or {}).get("window_hours", 48))
    out = {"__default__": max(1, (default_h + 23) // 24)}
    for s in data.get("sources", []):
        h = int(s.get("window_hours", default_h))
        out[s["id"]] = max(1, (h + 23) // 24)
    return out


def load_prefiltered(root):
    """ÐœÐ½Ð¾Ð¶ÐµÑÑ‚Ð²Ð¾ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð² Ñ ÑÐµÑ€Ð²ÐµÑ€Ð½Ð¾Ð¹ Ð¿Ñ€ÐµÐ´Ñ„Ð¸Ð»ÑŒÑ‚Ñ€Ð°Ñ†Ð¸ÐµÐ¹ Ñ‚ÐµÐ¼Ñ‹ (prefiltered: true)."""
    data = load_yaml(os.path.join(root, "config", "sources.yaml"))
    out = set()
    for s in data.get("sources", []):
        if s.get("prefiltered"):
            out.add(s["id"])
    return out


def load_default_topics(root):
    """Ð¢ÐµÐ¼Ð° Ð¿Ð¾ ÑƒÐ¼Ð¾Ð»Ñ‡Ð°Ð½Ð¸ÑŽ Ð´Ð»Ñ ÑÐµÑ€Ð²ÐµÑ€Ð½Ð¾ Ð¿Ñ€ÐµÐ´Ñ„Ð¸Ð»ÑŒÑ‚Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ñ… Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð²."""
    data = load_yaml(os.path.join(root, "config", "sources.yaml"))
    return {
        source["id"]: source.get("default_topic", "nl_fiscaal")
        for source in data.get("sources", [])
        if source.get("prefiltered")
    }


def load_required_topics(root):
    """Ð“ÐµÐ¹Ñ‚Ñ‹ ÑˆÐ¸Ñ€Ð¾ÐºÐ¸Ñ… Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð²: {source_id: {Ð¾Ð±ÑÐ·Ð°Ñ‚ÐµÐ»ÑŒÐ½Ñ‹Ðµ topic_id}}."""
    data = load_yaml(os.path.join(root, "config", "sources.yaml"))
    out = {}
    for source in data.get("sources", []):
        required = {
            str(topic_id).strip()
            for topic_id in source.get("require_topics_any", []) or []
            if str(topic_id).strip()
        }
        if required:
            out[source["id"]] = required
    return out


def load_source_text_excludes(root):
    """ÐšÐ¾Ð½Ñ„Ð¸Ð³ÑƒÑ€Ð°Ñ†Ð¸Ð¾Ð½Ð½Ñ‹Ðµ regex Ð´Ð»Ñ Ð¾Ñ‚ÑÐµÑ‡ÐµÐ½Ð¸Ñ Ñ€ÐµÐºÐ»Ð°Ð¼Ñ‹/ÐºÑƒÑ€ÑÐ¾Ð² Ð¿Ð¾ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÑƒ."""
    data = load_yaml(os.path.join(root, "config", "sources.yaml"))
    return {
        source["id"]: list(source.get("exclude_text") or [])
        for source in data.get("sources", [])
        if source.get("exclude_text")
    }


def load_jurisdictions(root):
    """Ð—Ð°Ð³Ñ€ÑƒÐ·Ð¸Ñ‚ÑŒ ÐºÐ°Ñ€Ñ‚Ñƒ ÑŽÑ€Ð¸ÑÐ´Ð¸ÐºÑ†Ð¸Ð¹; ÐµÑÐ»Ð¸ Ñ„Ð°Ð¹Ð»Ð° Ð½ÐµÑ‚, Ð²ÐµÑ€Ð½ÑƒÑ‚ÑŒ Ð¼ÑÐ³ÐºÐ¸Ðµ defaults."""
    path = os.path.join(root, "config", "jurisdictions.yaml")
    if not os.path.exists(path):
        return {
            "jurisdictions": [],
            "source_map": {},
            "unscoped_cap": DEFAULT_UNSCOPED_CAP,
            "third_line_cap": DEFAULT_THIRD_LINE_CAP,
        }
    data = load_yaml(path) or {}
    jurisdictions = []
    source_map = {}
    for j in data.get("jurisdictions", []) or []:
        kws = []
        for kw in j.get("keywords", []) or []:
            kw = str(kw).strip()
            if kw:
                kws.append(kw.casefold())
        rec = {
            "id": j["id"],
            "name": j.get("name", j["id"]),
            "tier": j.get("tier", ""),
            "weight": float(j.get("weight", 0.0)),
            "keywords": kws,
        }
        jurisdictions.append(rec)
        for sid in j.get("source_ids", []) or []:
            source_map.setdefault(sid, []).append(rec)
    defaults = data.get("defaults") or {}
    return {
        "jurisdictions": jurisdictions,
        "source_map": source_map,
        "unscoped_cap": int(defaults.get("unscoped_cap", DEFAULT_UNSCOPED_CAP)),
        "third_line_cap": int(defaults.get("third_line_cap", DEFAULT_THIRD_LINE_CAP)),
    }


def age_days(published_at, run_date):
    """Ð’Ð¾Ð·Ñ€Ð°ÑÑ‚ Ð¼Ð°Ñ‚ÐµÑ€Ð¸Ð°Ð»Ð° Ð² Ð´Ð½ÑÑ… Ð¾Ñ‚Ð½Ð¾ÑÐ¸Ñ‚ÐµÐ»ÑŒÐ½Ð¾ Ð´Ð°Ñ‚Ñ‹ Ð¿Ñ€Ð¾Ð³Ð¾Ð½Ð°; None ÐµÑÐ»Ð¸ Ð´Ð°Ñ‚Ð° Ð½ÐµÐ¸Ð·Ð²ÐµÑÑ‚Ð½Ð°/ÐºÑ€Ð¸Ð²Ð°Ñ."""
    if not published_at:
        return None
    try:
        pub = datetime.strptime(published_at[:10], "%Y-%m-%d").date()
        rd = datetime.strptime(run_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (rd - pub).days


def load_inbox(root, date):
    """ÐŸÑ€Ð¾Ñ‡Ð¸Ñ‚Ð°Ñ‚ÑŒ pipeline/inbox/{date}_items.jsonl â†’ ÑÐ¿Ð¸ÑÐ¾Ðº dict."""
    path = os.path.join(root, "pipeline", "inbox", f"{date}_items.jsonl")
    items = []
    if not os.path.exists(path):
        print(f"[select] Ð½ÐµÑ‚ inbox-Ñ„Ð°Ð¹Ð»Ð° {path}", file=sys.stderr)
        return items
    with open(path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                items.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return items


def match_topics(text, topics):
    """Ð¡Ð¾Ð¿Ð¾ÑÑ‚Ð°Ð²Ð¸Ñ‚ÑŒ Ñ‚ÐµÐ¼Ñ‹ Ð¿Ð¾ Ð²Ñ…Ð¾Ð¶Ð´ÐµÐ½Ð¸ÑŽ ÐºÐ»ÑŽÑ‡ÐµÐ²Ñ‹Ñ… ÑÐ»Ð¾Ð² (casefold substring).

    Ð’Ð¾Ð·Ð²Ñ€Ð°Ñ‰Ð°ÐµÑ‚ (best_priority, best_weight, matched_topic_ids, any_tax_hit).
    """
    hay = text.casefold()
    matched = []
    best_priority = None
    for t in topics:
        for kw in t["keywords"]:
            if kw and kw in hay:
                matched.append(t["id"])
                if best_priority is None or t["priority"] < best_priority:
                    best_priority = t["priority"]
                break
    matched = sorted(set(matched))
    any_hit = len(matched) > 0
    if best_priority is None:
        return None, 0.0, matched, any_hit
    return best_priority, PRIORITY_WEIGHT.get(best_priority, 1.0), matched, any_hit


def match_jurisdictions(text, source_id, jcfg):
    """ÐÐ°Ð¹Ñ‚Ð¸ ÑŽÑ€Ð¸ÑÐ´Ð¸ÐºÑ†Ð¸Ð¸ Ð¿Ð¾ source_id Ð¸ ÐºÐ»ÑŽÑ‡ÐµÐ²Ñ‹Ð¼ ÑÐ»Ð¾Ð²Ð°Ð¼ Ð² Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²ÐºÐµ/Ð°Ð½Ð½Ð¾Ñ‚Ð°Ñ†Ð¸Ð¸."""
    hay = text.casefold()

    def has_keyword(kw):
        if len(kw) <= 3 and re.fullmatch(r"[\w%.-]+", kw, re.IGNORECASE):
            return re.search(rf"(?<!\w){re.escape(kw)}(?!\w)", hay, re.IGNORECASE) is not None
        return kw in hay

    matches = {}
    for j in jcfg.get("source_map", {}).get(source_id, []):
        matches[j["id"]] = j
    for j in jcfg.get("jurisdictions", []):
        if any(kw and has_keyword(kw) for kw in j["keywords"]):
            matches[j["id"]] = j

    found = sorted(matches.values(), key=lambda j: (j["weight"], j["id"]), reverse=True)
    ids = [j["id"] for j in found]
    names = [j["name"] for j in found]
    weight = max((j["weight"] for j in found), default=0.0)
    tiers = sorted({j["tier"] for j in found if j["tier"]})
    primary_tier = found[0]["tier"] if found else ""
    return ids, names, weight, tiers, primary_tier


def is_fresh(published_at, run_date):
    """ÐžÐ¿ÑƒÐ±Ð»Ð¸ÐºÐ¾Ð²Ð°Ð½Ð¾ Ð»Ð¸ Ð² Ð¿Ñ€ÐµÐ´ÐµÐ»Ð°Ñ… 24Ñ‡ Ð´Ð¾ Ð´Ð°Ñ‚Ñ‹ Ð¿Ñ€Ð¾Ð³Ð¾Ð½Ð° (Ð¿Ð¾ Ð´Ð°Ñ‚Ð°Ð¼, Ð±ÐµÐ· Ð²Ñ€ÐµÐ¼ÐµÐ½Ð¸ â€” ÐºÐ¾Ð½ÑÐµÑ€Ð²Ð°Ñ‚Ð¸Ð²Ð½Ð¾)."""
    if not published_at:
        return False
    try:
        pub = datetime.strptime(published_at[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    try:
        rd = datetime.strptime(run_date, "%Y-%m-%d").date()
    except ValueError:
        rd = date_cls.today()
    delta = (rd - pub).days
    return 0 <= delta <= 1


def suggested_channels(source_id):
    """ÐŸÑ€ÐµÐ´Ð»Ð¾Ð¶ÐµÐ½Ð½Ñ‹Ðµ ÐºÐ°Ð½Ð°Ð»Ñ‹ Ð¿ÑƒÐ±Ð»Ð¸ÐºÐ°Ñ†Ð¸Ð¸ Ð¿Ð¾ Ð¿Ñ€Ð°Ð²Ð¸Ð»Ð°Ð¼ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ°."""
    if source_id in COURT_SOURCES:
        return ["telegram_channel"]
    if source_id in RU_NEWS_SOURCES:
        return ["telegram_channel", "vk"]
    if source_id in NL_EN_MEDIA:
        return ["telegram_channel"]
    # ÐŸÐ¾ ÑƒÐ¼Ð¾Ð»Ñ‡Ð°Ð½Ð¸ÑŽ â€” ÐºÐ¾Ð½ÑÐµÑ€Ð²Ð°Ñ‚Ð¸Ð²Ð½Ð¾, Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ð¾ÑÐ½Ð¾Ð²Ð½Ð¾Ð¹ ÐºÐ°Ð½Ð°Ð».
    return ["telegram_channel"]


def run(date, top, root):
    """ÐŸÐ¾Ð»Ð½Ñ‹Ð¹ Ð¿Ñ€Ð¾Ñ…Ð¾Ð´ Ð¾Ñ‚Ð±Ð¾Ñ€Ð°: ÑÐºÐ¾Ñ€Ð¸Ð½Ð³, Ð´ÐµÐ´ÑƒÐ¿, ÐºÐ°Ð¿, Ð·Ð°Ð¿Ð¸ÑÑŒ shortlist, Ð°Ð¿Ð´ÐµÐ¹Ñ‚ runs."""
    conn = newsdb.connect(root)
    try:
        return _run_connected(date, top, root, conn)
    finally:
        newsdb.close(conn)


def _run_connected(date, top, root, conn):
    """Ð’Ñ‹Ð¿Ð¾Ð»Ð½Ð¸Ñ‚ÑŒ Ð¾Ñ‚Ð±Ð¾Ñ€ Ð½Ð° Ð¾Ñ‚ÐºÑ€Ñ‹Ñ‚Ð¾Ð¼ newsdb-ÑÐ¾ÐµÐ´Ð¸Ð½ÐµÐ½Ð¸Ð¸."""
    topics = load_topics(root)
    weights = load_source_weights(root)
    windows = load_source_windows(root)
    prefiltered_sources = load_prefiltered(root)
    default_topics = load_default_topics(root)
    required_topics = load_required_topics(root)
    source_text_excludes = load_source_text_excludes(root)
    jcfg = load_jurisdictions(root)
    inbox = load_inbox(root, date)
    catalog_path = Path(root).resolve().parent / "ÐžÐŸÐ£Ð‘Ð›Ð˜ÐšÐžÐ’ÐÐÐÐ«Ð•_ÐÐžÐ’ÐžÐ¡Ð¢Ð˜.md"
    if catalog_path.exists():
        n_catalog = newsdb.ingest_published_catalog(conn, str(catalog_path))
        print(f"[select] ÐºÐ°Ñ‚Ð°Ð»Ð¾Ð³ Ð¿ÑƒÐ±Ð»Ð¸ÐºÐ°Ñ†Ð¸Ð¹: {n_catalog} ÑÑ‚Ñ€Ð¾Ðº Ð¿Ñ€Ð¾Ð¸Ð½Ð´ÐµÐºÑÐ¸Ñ€Ð¾Ð²Ð°Ð½Ð¾")

    n_collected_new = 0
    n_stale = 0
    scored = []  # ÑÐ¿Ð¸ÑÐ¾Ðº ÐºÐ°Ð½Ð´Ð¸Ð´Ð°Ñ‚Ð¾Ð² Ñ Ð¿Ð¾Ð»ÑÐ¼Ð¸ ÑÐºÐ¾Ñ€Ð¸Ð½Ð³Ð°

    for rec in inbox:
        source = rec.get("source", "")
        title = rec.get("title", "") or ""
        summary = rec.get("summary", "") or ""
        url = rec.get("url", "") or ""
        ecli = newsdb.normalize_ecli(rec.get("ecli", ""))
        act = rec.get("act", "") or rec.get("case_number", "") or ""
        act_norm = newsdb.normalize_title(act)
        published_at = rec.get("published_at", "") or ""
        lead = bool(rec.get("lead"))
        try:
            engagement = max(0.0, float(rec.get("engagement", 0) or 0))
        except (TypeError, ValueError):
            engagement = 0.0

        # Ð–Ñ‘ÑÑ‚ÐºÐ¾Ðµ Ð¾ÐºÐ½Ð¾ ÑÐ²ÐµÐ¶ÐµÑÑ‚Ð¸: Ð´Ð°Ñ‚Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ð¹ Ð¼Ð°Ñ‚ÐµÑ€Ð¸Ð°Ð» ÑÑ‚Ð°Ñ€ÑˆÐµ Ð¾ÐºÐ½Ð° Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ°
        # Ð² Ð¿Ð¾Ð´Ð±Ð¾Ñ€ÐºÑƒ Ð½Ðµ Ð¸Ð´Ñ‘Ñ‚ (ÐºÑÑˆ-ÑÐ½Ð°Ð¿ÑˆÐ¾Ñ‚Ñ‹ CDN Ð¸ Ð¿ÐµÑ€ÐµÐ¿ÐµÑ‡Ð°Ñ‚ÐºÐ¸ ÑÑ‚Ð°Ñ€ÑŒÑ).
        # ÐœÐ°Ñ‚ÐµÑ€Ð¸Ð°Ð»Ñ‹ Ð±ÐµÐ· Ð´Ð°Ñ‚Ñ‹ ÑÐ¾Ñ…Ñ€Ð°Ð½ÑÐµÐ¼ â€” Ð¿Ð¾ Ð½Ð¸Ð¼ Ñ€ÐµÑˆÐ°ÐµÑ‚ Ð´ÐµÐ´ÑƒÐ¿ Ð¸ ÑÐºÐ¾Ñ€Ð¸Ð½Ð³.
        age = age_days(published_at, date)
        if age is not None and age > windows.get(source, windows["__default__"]):
            n_stale += 1
            continue

        text = f"{title} {summary}"
        if any(
            re.search(pattern, text, re.IGNORECASE)
            for pattern in source_text_excludes.get(source, [])
        ):
            continue

        best_priority, topic_w, matched_ids, any_hit = match_topics(text, topics)
        (jurisdiction_ids, jurisdiction_names, jurisdiction_w,
         jurisdiction_tiers, primary_jurisdiction_tier) = match_jurisdictions(
            text, source, jcfg
        )

        is_court = source in COURT_SOURCES

        # ÐŸÑ€Ð°Ð²Ð¸Ð»Ð° Ð¿Ñ€Ð¾Ñ…Ð¾Ð¶Ð´ÐµÐ½Ð¸Ñ Ñ„Ð¸Ð»ÑŒÑ‚Ñ€Ð° Ñ‚ÐµÐ¼:
        #  - Ð¾Ð±Ñ‹Ñ‡Ð½Ñ‹Ð¹ Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº: Ð½ÑƒÐ¶ÐµÐ½ Ð¼Ð°Ñ‚Ñ‡ Ñ‚ÐµÐ¼Ñ‹;
        #  - Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸Ðº Ñ ÑÐµÑ€Ð²ÐµÑ€Ð½Ð¾Ð¹ Ð¿Ñ€ÐµÐ´Ñ„Ð¸Ð»ÑŒÑ‚Ñ€Ð°Ñ†Ð¸ÐµÐ¹ (prefiltered: true, Ð½Ð°Ð¿Ñ€.
        #    nl_rechtspraak Ñ subject=belastingrecht) â€” Ñ‚ÐµÐ¼Ñƒ ÑƒÐ¶Ðµ Ð¾Ñ‚Ð¾Ð±Ñ€Ð°Ð» ÑÐµÑ€Ð²ÐµÑ€,
        #    Ð¿Ð¾ÑÑ‚Ð¾Ð¼Ñƒ Ð¿Ñ€Ð¾Ð¿ÑƒÑÐºÐ°ÐµÐ¼ Ð¸ Ð±ÐµÐ· Ð¼Ð°Ñ‚Ñ‡Ð° ÐºÐ»ÑŽÑ‡ÐµÐ²Ñ‹Ñ… ÑÐ»Ð¾Ð², Ñ Ð´ÐµÑ„Ð¾Ð»Ñ‚Ð½Ñ‹Ð¼
        #    Ð¿Ñ€Ð¸Ð¾Ñ€Ð¸Ñ‚ÐµÑ‚Ð¾Ð¼. Ð­Ñ‚Ð¾ Ð·Ð°Ð¼ÐµÐ½ÑÐµÑ‚ Ð¿Ñ€ÐµÐ¶Ð½Ð¸Ð¹ Ð½ÐµÐ´Ð¾ÑÑ‚Ð¸Ð¶Ð¸Ð¼Ñ‹Ð¹ Ð³ÐµÐ¹Ñ‚ ÑÑƒÐ´Ð¾Ð²
        #    (is_court and any_hit Ð¿Ñ€Ð¸ best_priority is None Ð½Ð¸ÐºÐ¾Ð³Ð´Ð° Ð½Ðµ Ð¸ÑÑ‚Ð¸Ð½Ð½Ð¾,
        #    Ñ‚.Ðº. any_hit â‡” best_priority Ð·Ð°Ð´Ð°Ð½) â€” Ð¸Ð·-Ð·Ð° Ð½ÐµÐ³Ð¾ ÑÑƒÐ´Ñ‹ Ð¼Ð¾Ð»Ñ‡Ð°
        #    Ð²Ñ‹Ð±Ñ€Ð°ÑÑ‹Ð²Ð°Ð»Ð¸ÑÑŒ (0 Ð·Ð°Ð¿Ð¸ÑÐµÐ¹ nl_rechtspraak/ru_ras Ð² Ð¸ÑÑ‚Ð¾Ñ€Ð¸Ð¸ state).
        if best_priority is None:
            if source in prefiltered_sources:
                best_priority = PREFILTERED_DEFAULT_PRIORITY
                topic_w = PRIORITY_WEIGHT.get(PREFILTERED_DEFAULT_PRIORITY, 1.0)
                if not matched_ids:
                    matched_ids = [default_topics.get(source, "nl_fiscaal")]
            else:
                continue

        # ÐžÐ±Ñ‰Ð¸Ð¹ ÑÐ»ÑƒÐ¶ÐµÐ±Ð½Ñ‹Ð¹ Ñ‚ÐµÐ³ Ð½Ðµ Ð·Ð°Ð¼ÐµÐ½ÑÐµÑ‚ Ñ†ÐµÐ»ÐµÐ²ÑƒÑŽ Ñ‚ÐµÐ¼Ñƒ Ñƒ ÑˆÐ¸Ñ€Ð¾ÐºÐ¸Ñ… Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð².
        required = required_topics.get(source)
        if required and not required.intersection(matched_ids):
            continue

        # court_p1 ÑÑ‡Ð¸Ñ‚Ð°ÐµÐ¼ ÐŸÐžÐ¡Ð›Ð• Ð³ÐµÐ¹Ñ‚Ð°: Ð³Ð°Ñ€Ð°Ð½Ñ‚Ð¸ÑŽ Ð² ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ðµ Ð´Ð°Ñ‘Ñ‚ Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ€ÐµÐ°Ð»ÑŒÐ½Ñ‹Ð¹
        # Ð¼Ð°Ñ‚Ñ‡ P1-Ñ‚ÐµÐ¼Ñ‹, Ð° Ð½Ðµ Ð´ÐµÑ„Ð¾Ð»Ñ‚Ð½Ñ‹Ð¹ Ð¿Ñ€Ð¸Ð¾Ñ€Ð¸Ñ‚ÐµÑ‚ Ð¿Ñ€ÐµÐ´Ñ„Ð¸Ð»ÑŒÑ‚Ñ€Ð°Ñ†Ð¸Ð¸.
        court_p1 = is_court and best_priority == 1

        src_w = weights.get(source, 1.0)
        base = topic_w * src_w
        fresh = is_fresh(published_at, date)
        engagement_bonus = min(1.5, math.log1p(engagement) / 4.0) if lead else 0.0
        score = base + jurisdiction_w + (FRESHNESS_BONUS if fresh else 0.0) + engagement_bonus

        title_norm = newsdb.normalize_title(title)
        dup = newsdb.is_duplicate(conn, url, ecli, title_norm, act_norm)

        candidate = {
            "source": source,
            "url": url,
            "ecli": ecli,
            "act": act,
            "title": title,
            "title_norm": title_norm,
            "summary": summary,
            "published_at": published_at,
            "score": round(score, 3),
            "topics": matched_ids,
            "jurisdictions": jurisdiction_ids,
            "jurisdiction_names": jurisdiction_names,
            "jurisdiction_tiers": jurisdiction_tiers,
            "primary_jurisdiction_tier": primary_jurisdiction_tier,
            "priority": best_priority,
            "fresh": fresh,
            "lead": lead,
            "channel": rec.get("channel", "") or "",
            "message_id": rec.get("message_id", "") or "",
            "engagement": engagement,
            "item_type": rec.get("item_type", "") or "",
            "is_court_p1": court_p1,
            "dup": dup,
        }
        scored.append(candidate)

    # --- Ð”ÐµÐ´ÑƒÐ¿ ----------------------------------------------------------------
    # Ð¡Ð½Ð°Ñ‡Ð°Ð»Ð° Ð¿Ð¾ ÑƒÐ±Ñ‹Ð²Ð°Ð½Ð¸ÑŽ ÑÐºÐ¾Ñ€Ð°: Ð¿Ñ€Ð¸ Ð²Ð½ÑƒÑ‚Ñ€Ð¸Ð¿Ð°Ñ‡ÐµÑ‡Ð½Ð¾Ð¼ Ð´ÑƒÐ±Ð»Ðµ Ð¾ÑÑ‚Ð°Ð²Ð»ÑÐµÐ¼ Ð»ÑƒÑ‡ÑˆÐ¸Ð¹ Ð²Ð°Ñ€Ð¸Ð°Ð½Ñ‚.
    scored.sort(key=lambda c: (bool(c["jurisdictions"]), c["score"], c["fresh"]),
                reverse=True)

    fresh_candidates = []
    seen_urls, seen_eclis, seen_acts, seen_titles = set(), set(), set(), []
    n_batch_dupes = 0
    for c in scored:
        if c["dup"]:
            continue
        # Ð’Ð½ÑƒÑ‚Ñ€Ð¸Ð¿Ð°Ñ‡ÐµÑ‡Ð½Ñ‹Ð¹ ÐºÑ€Ð¾ÑÑ-Ð¸ÑÑ‚Ð¾Ñ‡Ð½Ð¸ÐºÐ¾Ð²Ñ‹Ð¹ Ð´ÐµÐ´ÑƒÐ¿: Ð¾Ð´Ð½Ð° Ð½Ð¾Ð²Ð¾ÑÑ‚ÑŒ Ð¾Ñ‚ garant Ð¸ Ð¤ÐÐ¡
        # (Ð¸Ð»Ð¸ Ð¿ÐµÑ€ÐµÐ¿ÐµÑ‡Ð°Ñ‚ÐºÐ° Ð²Ð½ÑƒÑ‚Ñ€Ð¸ Ð¾Ð´Ð½Ð¾Ð³Ð¾ Ð¿Ñ€Ð¾Ð³Ð¾Ð½Ð°) Ð½Ðµ Ð´Ð¾Ð»Ð¶Ð½Ð° Ð²Ð¾Ð¹Ñ‚Ð¸ Ð´Ð²Ð°Ð¶Ð´Ñ‹. Ð¡Ð²ÐµÑ€ÑÐµÐ¼
        # Ñ ÑƒÐ¶Ðµ Ð¿Ñ€Ð¸Ð½ÑÑ‚Ñ‹Ð¼Ð¸ Ð² Ð­Ð¢ÐžÐœ Ð¿Ñ€Ð¾Ð³Ð¾Ð½Ðµ Ð¿Ð¾ URL / ECLI / Ð½ÐµÑ‡Ñ‘Ñ‚ÐºÐ¾Ð¼Ñƒ Ð·Ð°Ð³Ð¾Ð»Ð¾Ð²ÐºÑƒ.
        u, e, a, tn = c["url"], c["ecli"], c["act"], c["title_norm"]
        batch_dup = False
        if u and u in seen_urls:
            batch_dup = True
        elif e and e in seen_eclis:
            batch_dup = True
        elif a and newsdb.normalize_title(a) in seen_acts:
            batch_dup = True
        elif tn and any(
            difflib.SequenceMatcher(None, tn, t).ratio() >= newsdb.DUP_RATIO
            for t in seen_titles
        ):
            batch_dup = True
        if batch_dup:
            n_batch_dupes += 1
            continue
        if u:
            seen_urls.add(u)
        if e:
            seen_eclis.add(e)
        if a:
            seen_acts.add(newsdb.normalize_title(a))
        if tn:
            seen_titles.append(tn)

        item_id, is_new = newsdb.upsert_item(conn, {
            "url": c["url"],
            "ecli": c["ecli"],
            "act": c["act"],
            "source": c["source"],
            "title": c["title"],
            "title_norm": c["title_norm"],
            "summary": c["summary"],
            "published_at": c["published_at"],
            "run_date": date,
            "score": c["score"],
            "topics": ",".join(c["topics"]),
            "status": "collected",
        })
        c["item_id"] = item_id
        if is_new:
            n_collected_new += 1
        fresh_candidates.append(c)

    # --- Ð Ð°Ð½Ð¶Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð¸Ðµ ---------------------------------------------------------
    # Ð¡ÑƒÐ´ÐµÐ±Ð½Ñ‹Ðµ P1 Ð³Ð°Ñ€Ð°Ð½Ñ‚Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ð¾ Ð² ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ðµ: ÑÐ¾Ñ€Ñ‚Ð¸Ñ€ÑƒÐµÐ¼ Ð¸Ñ… Ð½Ð°Ð²ÐµÑ€Ñ…, Ð·Ð°Ñ‚ÐµÐ¼ Ð¿Ð¾ score.
    fresh_candidates.sort(
        key=lambda c: (c["is_court_p1"], bool(c["jurisdictions"]), c["score"], c["fresh"]),
        reverse=True,
    )

    # --- ÐŸÑ€Ð¸Ð¼ÐµÐ½ÑÐµÐ¼ ÐºÐ°Ð¿ --top, Ð½Ð¾ ÑÑƒÐ´ÐµÐ±Ð½Ñ‹Ðµ P1 Ð½Ðµ Ð²Ñ‹ÐºÐ¸Ð´Ñ‹Ð²Ð°ÐµÐ¼ ---------------------
    # ÐœÐ°Ñ‚ÐµÑ€Ð¸Ð°Ð»Ñ‹ Ð±ÐµÐ· Ñ†ÐµÐ»ÐµÐ²Ð¾Ð¹ ÑŽÑ€Ð¸ÑÐ´Ð¸ÐºÑ†Ð¸Ð¸ â€” Ñ‚Ð¾Ð»ÑŒÐºÐ¾ Ñ„Ð¾Ð½: Ð½Ðµ Ð±Ð¾Ð»ÐµÐµ unscoped_cap.
    guaranteed = [c for c in fresh_candidates if c["is_court_p1"]]
    scoped = [c for c in fresh_candidates if not c["is_court_p1"] and c["jurisdictions"]]
    third_line = [c for c in scoped if c.get("primary_jurisdiction_tier") == "third_line"]
    non_third_scoped = [c for c in scoped if c.get("primary_jurisdiction_tier") != "third_line"]
    unscoped = [c for c in fresh_candidates if not c["is_court_p1"] and not c["jurisdictions"]]
    others = (
        non_third_scoped
        + third_line[:max(0, jcfg["third_line_cap"])]
        + unscoped[:max(0, jcfg["unscoped_cap"])]
    )
    selected = list(guaranteed)
    for c in others:
        if len(selected) >= top:
            break
        selected.append(c)
    # Ð¤Ð¸Ð½Ð°Ð»ÑŒÐ½Ð°Ñ ÑÐ¾Ñ€Ñ‚Ð¸Ñ€Ð¾Ð²ÐºÐ° Ð¾Ñ‚Ð¾Ð±Ñ€Ð°Ð½Ð½Ð¾Ð³Ð¾ Ð¿Ð¾ score (Ð³Ð°Ñ€Ð°Ð½Ñ‚Ð¸Ñ€Ð¾Ð²Ð°Ð½Ð½Ñ‹Ðµ Ñ‚Ð¾Ð¶Ðµ ÑƒÑ‡Ð°ÑÑ‚Ð²ÑƒÑŽÑ‚).
    selected.sort(key=lambda c: (bool(c["jurisdictions"]), c["score"], c["is_court_p1"]), reverse=True)

    # --- Ð—Ð°Ð¿Ð¸ÑÑŒ shortlist.json ------------------------------------------------
    out_items = []
    for i, c in enumerate(selected, start=1):
        out_items.append({
            "n": i,
            "item_id": c["item_id"],
            "source": c["source"],
            "url": c["url"],
            "ecli": c["ecli"],
            "act": c["act"],
            "title": c["title"],
            "summary": c["summary"],
            "published_at": c["published_at"],
            "score": c["score"],
            "topics": c["topics"],
            "jurisdictions": c["jurisdictions"],
            "jurisdiction_names": c["jurisdiction_names"],
            "lead": c["lead"],
            "channel": c["channel"],
            "message_id": c["message_id"],
            "engagement": c["engagement"],
            "item_type": c["item_type"],
            "suggested_channels": suggested_channels(c["source"]),
        })
        newsdb.set_status(conn, c["item_id"], "shortlisted")

    shortlist = {"date": date, "items": out_items}
    out_dir = os.path.join(root, "pipeline", "shortlist")
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{date}_shortlist.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(shortlist, f, ensure_ascii=False, indent=2)

    # --- ÐžÐ±Ð½Ð¾Ð²Ð»ÑÐµÐ¼ ÑÑ‚Ñ€Ð¾ÐºÑƒ runs ------------------------------------------------
    newsdb.upsert_run(
        conn, date,
        n_collected=n_collected_new,
        n_shortlisted=len(out_items),
        finished=newsdb.now_iso(),
    )

    # --- Ð§ÐµÐ»Ð¾Ð²ÐµÐºÐ¾Ñ‡Ð¸Ñ‚Ð°ÐµÐ¼Ð°Ñ ÑÐ²Ð¾Ð´ÐºÐ° ----------------------------------------------
    print(f"\n[select] Ð´Ð°Ñ‚Ð°={date}  ÐºÐ°Ð½Ð´Ð¸Ð´Ð°Ñ‚Ð¾Ð²_Ñ_Ñ‚ÐµÐ¼Ð¾Ð¹={len(scored)}  ÑƒÑÑ‚Ð°Ñ€ÐµÐ»Ð¾_Ð¾Ñ‚ÑÐµÑÐ½Ð¾={n_stale}  "
          f"Ð²Ð½ÑƒÑ‚Ñ€Ð¸Ð¿Ð°Ñ‡_Ð´ÑƒÐ±Ð»ÐµÐ¹={n_batch_dupes}  Ð½Ð¾Ð²Ñ‹Ñ…={n_collected_new}  "
          f"Ð²_ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ðµ={len(out_items)} (ÐºÐ°Ð¿={top})")
    print("-" * 88)
    print(f"{'#':>2}  {'source':<16} {'score':>6}  {'pub':<10}  ÑÑ‚Ñ€Ð°Ð½Ñ‹ | Ñ‚ÐµÐ¼Ñ‹")
    print("-" * 88)
    for it in out_items:
        topics_s = ",".join(it["topics"]) or "-"
        jurisdictions_s = ",".join(it.get("jurisdictions", [])) or "-"
        title_short = (it["title"][:46] + "â€¦") if len(it["title"]) > 47 else it["title"]
        print(f"{it['n']:>2}  {it['source']:<16} {it['score']:>6}  "
              f"{(it['published_at'] or '-'):<10}  {jurisdictions_s} | {topics_s}")
        print(f"      {title_short}")
    print("-" * 88)
    print(f"[select] â†’ {out_path}")
    return {"out_path": out_path, "n_shortlisted": len(out_items),
            "n_collected_new": n_collected_new}


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="Ð¡ÐºÐ¾Ñ€Ð¸Ð½Ð³ Ð¸ Ð¾Ñ‚Ð±Ð¾Ñ€ Ð½Ð¾Ð²Ð¾ÑÑ‚ÐµÐ¹.")
    ap.add_argument("--date", required=True, help="Ð”Ð°Ñ‚Ð° Ð¿Ñ€Ð¾Ð³Ð¾Ð½Ð° YYYY-MM-DD.")
    ap.add_argument("--top", type=int, default=15, help="ÐœÐ°ÐºÑÐ¸Ð¼ÑƒÐ¼ Ð½Ð¾Ð²Ð¾ÑÑ‚ÐµÐ¹ Ð² ÑˆÐ¾Ñ€Ñ‚Ð»Ð¸ÑÑ‚Ðµ.")
    ap.add_argument("--root", default=".", help="ÐšÐ¾Ñ€ÐµÐ½ÑŒ Ð¿Ñ€Ð¾ÐµÐºÑ‚Ð°.")
    args = ap.parse_args()
    run(args.date, args.top, args.root)


if __name__ == "__main__":
    main()

