#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Устаревший автосборщик, намеренно заблокированный для боевых выпусков.

Он не открывал каждый первоисточник и потому не может создавать approved JSON.
Оставлен только как историческая заготовка; вызов завершается ошибкой до записи.
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NEWS_ROOT = ROOT / "News Claude" if (ROOT / "News Claude").exists() else ROOT
VENV_PYTHON = ROOT / ".venv" / "Scripts" / "python.exe"
if not VENV_PYTHON.exists():
    VENV_PYTHON = Path(sys.executable)

TRANSLATION_MAP = {
    r"\bAlbania\b": "Албания", r"\bQatar\b": "Катар", r"\bTaiwan\b": "Тайвань", r"\bKazakhstan\b": "Казахстан",
    r"\bRussia\b": "Россия", r"\bPeru\b": "Перу", r"\bPhilippines\b": "Филиппины", r"\bBolivia\b": "Боливия",
    r"\bKenya\b": "Кения", r"\bUS\b": "США", r"\bUSA\b": "США", r"\bNetherlands\b": "Нидерланды", r"\bBelgium\b": "Бельгия",
    r"\bItaly\b": "Италия", r"\bEU\b": "ЕС", r"\bGuatemala\b": "Гватемала", r"\bAustralia\b": "Австралия",
    r"\bUK\b": "Великобритания", r"\bIceland\b": "Исландия", r"\bCanada\b": "Канада", r"\bBrazil\b": "Бразилия",
    r"\bGermany\b": "Германия", r"\bJapan\b": "Япония", r"\bParaguay\b": "Парагвай", r"\bLithuania\b": "Литва",
    r"\bGreece\b": "Греция", r"\bHong Kong\b": "Гонконг", r"\bSingapore\b": "Сингапур", r"\bPakistan\b": "Пакистан",
    r"\bSlovenia\b": "Словения", r"\bSpain\b": "Испания", r"\bFrance\b": "Франция", r"\bSwitzerland\b": "Швейцария",
    r"\bAustria\b": "Австрия", r"\bNorway\b": "Норвегия", r"\bSweden\b": "Швеция", r"\bFinland\b": "Финляндия",
    r"\bCouncil of Ministers\b": "Совет министров", r"\bapproves\b": "одобрил", r"\bprotocol\b": "протокол",
    r"\btax treaty\b": "налоговое соглашение", r"\bwith\b": "с", r"\bintroduces\b": "внедряет",
    r"\belectronic\b": "электронную", r"\bcertificate\b": "сертификацию", r"\bprocess\b": "процедуру",
    r"\bwarns on\b": "предупреждает о", r"\bsecurities tax\b": "налоге на ценные бумаги", r"\bunlisted shares\b": "некотируемые акции",
    r"\breminds\b": "напоминает", r"\bbusinesses\b": "бизнесу", r"\bcross-border\b": "трансграничных",
    r"\be-service\b": "электронных сервисов", r"\bduties\b": "обязанностях", r"\bNational Bank\b": "Национальный банк",
    r"\bcuts base rate\b": "снизил базовую ставку", r"\bproposes\b": "предлагает", r"\bVAT\b": "НДС",
    r"\bSME\b": "МСП", r"\btax changes\b": "налоговые изменения", r"\burged to cut\b": "призвали сократить",
    r"\btax expenditures\b": "налоговые льготы", r"\bimprove compliance\b": "улучшить администрирование",
    r"\bexpands\b": "расширяет", r"\bpayment channels\b": "каналы уплаты", r"\bprovisional\b": "авансовых платежей",
    r"\bcorporate income tax\b": "налога на прибыль", r"\bratifies\b": "ратифицировал", r"\bincome tax treaty\b": "налоговое соглашение",
    r"\bconsults on\b": "консультируется по", r"\brevised\b": "обновленной", r"\bbilling system\b": "системе счетов",
    r"\bspecifications\b": "требованиям", r"\blaunches\b": "запускает", r"\btax amnesty\b": "налоговую амнистию",
    r"\bprogramme\b": "программу", r"\bthrough end of\b": "до конца", r"\bextends\b": "продлевает",
    r"\bpied-à-terre\b": "на второе жилье", r"\bexemption deadline\b": "срок освобождения", r"\bto October\b": "до октября",
    r"\bupdates\b": "обновил", r"\bdecree\b": "указ", r"\bincorporate\b": "с учетом", r"\brebuttal scheme\b": "схемы опровержения",
    r"\bCourt of Cassation\b": "Кассационный суд", r"\brules\b": "постановил", r"\bsubscription tax\b": "подписной налог",
    r"\bapplies to\b": "применяется к", r"\bfunds\b": "фондам", r"\btemporary\b": "временное",
    r"\bdiesel excise duty\b": "акциз на дизель", r"\breduction\b": "снижение", r"\bCommission\b": "Комиссия",
    r"\bsets\b": "установила", r"\bdocumentation rules\b": "правила документации", r"\bsteel import\b": "импорта стали",
    r"\btraceability\b": "прослеживаемости", r"\bzero rate\b": "нулевую ставку", r"\bresidential properties\b": "жилую недвижимость",
    r"\bcapital gains exemption\b": "освобождение прироста капитала", r"\bminimum tax\b": "минимальный налог",
    r"\bdiscretionary trusts\b": "дискреционные трасты", r"\bcurb income splitting\b": "ограничение расщепления доходов",
    r"\brequires\b": "обязывает", r"\bmaintain stock records\b": "вести учет запасов", r"\bcompulsory\b": "обязательное",
    r"\bforeign permanent establishment\b": "зарубежное постоянное представительство", r"\bexemption\b": "освобождение",
    r"\bfrom 2027\b": "с 2027 года", r"\bbudget\b": "бюджет", r"\bfinancial institution\b": "финансовых институтов",
    r"\btax hike\b": "повышение налога", r"\bmeasures\b": "меры", r"\benacts\b": "ввел",
    r"\bretaliatory tariffs\b": "ответные пошлины", r"\bimports\b": "импорт", r"\btrade negotiations\b": "торговых переговорах",
    r"\bcollapse\b": "срыве", r"\bconsolidates\b": "консолидирует", r"\bcustoms storage\b": "таможенное хранение",
    r"\bopens public input\b": "открыл обсуждение"
}

LATIN_ALLOWED = {"BEPS", "OECD", "HMRC", "ECLI", "MLI", "FNS", "ENS", "INN", "GLOBE", "PILLAR", "TELEGRAM", "LINKEDIN", "WORDPRESS", "POSTIZ", "CRS", "AEOI", "DTT", "VAT", "SME"}


def to_russian(text: str) -> str:
    res = text
    for pattern, repl in TRANSLATION_MAP.items():
        res = re.sub(pattern, repl, res, flags=re.IGNORECASE)
        
    def _sanitize(m):
        word = m.group(0)
        if word.upper() in LATIN_ALLOWED or len(word) <= 2:
            return word
        return ""

    res = re.sub(r"[A-Za-z]+", _sanitize, res)
    res = re.sub(r"\s+", " ", res).strip()
    return res


def load_published_history(root: Path) -> tuple[set[str], set[str]]:
    titles = set()
    urls = set()
    
    pub_md = root.parent / "ОПУБЛИКОВАННЫЕ_НОВОСТИ.md"
    if not pub_md.exists():
        pub_md = root / "ОПУБЛИКОВАННЫЕ_НОВОСТИ.md"
    if pub_md.is_file():
        for line in pub_md.read_text(encoding="utf-8").splitlines():
            clean = line.strip().casefold()
            if clean:
                titles.add(clean)
                
    for f in (root / "pipeline" / "published").glob("*.jsonl"):
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            try:
                data = json.loads(line)
                if data.get("title"): titles.add(data["title"].strip().casefold())
                if data.get("url"): urls.add(data["url"].strip())
            except Exception: pass

    for f in (root / "pipeline" / "approved").glob("*.json"):
        try:
            data = json.loads(f.read_text(encoding="utf-8"))
            for item in data.get("items", []):
                if item.get("title"): titles.add(item["title"].strip().casefold())
                if item.get("source_url"): urls.add(item["source_url"].strip())
                if item.get("url"): urls.add(item["url"].strip())
                for src in item.get("sources", []):
                    if src.get("url"): urls.add(src["url"].strip())
        except Exception: pass
        
    return titles, urls


def build_approved_package(release_name: str, target_path: Path, root: Path) -> Path:
    raise RuntimeError(
        "Автосбор из inbox запрещён: он не выполняет обязательную live-проверку "
        "первоисточников и не вправе создавать approved-пакет."
    )
    published_titles, published_urls = load_published_history(root)
    date_str = release_name[:10]
    slot_str = release_name[11:15] if len(release_name) >= 15 else "1700"

    inbox_files = sorted((root / "pipeline" / "inbox").glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
    
    ru_candidates = []
    kz_candidates = []
    other_candidates = []
    seen_urls = set()

    for f in inbox_files:
        for line in f.read_text(encoding="utf-8").splitlines():
            if not line.strip(): continue
            try:
                item = json.loads(line)
                url = (item.get("url") or item.get("source_url") or "").strip()
                title = (item.get("title") or item.get("title_ru") or "").strip()
                if not title or not url or url in seen_urls or url in published_urls:
                    continue
                if title.casefold() in published_titles:
                    continue
                
                seen_urls.add(url)
                src = item.get("source") or ""
                txt_lower = (title + " " + (item.get("summary") or "")).lower()
                
                if src in ("ru_fns", "ru_minfin", "ru_garant", "ru_vs"):
                    ru_candidates.append(item)
                elif src in ("kz_kgd", "kz_minfin") or "казахстан" in txt_lower or "kazakhstan" in txt_lower:
                    kz_candidates.append(item)
                else:
                    other_candidates.append(item)
            except Exception:
                pass

    print(f"[auto-build] Candidates available: RU={len(ru_candidates)}, KZ={len(kz_candidates)}, Other={len(other_candidates)}")

    selected = []
    
    # Pick 2 RU
    for item in ru_candidates[:2]:
        selected.append((item, "RU"))
        
    # Pick 2 KZ
    for item in kz_candidates[:2]:
        selected.append((item, "KZ"))

    # Fill up to 10 with Other / RU / KZ
    for item in other_candidates:
        if len(selected) >= 10: break
        c_code = "INTL"
        t_lower = item.get("title", "").lower()
        for k, v in TRANSLATION_MAP.items():
            k_clean = k.replace(r"\b", "").strip()
            if k_clean.lower() in t_lower:
                c_code = k_clean.upper()
                break
        selected.append((item, c_code))

    if len(selected) < 10:
        for item in ru_candidates[2:]:
            if len(selected) >= 10: break
            selected.append((item, "RU"))

    if len(selected) < 10:
        raise RuntimeError(f"[auto-build] Недостаточно уникальных кандидатов для сборки (найдено {len(selected)}/10)")

    items = []
    for idx, (cand, country) in enumerate(selected, start=1):
        country_slug = re.sub(r"[^a-z0-9]+", "-", country.lower()).strip("-")
        slug = f"{date_str}-item-{slot_str}-{idx:02d}-{country_slug}"
        title = cand.get("title") or ""
        url = cand.get("url") or cand.get("source_url") or ""
        
        clean_title = to_russian(title.replace("\n", " ").strip())
        if not clean_title:
            clean_title = f"Налоговые новости {country}"
        
        caption = (
            f"{clean_title}\n\n"
            f"Источник: {url}\n\n"
            f"Почему это важно: Материал содержит практические налоговые изменения и разъяснения профильных ведомств.\n\n"
            f"#АкадемияBEPS #АкадемияБЕПС"
        )
        
        items.append({
            "slug": slug,
            "title": clean_title,
            "caption": caption,
            "theme": "международное налогообложение",
            "jurisdictions": country,
            "act": clean_title,
            "sources": [{"label": "Первичный источник", "url": url}],
            "image_spec": {
                "badge": "TAX NEWS",
                "color_a": [24, 76, 120],
                "color_b": [235, 140, 50]
            },
            "channels": ["telegram_channel"],
            "item_type": "official_notice",
            "primary_source_verified": True,
            "approval": {
                "status": "approved",
                "by": "Auto-Publisher",
                "evidence": "automated candidates selection"
            }
        })

    approved_data = {
        "release": release_name,
        "date": date_str,
        "slot": slot_str,
        "items": items
    }
    
    target_path.parent.mkdir(parents=True, exist_ok=True)
    target_path.write_text(json.dumps(approved_data, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"[auto-build] Created approved release JSON: {target_path}")
    return target_path


if __name__ == "__main__":
    raise SystemExit(
        "Автосбор из inbox заблокирован: он не подтверждает первоисточники. "
        "Approved-пакет создаёт только редактор после live-проверки всех URL."
    )
