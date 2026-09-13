#!/usr/bin/env python3
"""Экспорт судебных решений в корневой реестр Новости Академии/court_analysis."""

from __future__ import annotations

import csv
import hashlib
import os
import tempfile
from datetime import date as date_cls, timedelta
from pathlib import Path

FIELDS = [
    "id", "source", "run_date", "decision_date", "case_number", "ecli", "title",
    "query_text", "url", "local_artifact_path", "extracted_text_path",
    "analysis_status", "relevance", "summary_comment", "notes",
]
COURT_SOURCES = {"ru_ras", "nl_rechtspraak"}


def analysis_root(root: str | Path) -> Path:
    news_root = Path(root).resolve()
    if news_root.name == "News Claude":
        return news_root.parent / "court_analysis"
    return news_root / "court_analysis"


def csv_path(root: str | Path) -> Path:
    return analysis_root(root) / "court_decisions.csv"


def ensure_layout(root: str | Path) -> Path:
    base = analysis_root(root)
    (base / "ras").mkdir(parents=True, exist_ok=True)
    (base / "rechtspraak").mkdir(parents=True, exist_ok=True)
    (base / "extracted_text").mkdir(parents=True, exist_ok=True)
    target = base / "court_decisions.csv"
    if not target.exists():
        target.write_text(",".join(FIELDS) + "\n", encoding="utf-8")
    return target


def _decision_id(item: dict) -> str:
    source = str(item.get("source") or "")
    ecli = str(item.get("ecli") or "").strip()
    if source == "nl_rechtspraak" and ecli:
        return f"{source}:{ecli}"
    act = str(item.get("act") or item.get("case_number") or "").strip()
    decision_date = str(item.get("published_at") or "").strip()
    if source == "ru_ras" and act:
        return f"{source}:{act}:{decision_date}"
    seed = "|".join([
        source,
        str(item.get("url") or ""),
        ecli,
        act,
        decision_date,
        str(item.get("title") or ""),
    ])
    return f"{source}:{hashlib.sha1(seed.encode('utf-8')).hexdigest()[:16]}"


def _artifact_path(root: str | Path, run_date: str, item: dict) -> str:
    source = str(item.get("source") or "")
    if source == "ru_ras":
        return f"News Claude/pipeline/raw/{run_date}/ru_ras_1.txt"
    if source == "nl_rechtspraak":
        decision_date = str(item.get("published_at") or "")
        try:
            if decision_date == run_date:
                suffix = "1"
            elif decision_date == (date_cls.fromisoformat(run_date) - timedelta(days=1)).isoformat():
                suffix = "2"
            else:
                suffix = ""
        except ValueError:
            suffix = ""
        if suffix:
            return f"News Claude/pipeline/raw/{run_date}/nl_rechtspraak_{suffix}.txt"
        return f"News Claude/pipeline/raw/{run_date}/"
    return ""


def _query_text(item: dict) -> str:
    if item.get("source") == "ru_ras":
        return str(item.get("query") or "избежании двойного налогообложения")
    if item.get("source") == "nl_rechtspraak":
        return "bestuursrecht_belastingrecht"
    return str(item.get("query") or "")


def _load_existing(target: Path) -> dict[str, dict]:
    if not target.exists():
        return {}
    rows: dict[str, dict] = {}
    with target.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle):
            if not row.get("id"):
                continue
            rows[row["id"]] = {field: row.get(field, "") for field in FIELDS}
    return rows


def upsert_court_decisions(root: str | Path, run_date: str, items: list[dict]) -> tuple[int, str]:
    target = ensure_layout(root)
    rows = _load_existing(target)
    touched = 0
    for item in items:
        source = str(item.get("source") or "")
        if source not in COURT_SOURCES:
            continue
        row_id = _decision_id(item)
        existing = rows.get(row_id, {})
        row = {field: existing.get(field, "") for field in FIELDS}
        row.update({
            "id": row_id,
            "source": source,
            "run_date": run_date,
            "decision_date": str(item.get("published_at") or ""),
            "case_number": str(item.get("act") or item.get("case_number") or ""),
            "ecli": str(item.get("ecli") or ""),
            "title": str(item.get("title") or ""),
            "query_text": _query_text(item),
            "url": str(item.get("url") or ""),
            "local_artifact_path": _artifact_path(root, run_date, item),
            "extracted_text_path": existing.get("extracted_text_path", ""),
            "analysis_status": existing.get("analysis_status") or "collected",
            "relevance": existing.get("relevance", ""),
            "summary_comment": existing.get("summary_comment", ""),
            "notes": existing.get("notes", ""),
        })
        rows[row_id] = row
        touched += 1
    if touched:
        fd, tmp_name = tempfile.mkstemp(prefix=".court_decisions.", dir=target.parent)
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            with tmp.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=FIELDS)
                writer.writeheader()
                for key in sorted(rows):
                    writer.writerow(rows[key])
            os.replace(tmp, target)
        finally:
            tmp.unlink(missing_ok=True)
    return touched, str(target)
