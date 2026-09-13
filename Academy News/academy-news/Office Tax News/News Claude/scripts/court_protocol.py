#!/usr/bin/env python3
"""Утренний протокол анализа судебных решений RAS + Rechtspraak."""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
import subprocess
import sys
from pathlib import Path

import requests
import yaml

from court_registry import analysis_root, csv_path, ensure_layout
from fetch_rechtspraak_fulltext import fetch as fetch_rechtspraak_fulltext

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")

COURT_TOPIC_IDS = {
    "dta", "nl_ru", "substance_migration", "transfer_pricing",
    "advance_rulings", "pillar2", "withholding_dividend",
    "exchange_info", "cross_border_trade_tax",
}
EXTRA_COURT_KEYWORDS = [
    "double taxation", "tax treaty", "beneficial owner", "mli", "beps",
    "двойное налогообложение", "сидн", "фактическое право на доход", "налоговое резидентство",
    "двойного налогообложения", "избежании двойного налогообложения", "соглашения об избежании двойного налогообложения",
    "фактическом праве на доход", "налогового резидентства",
    "belastingverdrag", "verdrag rusland", "opschorting belastingverdrag",
    "dubbele belasting", "verdragstoepassing", "woonplaats", "belastingverdragen",
    "russia", "russian", "rossiya", "россия", "россии", "рф", "нидерланд", "nederland",
    "proportionaliteit", "evenredigheidsbeginsel", "proportional", "пропорцион", "соразмерност",
]
PROCEDURAL_KEYWORDS = [
    "оставить без изменения", "кассационную жалобу", "апелляционную жалобу",
    "обеспечительных мер", "возврат госпошлины", "процессуал", "определение",
    "жалобу без удовлетворения", "leave unchanged", "appeal dismissed",
    "processuele beslissing", "procedurele beslissing", "procedurele",
    "niet-ontvankelijk", "tussenuitspraak", "zonder belastingverdrag",
    "zonder internationale fiscale analyse",
]
NEGATIVE_CONTEXT_KEYWORDS = [
    "zonder belastingverdrag",
    "zonder internationale fiscale analyse",
    "without substantive tax analysis",
]


def _rows_for_date(target: Path, run_date: str) -> list[dict]:
    with target.open("r", encoding="utf-8", newline="") as handle:
        rows = [row for row in csv.DictReader(handle) if row.get("run_date") == run_date]
    return rows


def _criteria_keywords(project_root: Path) -> list[str]:
    keywords = set()
    topics_path = project_root / "config" / "topics.yaml"
    if topics_path.exists():
        topics = yaml.safe_load(topics_path.read_text(encoding="utf-8")) or {}
        for topic in topics.get("topics", []):
            if topic.get("id") not in COURT_TOPIC_IDS:
                continue
            for key in ("keywords_ru", "keywords_nl", "keywords_en", "keywords"):
                for value in topic.get(key, []) or []:
                    value = str(value).strip()
                    if value:
                        keywords.add(value.casefold())
    jurisdictions_path = project_root / "config" / "jurisdictions.yaml"
    if jurisdictions_path.exists():
        jurisdictions = yaml.safe_load(jurisdictions_path.read_text(encoding="utf-8")) or {}
        for item in jurisdictions.get("jurisdictions", []):
            if item.get("id") not in {"ru", "nl"}:
                continue
            for value in item.get("keywords", []) or []:
                value = str(value).strip()
                if value:
                    keywords.add(value.casefold())
    for value in EXTRA_COURT_KEYWORDS:
        keywords.add(value.casefold())
    return sorted(keywords)


def _write_rows(target: Path, rows: list[dict]) -> None:
    fieldnames = rows[0].keys() if rows else [
        "id", "source", "run_date", "decision_date", "case_number", "ecli", "title",
        "query_text", "url", "local_artifact_path", "extracted_text_path",
        "analysis_status", "relevance", "summary_comment", "notes",
    ]
    tmp = target.with_suffix(".tmp")
    with tmp.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)
    tmp.replace(target)


def _load_all_rows(target: Path) -> list[dict]:
    with target.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _relevance_from_text(text: str, criteria_keywords: list[str]) -> tuple[str, str]:
    hay = " ".join((text or "").split()).casefold()
    matched = [kw for kw in criteria_keywords if kw in hay]
    procedural = [kw for kw in PROCEDURAL_KEYWORDS if kw.casefold() in hay]
    negative = [kw for kw in NEGATIVE_CONTEXT_KEYWORDS if kw.casefold() in hay]
    if negative:
        comment = f"Отрицательный/процедурный контекст: {', '.join(negative[:4])}"
        return "procedural", comment
    if matched:
        comment = f"Совпали международно-налоговые маркеры: {', '.join(matched[:5])}"
        return "international_tax", comment
    if procedural:
        comment = f"Процедурный/технический акт без явных международных маркеров: {', '.join(procedural[:4])}"
        return "procedural", comment
    return "other", "Не найдено достаточных маркеров международного налогообложения"


def _registry_by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["id"]: row for row in rows if row.get("id")}


def _rechtspraak_texts(project_root: Path, run_date: str, rows: list[dict]) -> dict[str, Path]:
    eclis = list(dict.fromkeys(
        row["ecli"] for row in rows
        if row.get("source") == "nl_rechtspraak" and row.get("ecli")
    ))
    if eclis:
        fetch_rechtspraak_fulltext(
            str(project_root),
            run_date,
            session=requests.Session(),
            pause=2.0,
            eclis=eclis,
        )
    out_dir = project_root / "pipeline" / "raw" / run_date / "rechtspraak_fulltext"
    extracted_dir = analysis_root(project_root) / "extracted_text" / "rechtspraak" / run_date
    extracted_dir.mkdir(parents=True, exist_ok=True)
    found = {}
    for row in rows:
        if row.get("source") != "nl_rechtspraak" or not row.get("ecli"):
            continue
        safe = re.sub(r"[^A-Za-z0-9._-]+", "_", row["ecli"]).strip("_")
        txt = out_dir / f"{safe}.txt"
        if txt.exists():
            canonical = extracted_dir / f"{safe}.txt"
            shutil.copy2(txt, canonical)
            found[row["id"]] = canonical
    return found


def _run_ras_fulltext(project_root: Path, run_date: str) -> Path:
    script = project_root / "scripts" / "fetch_ras_fulltext.js"
    sources = yaml.safe_load((project_root / "config" / "sources.yaml").read_text(encoding="utf-8")) or {}
    ras = next((item for item in sources.get("sources", []) if item.get("id") == "ru_ras"), {})
    collector_args = list(ras.get("collector_args") or [])
    try:
        browser_url = collector_args[collector_args.index("--browser-url") + 1]
    except (ValueError, IndexError):
        browser_url = "http://127.0.0.1:9222"
    cmd = ["node", str(script), "--root", str(project_root), "--date", run_date,
           "--browser-url", str(browser_url)]
    result = subprocess.run(cmd, text=True, capture_output=True, check=False)
    if result.returncode not in (0, 3):
        raise RuntimeError((result.stdout + "\n" + result.stderr).strip()[-2000:])
    return analysis_root(project_root) / "extracted_text" / "ras" / run_date / "manifest.json"


def _extract_pdf_text(pdf_path: Path) -> str:
    try:
        from pypdf import PdfReader
    except ImportError as exc:  # pragma: no cover
        raise RuntimeError("Для анализа PDF RAS нужен pypdf") from exc
    reader = PdfReader(str(pdf_path))
    text = "\n".join((page.extract_text() or "") for page in reader.pages)
    return text


def _ras_texts(project_root: Path, run_date: str, rows: list[dict]) -> dict[str, Path]:
    manifest_path = _run_ras_fulltext(project_root, run_date)
    if not manifest_path.exists():
        return {}
    payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    by_case = {}
    text_dir = analysis_root(project_root) / "extracted_text" / "ras" / run_date
    for item in payload.get("items", []):
        if item.get("state") != "ok":
            continue
        pdf_path = Path(item["pdf_path"])
        txt_path = text_dir / (pdf_path.stem + ".txt")
        if not txt_path.exists():
            text = _extract_pdf_text(pdf_path)
            txt_path.write_text(text, encoding="utf-8")
        by_case[item.get("case_number") or ""] = txt_path
    found = {}
    for row in rows:
        if row.get("source") == "ru_ras" and row.get("case_number") in by_case:
            found[row["id"]] = by_case[row["case_number"]]
    return found


def _copy_if_relevant(src: Path, dest_dir: Path) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)
    target = dest_dir / src.name
    shutil.copy2(src, target)
    return target


def _cleanup_irrelevant(dest_dir: Path, stem: str) -> None:
    for candidate in dest_dir.glob(f"{stem}*"):
        candidate.unlink(missing_ok=True)


def run(root: str, run_date: str) -> dict:
    project_root = Path(root).resolve()
    project_base = analysis_root(project_root).parent.resolve()
    ensure_layout(project_root)
    criteria_keywords = _criteria_keywords(project_root)
    registry = csv_path(project_root)
    (analysis_root(project_root) / "ras").mkdir(parents=True, exist_ok=True)
    (analysis_root(project_root) / "rechtspraak").mkdir(parents=True, exist_ok=True)
    all_rows = _load_all_rows(registry)
    run_rows = [row for row in all_rows if row.get("run_date") == run_date and row.get("source") in {"ru_ras", "nl_rechtspraak"}]
    rechtspraak_paths = _rechtspraak_texts(project_root, run_date, run_rows)
    ras_paths = _ras_texts(project_root, run_date, run_rows)
    text_paths = {**rechtspraak_paths, **ras_paths}
    base = analysis_root(project_root)
    updated = 0
    kept = 0
    for row in all_rows:
        if row.get("run_date") != run_date or row.get("source") not in {"ru_ras", "nl_rechtspraak"}:
            continue
        text_path = text_paths.get(row["id"])
        if not text_path or not Path(text_path).exists():
            row["analysis_status"] = "fulltext_failed"
            row["relevance"] = ""
            row["summary_comment"] = "Полный текст не получен"
            updated += 1
            continue
        text = Path(text_path).read_text(encoding="utf-8", errors="replace")
        relevance, comment = _relevance_from_text(text, criteria_keywords)
        row["extracted_text_path"] = str(Path(text_path).resolve().relative_to(project_base))
        row["summary_comment"] = comment
        row["relevance"] = relevance
        row["analysis_status"] = "relevant" if relevance == "international_tax" else "irrelevant"
        stem = Path(text_path).stem
        if row["source"] == "ru_ras":
            final_dir = base / "ras"
        else:
            final_dir = base / "rechtspraak"
        if relevance == "international_tax":
            _copy_if_relevant(Path(text_path), final_dir)
            kept += 1
        else:
            _cleanup_irrelevant(final_dir, stem)
        updated += 1
    _write_rows(registry, all_rows)
    return {"updated": updated, "kept": kept, "registry": str(registry)}


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyse all court decisions for a morning run.")
    parser.add_argument("--date", required=True)
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    try:
        result = run(args.root, args.date)
    except (OSError, ValueError, RuntimeError, json.JSONDecodeError) as exc:
        print(f"[court-protocol] error: {exc}", file=sys.stderr)
        return 1
    print(f"[court-protocol] updated={result['updated']} kept={result['kept']} registry={result['registry']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
