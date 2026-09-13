#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Скоринг и отбор новостей → pipeline/shortlist/{date}_shortlist.json. Stdlib + PyYAML."""

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
    print("Нужен PyYAML. Установка: pip install pyyaml --break-system-packages", file=sys.stderr)
    sys.exit(2)

import newsdb  # локальный модуль состояния

# Вес приоритета темы.
PRIORITY_WEIGHT = {1: 3.0, 2: 2.0, 3: 1.0}
# Бонус за свежесть (публикация за последние 24 часа).
FRESHNESS_BONUS = 0.5
# Судебные источники — особые правила прохождения.
COURT_SOURCES = {"nl_rechtspraak", "ru_ras", "ru_vs"}
DEFAULT_UNSCOPED_CAP = 1
DEFAULT_THIRD_LINE_CAP = 2
# Приоритет по умолчанию для источников с серверной предфильтрацией темы
# (prefiltered: true в sources.yaml): сервер уже отобрал по теме, поэтому такой
# материал проходит гейт и без матча ключевых слов — с этим приоритетом.
PREFILTERED_DEFAULT_PRIORITY = 2

# Правила предложенных каналов по источнику.
RU_NEWS_SOURCES = {"ru_garant", "ru_fns", "ru_minfin", "ru_vs"}
NL_EN_MEDIA = {"intl_regfollower", "nl_taxlive", "nl_taxence", "nl_fd"}


def load_yaml(path):
    """Прочитать YAML-файл в объект."""
    with open(path, "r", encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_topics(root):
    """Список тем с плоским набором ключевых слов (ru+nl+en+plain)."""
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
    """Веса источников из sources.yaml → {source_id: weight}."""
    data = load_yaml(os.path.join(root, "config", "sources.yaml"))
    out = {}
    for s in data.get("sources", []):
        out[s["id"]] = float(s.get("weight", 1.0))
    return out


def load_source_windows(root):
    """Окно свежести источников из sources.yaml → {source_id: window_days}."""
    data = load_yaml(os.path.join(root, "config", "sources.yaml"))
    default_h = int((data.get("defaults") or {}).get("window_hours", 48))
    out = {"__default__": max(1, (default_h + 23) // 24)}
    for s in data.get("sources", []):
        h = int(s.get("window_hours", default_h))
        out[s["id"]] = max(1, (h + 23) // 24)
    return out


def load_prefiltered(root):
    """Множество источников с серверной предфильтрацией темы (prefiltered: true)."""
    data = load_yaml(os.path.join(root, "config", "sources.yaml"))
    out = set()
    for s in data.get("sources", []):
        if s.get("prefiltered"):
            out.add(s["id"])
    return out


def load_default_topics(root):
    """Тема по умолчанию для серверно предфильтрованных источников."""
    data = load_yaml(os.path.join(root, "config", "sources.yaml"))
    return {
        source["id"]: source.get("default_topic", "nl_fiscaal")
        for source in data.get("sources", [])
        if source.get("prefiltered")
    }


def load_required_topics(root):
    """Гейты широких источников: {source_id: {обязательные topic_id}}."""
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
    """Конфигурационные regex для отсечения рекламы/курсов по источнику."""
    data = load_yaml(os.path.join(root, "config", "sources.yaml"))
    return {
        source["id"]: list(source.get("exclude_text") or [])
        for source in data.get("sources", [])
        if source.get("exclude_text")
    }


def load_jurisdictions(root):
    """Загрузить карту юрисдикций; если файла нет, вернуть мягкие defaults."""
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
    """Возраст материала в днях относительно даты прогона; None если дата неизвестна/кривая."""
    if not published_at:
        return None
    try:
        pub = datetime.strptime(published_at[:10], "%Y-%m-%d").date()
        rd = datetime.strptime(run_date, "%Y-%m-%d").date()
    except ValueError:
        return None
    return (rd - pub).days


def load_inbox(root, date):
    """Прочитать pipeline/inbox/{date}_items.jsonl → список dict."""
    path = os.path.join(root, "pipeline", "inbox", f"{date}_items.jsonl")
    items = []
    if not os.path.exists(path):
        print(f"[select] нет inbox-файла {path}", file=sys.stderr)
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
    """Сопоставить темы по вхождению ключевых слов (casefold substring).

    Возвращает (best_priority, best_weight, matched_topic_ids, any_tax_hit).
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
    """Найти юрисдикции по source_id и ключевым словам в заголовке/аннотации."""
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
    """Опубликовано ли в пределах 24ч до даты прогона (по датам, без времени — консервативно)."""
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
    """Предложенные каналы публикации по правилам источника."""
    if source_id in COURT_SOURCES:
        return ["telegram_channel"]
    if source_id in RU_NEWS_SOURCES:
        return ["telegram_channel", "vk"]
    if source_id in NL_EN_MEDIA:
        return ["telegram_channel"]
    # По умолчанию — консервативно, только основной канал.
    return ["telegram_channel"]


def run(date, top, root):
    """Полный проход отбора: скоринг, дедуп, кап, запись shortlist, апдейт runs."""
    conn = newsdb.connect(root)
    try:
        return _run_connected(date, top, root, conn)
    finally:
        newsdb.close(conn)


def _run_connected(date, top, root, conn):
    """Выполнить отбор на открытом newsdb-соединении."""
    topics = load_topics(root)
    weights = load_source_weights(root)
    windows = load_source_windows(root)
    prefiltered_sources = load_prefiltered(root)
    default_topics = load_default_topics(root)
    required_topics = load_required_topics(root)
    source_text_excludes = load_source_text_excludes(root)
    jcfg = load_jurisdictions(root)
    inbox = load_inbox(root, date)
    catalog_path = Path(root).resolve().parent / "ОПУБЛИКОВАННЫЕ_НОВОСТИ.md"
    if catalog_path.exists():
        n_catalog = newsdb.ingest_published_catalog(conn, str(catalog_path))
        print(f"[select] каталог публикаций: {n_catalog} строк проиндексировано")

    n_collected_new = 0
    n_stale = 0
    scored = []  # список кандидатов с полями скоринга

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

        # Жёсткое окно свежести: датированный материал старше окна источника
        # в подборку не идёт (кэш-снапшоты CDN и перепечатки старья).
        # Материалы без даты сохраняем — по ним решает дедуп и скоринг.
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

        # Правила прохождения фильтра тем:
        #  - обычный источник: нужен матч темы;
        #  - источник с серверной предфильтрацией (prefiltered: true, напр.
        #    nl_rechtspraak с subject=belastingrecht) — тему уже отобрал сервер,
        #    поэтому пропускаем и без матча ключевых слов, с дефолтным
        #    приоритетом. Это заменяет прежний недостижимый гейт судов
        #    (is_court and any_hit при best_priority is None никогда не истинно,
        #    Ñ‚.к. any_hit ⇔ best_priority задан) — из-за него суды молча
        #    выбрасывались (0 записей nl_rechtspraak/ru_ras в истории state).
        if best_priority is None:
            if source in prefiltered_sources:
                best_priority = PREFILTERED_DEFAULT_PRIORITY
                topic_w = PRIORITY_WEIGHT.get(PREFILTERED_DEFAULT_PRIORITY, 1.0)
                if not matched_ids:
                    matched_ids = [default_topics.get(source, "nl_fiscaal")]
            else:
                continue

        # Общий служебный тег не заменяет целевую тему у широких источников.
        required = required_topics.get(source)
        if required and not required.intersection(matched_ids):
            continue

        # court_p1 считаем ПОСЛЕ гейта: гарантию в шортлисте даёт только реальный
        # матч P1-темы, а не дефолтный приоритет предфильтрации.
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

    # --- Дедуп ----------------------------------------------------------------
    # Сначала по убыванию скора: при внутрипачечном дубле оставляем лучший вариант.
    scored.sort(key=lambda c: (bool(c["jurisdictions"]), c["score"], c["fresh"]),
                reverse=True)

    fresh_candidates = []
    seen_urls, seen_eclis, seen_acts, seen_titles = set(), set(), set(), []
    n_batch_dupes = 0
    for c in scored:
        if c["dup"]:
            continue
        # Внутрипачечный кросс-источниковый дедуп: одна новость от garant и ФНС
        # (или перепечатка внутри одного прогона) не должна войти дважды. Сверяем
        # с уже принятыми в ЭТОМ прогоне по URL / ECLI / нечёткому заголовку.
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

    # --- Ранжирование ---------------------------------------------------------
    # Судебные P1 гарантированно в шортлисте: сортируем их наверх, затем по score.
    fresh_candidates.sort(
        key=lambda c: (c["is_court_p1"], bool(c["jurisdictions"]), c["score"], c["fresh"]),
        reverse=True,
    )

    # --- Применяем кап --top, но судебные P1 не выкидываем ---------------------
    # Материалы без целевой юрисдикции — только фон: не более unscoped_cap.
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
    # Финальная сортировка отобранного по score (гарантированные тоже участвуют).
    selected.sort(key=lambda c: (bool(c["jurisdictions"]), c["score"], c["is_court_p1"]), reverse=True)

    # --- Запись shortlist.json ------------------------------------------------
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

    # --- Обновляем строку runs ------------------------------------------------
    newsdb.upsert_run(
        conn, date,
        n_collected=n_collected_new,
        n_shortlisted=len(out_items),
        finished=newsdb.now_iso(),
    )

    # --- Человекочитаемая сводка ----------------------------------------------
    print(f"\n[select] дата={date}  кандидатов_с_темой={len(scored)}  устарело_отсеяно={n_stale}  "
          f"внутрипач_дублей={n_batch_dupes}  новых={n_collected_new}  "
          f"в_шортлисте={len(out_items)} (кап={top})")
    print("-" * 88)
    print(f"{'#':>2}  {'source':<16} {'score':>6}  {'pub':<10}  страны | темы")
    print("-" * 88)
    for it in out_items:
        topics_s = ",".join(it["topics"]) or "-"
        jurisdictions_s = ",".join(it.get("jurisdictions", [])) or "-"
        title_short = (it["title"][:46] + "…") if len(it["title"]) > 47 else it["title"]
        print(f"{it['n']:>2}  {it['source']:<16} {it['score']:>6}  "
              f"{(it['published_at'] or '-'):<10}  {jurisdictions_s} | {topics_s}")
        print(f"      {title_short}")
    print("-" * 88)
    print(f"[select] → {out_path}")
    return {"out_path": out_path, "n_shortlisted": len(out_items),
            "n_collected_new": n_collected_new}


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="Скоринг и отбор новостей.")
    ap.add_argument("--date", required=True, help="Дата прогона YYYY-MM-DD.")
    ap.add_argument("--top", type=int, default=15, help="Максимум новостей в шортлисте.")
    ap.add_argument("--root", default=".", help="Корень проекта.")
    args = ap.parse_args()
    run(args.date, args.top, args.root)


if __name__ == "__main__":
    main()

