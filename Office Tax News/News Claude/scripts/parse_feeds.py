#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Парсинг сырых ответов web_fetch → pipeline/inbox/{date}_items.jsonl. Только stdlib + PyYAML."""

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
except ImportError:  # pragma: no cover - подсказка по установке зависимости
    print("Нужен PyYAML. Установка: pip install pyyaml --break-system-packages", file=sys.stderr)
    sys.exit(2)

from court_registry import upsert_court_decisions

# --- Месяцы для разбора дат ----------------------------------------------------
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

# Общие мусорные слова навигации/сервиса (для html_links фильтра).
NAV_STOPWORDS = {
    "read more", "lees verder", "meer", "inloggen", "login", "zoeken", "search",
    "home", "menu", "abonneren", "aanmelden", "meer nieuws", "alle nieuws",
    "далее", "подробнее", "войти", "поиск", "все новости", "читать далее",
    "rss", "contact", "over ons", "cookie", "privacy", "next", "previous",
    "volgende", "vorige", "оставить заявку",
}


# Минимальная длина осмысленного заголовка (короче — считаем навигацией).
MIN_TITLE_LEN = 20


# =============================================================================
#  ВСПОМОГАТЕЛЬНЫЕ
# =============================================================================
def load_sources(root):
    """Загрузить config/sources.yaml → dict {source_id: cfg}."""
    path = os.path.join(root, "config", "sources.yaml")
    with open(path, "r", encoding="utf-8") as f:
        data = yaml.safe_load(f)
    out = {}
    for src in data.get("sources", []):
        out[src["id"]] = src
    return out


def html_rules(src_cfg):
    """Единственный источник правил HTML-парсера — запись в sources.yaml."""
    rules = src_cfg.get("html") or {}
    return {
        "base": rules.get("base") or src_cfg.get("url") or "",
        "include": list(rules.get("include") or []),
        "exclude": list(rules.get("exclude") or []),
        "path_hint": rules.get("path_hint") or "",
        "date_from_title": rules.get("date_from_title") or "",
    }


def clean_text(s):
    """Снять HTML-сущности и схлопнуть пробелы."""
    if not s:
        return ""
    s = unescape(s)
    s = re.sub(r"\s+", " ", s)
    return s.strip()


def read_raw_text(path):
    """Прочитать сырьё, определив кодировку по meta charset.

    Прямой транспорт отдаёт живой HTML: garant.ru — windows-1251, остальные utf-8.
    Определяем charset по первым 2КБ (они ASCII-совместимы); web_fetch-фикстуры
    без charset читаются как utf-8 (обратная совместимость).
    """
    raw = Path(path).read_bytes()
    # utf-8 строго: подходит для markdown-фикстур web_fetch и для utf-8 HTML.
    # (Не сканируем текст на 'charset' до этого — иначе описательная фикстура,
    # упоминающая 'windows-1251', ошибочно декодировалась бы как cp1251.)
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        pass
    # Не utf-8 (напр. garant в windows-1251) — берём charset из <meta>, иначе cp1251.
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
    """Собрать (href, текст) всех <a> из живого HTML (stdlib)."""

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
    """Ответ непарсибелен: пустое тело, только эхо URL или сплошной [binary data].

    Одиночное упоминание [binary data] (описание неудавшегося под-теста) НЕ
    дисквалифицирует фикстуру, если в ней остаётся читаемый текст. Оцениваем
    объём «полезного» текста: выкидываем строки-эхо URL и binary-маркеры и
    смотрим, что осталось.
    """
    if text is None:
        return True
    stripped = text.strip()
    if not stripped:
        return True

    # Короткий JSON-конверт collector'а (напр. RAS с 0 результатов)
    # является валидным сырьём, даже если он короче текстового порога.
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
        # Строка, состоящая только из URL (эхо web_fetch), не несёт контента.
        if re.fullmatch(r"https?://\S+", ln):
            continue
        # Явный отказ политики без иного контента.
        if ln == "Web fetch was not allowed.":
            continue
        meaningful.append(ln)

    body = " ".join(meaningful).strip()
    # Совсем мало осмысленного текста — считаем непарсибельным.
    if len(body) < 120:
        return True
    return False


# =============================================================================
#  ПАРСЕР 1: rechtspraak_atom (Atom 1.0 из data.rechtspraak.nl)
# =============================================================================
def parse_rechtspraak_atom(text, src_cfg):
    """Извлечь <entry> Atom-фида rechtspraak: ECLI(id), title, summary, updated, deeplink."""
    items = []
    # Фикстура/ответ содержит XML где-то в теле — берём все <entry>...</entry>.
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
        # summary иногда "-" (нет аннотации) — нормализуем к пустой строке.
        if summary == "-":
            summary = ""

        published_at = ""
        if updated:
            # ISO8601 → YYYY-MM-DD (устойчиво к суффиксам Z/+02:00).
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
    """Локальное имя XML-тега без namespace."""
    return tag.rsplit("}", 1)[-1].casefold()


def _xml_text(node, *names):
    """Текст первого дочернего XML-элемента с одним из локальных имён."""
    wanted = {n.casefold() for n in names}
    for child in list(node):
        if _local_name(child.tag) in wanted:
            return clean_text("".join(child.itertext()))
    return ""


def _feed_date(value):
    """RSS/Atom-дата → YYYY-MM-DD."""
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
    """Дата из data-year/month/day официального листинга ВС РФ."""
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
    """Общий JSON/JSONL-конверт уже нормализованных collector items."""
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
    """JSON XHR-листинга официального сайта Верховного Суда РФ."""
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
                "налог" in review_hay
                or "обзор судебной практики верховного суда российской федерации" in review_hay
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
    """Компактный plain-text из RSS description/content."""
    return clean_text(re.sub(r"<[^>]+>", " ", unescape(value or "")))


def _canonical_feed_url(value):
    """Убрать RSS tracking-параметры, сохранив смысловые query-поля."""
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
    """Общий RSS 2.0 / Atom-парсер для прямого HTTP-транспорта."""
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
        # RSS использует те же URL-гейты, что и HTML-fallback. Это не даёт
        # разделам agenda/tag/author вернуться в поток через feed.
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
#  ПАРСЕР 2: html_links (markdown/текст от web_fetch)
# =============================================================================
def _url_ok(url, cfg):
    """URL проходит include/exclude фильтры источника."""
    if cfg["include"] and not any(re.search(p, url, re.IGNORECASE) for p in cfg["include"]):
        return False
    if any(re.search(p, url, re.IGNORECASE) for p in cfg.get("exclude", [])):
        return False
    return True


# Маркеры служебной прозы probe-отчёта / технического мусора внутри заголовка.
# Живой web_fetch-вывод их не содержит; нужны, чтобы описательные фикстуры не
# порождали ложные «заголовки» из повествования отчёта.
_PROSE_MARKERS = re.compile(
    r"(===|https?://|Content-Type|WORKS|EMPTY|binary data|"
    r"URL:|teaser|listing|pattern:|WordPress|markdown|charset|"
    r"probe|fetch|freshness|snapshot|\bnav\b)",
    re.IGNORECASE,
)


def _is_nav_title(title):
    """Заголовок похож на навигацию/сервис (слишком короткий или стоп-слово)."""
    t = title.strip().casefold()
    if len(title.strip()) < MIN_TITLE_LEN:
        return True
    if t in NAV_STOPWORDS:
        return True
    # Одно слово без пробелов почти всегда — пункт меню.
    if " " not in title.strip():
        return True
    return False


# Бренд-названия страниц (page <title>), не являющиеся новостными заголовками.
_BRAND_TITLES = {
    "taxlive | wolterskluwer", "taxence - taxence",
    "rechtspraak open data (uitspraken)",
}


def _is_prose_fragment(title):
    """Заголовок — фрагмент повествования/техвывод/бренд, а не новостной заголовок."""
    ts = title.strip()
    if not ts:
        return True
    # Начинается со служебного знака/скобки/строчной связки — обрывок предложения.
    if ts[:1] in "—-–·•,.;:)]}»([{":
        return True
    if _PROSE_MARKERS.search(ts):
        return True
    # Бренд-заголовок страницы (напр. «Taxlive | Wolterskluwer»).
    if ts.casefold() in _BRAND_TITLES:
        return True
    # Заголовок вида «Brand | Section» из <title> — служебный, не новость.
    if " | " in ts and len(ts) < 40:
        return True
    return False


def _extract_date_near(text, span_start, span_end, lang):
    """Найти дату (nl/en/iso) в пределах одной HTML-карточки вокруг ссылки."""
    # У TaxLive дата идёт после description, у ФНС — между image-link и
    # повторной title-link. Сначала берём специализированный metadata-маркер,
    # чтобы дата судебного акта внутри description не стала датой публикации.
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
    # 17.07.26 (официальный листинг Минфина)
    m = re.search(r"\b(\d{1,2})[.\-/](\d{1,2})[.\-/](\d{2})\b", date_text)
    if m:
        try:
            return datetime(2000 + int(m.group(3)), int(m.group(2)), int(m.group(1))).strftime(
                "%Y-%m-%d"
            )
        except ValueError:
            return ""
    # "09 June, 2026" / "17 juni 2026" / "2 juli 2026"
    m = re.search(r"\b(\d{1,2})\s+([A-Za-zА-Яа-я]+),?\s+(\d{4})\b", date_text)
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
    """Извлечь compact YYYYMMDD по конфигурируемому regex источника."""
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
    """Убрать повторы внутри одного источника по (url, заголовок)."""
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
    """Разбор ЖИВОГО HTML (прямой транспорт): <a href> с include/exclude источника.

    Заголовок = текст ссылки. Даты в листингах часто нет (garant) — оставляем
    published_at пустым, дальше решает дедуп и окно свежести.
    """
    base = cfg["base"]
    ex = _AnchorExtractor()
    try:
        ex.feed(text)
    except Exception:  # битый HTML не должен ронять прогон
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
    """Извлечь новостные ссылки по правилам источника.

    Живой HTML (прямой транспорт, есть теги `<a href>`) → parse_html_anchors.
    Markdown-вывод web_fetch (нет тегов) → стратегии A–D (fallback-транспорт).
    """
    cfg = html_rules(src_cfg)
    if not cfg["base"] or not cfg["include"]:
        return []
    base = cfg["base"]
    # Прямой транспорт отдаёт настоящий HTML с тегами <a href=…> — разбираем его.
    if re.search(r"<a\s[^>]*href\s*=", text, re.IGNORECASE):
        return parse_html_anchors(text, cfg, source_id)
    lang = src_cfg.get("lang", "en")
    items = []

    # --- Стратегия A: markdown-ссылки [title](url) -------------------------
    # Основной формат живого web_fetch-вывода.
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

    # Для стратегий B и C работаем по копии с схлопнутыми пробелами/переводами
    # строк — заголовки в тизерах часто переносятся на 2 строки.
    norm_text = re.sub(r"\s+", " ", text)

    # --- Стратегия B: «"Заголовок" ... (дата | URL)» -----------------------
    # Ð’ фикстурах: "Порядок обмена..." → https://www.garant.ru/news/2152202/
    # и "Koopsom nieuwe woning..." — 2 juli 2026 (без ссылки).
    for m in re.finditer(r'["“”]([^"“”]{%d,240}?)["“”]' % MIN_TITLE_LEN, norm_text):
        title = clean_text(m.group(1))
        if _is_nav_title(title) or _is_prose_fragment(title):
            continue
        # Ближайший URL источника в пределах ~320 символов после заголовка.
        tail = norm_text[m.end(): m.end() + 320]
        um = re.search(r"(https?://[^\s)>\]]+)", tail)
        url = ""
        if um:
            cand = um.group(1).rstrip(".,);")
            # Обрезанные в фикстуре ссылки (…-...) не берём как реальный URL.
            if not cand.endswith("...") and _url_ok(cand, cfg):
                url = urljoin(base, cand)
        published_at = _extract_date_near(norm_text, m.start(), m.end(), lang)
        # Нужен якорь: либо валидный URL, либо дата рядом.
        if not url and not published_at:
            continue
        items.append({
            "url": url,
            "ecli": "",
            "title": title,
            "summary": "",
            "published_at": published_at,
        })

    # --- Стратегия C: markdown-заголовки '## Title' + дата рядом -----------
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

    # --- Стратегия D: URL-якорь → ближайший заголовок в кавычках слева ------
    # Устойчивый разбор пары «"заголовок" → https://.../news/ID» даже когда
    # парность кавычек в описательном тексте «съезжает». Работает для любого
    # источника со статейными URL (include-паттерн источника решает).
    for um in re.finditer(r"https?://[^\s)>\]]+", norm_text):
        cand = um.group(0).rstrip(".,);")
        if cand.endswith("...") or not _url_ok(cand, cfg):
            continue
        url = urljoin(base, cand)
        # Заголовок — текст между ДВУМЯ последними кавычками слева от URL
        # (окно ~300). Берём по позициям самих кавычек, не полагаясь на
        # глобальную парность (в описательном тексте она «съезжает»).
        left = norm_text[max(0, um.start() - 300): um.start()]
        qpos = [i for i, ch in enumerate(left) if ch in '"“”']
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
#  ДИСПЕТЧЕР
# =============================================================================
def dispatch(text, src_cfg, source_id):
    """Выбрать парсер по src_cfg['parser'] и вернуть список сырых элементов."""
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
    # parser == none (chrome-источники) — здесь не парсим.
    return []


def source_id_from_filename(fname):
    """Из имени '{source_id}_{n}.txt' извлечь source_id (учитывая подчёркивания в id)."""
    base = os.path.basename(fname)
    base = re.sub(r"\.txt$", "", base, flags=re.IGNORECASE)
    # Отрезаем хвостовой _{число}, остальное — id источника.
    m = re.match(r"^(.*)_(\d+)$", base)
    return m.group(1) if m else base


def run(date, root):
    """Разобрать все pipeline/raw/{date}/*.txt и записать inbox jsonl. Возвращает stats."""
    raw_dir = os.path.join(root, "pipeline", "raw", date)
    inbox_dir = os.path.join(root, "pipeline", "inbox")
    os.makedirs(inbox_dir, exist_ok=True)
    out_path = os.path.join(inbox_dir, f"{date}_items.jsonl")

    sources = load_sources(root)
    files = sorted(glob.glob(os.path.join(raw_dir, "*.txt")))

    stats = {}  # source_id -> {"items": n, "status": str}
    all_items = []

    if not files:
        print(f"[parse] нет сырых файлов в {raw_dir}", file=sys.stderr)

    for fpath in files:
        sid = source_id_from_filename(fpath)
        src_cfg = sources.get(sid)
        entry = stats.setdefault(sid, {"items": 0, "status": "ok"})
        if src_cfg is None:
            entry["status"] = "unknown_source"
            print(f"[parse] {sid}: неизвестный источник (нет в sources.yaml) — пропуск")
            continue
        try:
            text = read_raw_text(fpath)
        except OSError as e:
            entry["status"] = f"read_error:{e}"
            print(f"[parse] {sid}: ошибка чтения {fpath}: {e}")
            continue

        if looks_like_binary(text):
            entry["status"] = "binary_or_empty"
            print(f"[parse] {sid}: пустой/binary фикстур — 0 элементов (не падаем)")
            continue

        try:
            raw_items = dispatch(text, src_cfg, sid)
        except Exception as e:  # источник не должен ронять прогон
            entry["status"] = f"parse_error:{type(e).__name__}"
            print(f"[parse] {sid}: ошибка парсинга: {type(e).__name__}: {e}")
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
        print(f"[parse] {sid}: {n} элементов ({entry['status']})")

    with open(out_path, "w", encoding="utf-8") as f:
        for rec in all_items:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    exported, registry_path = upsert_court_decisions(root, date, all_items)
    if exported:
        print(f"[parse] court_registry: {exported} решений → {registry_path}")

    total = len(all_items)
    print(f"[parse] ИТОГО {total} элементов → {out_path}")
    return {"out_path": out_path, "total": total, "per_source": stats}


def main():
    try:
        sys.stdout.reconfigure(encoding='utf-8')
        sys.stderr.reconfigure(encoding='utf-8')
    except AttributeError:
        pass
    ap = argparse.ArgumentParser(description="Парсинг сырых ответов в inbox jsonl.")
    ap.add_argument("--date", required=True, help="Дата прогона YYYY-MM-DD.")
    ap.add_argument("--root", default=".", help="Корень проекта.")
    args = ap.parse_args()
    run(args.date, args.root)


if __name__ == "__main__":
    main()

