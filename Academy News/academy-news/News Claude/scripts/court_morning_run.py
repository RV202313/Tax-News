#!/usr/bin/env python3
"""Утренний запуск судебного блока в 07:00: RAS + Rechtspraak."""

from __future__ import annotations

import argparse
import csv
import json
import os
import tempfile
from datetime import date as date_cls
from pathlib import Path

import collect_sources
import court_protocol
import parse_feeds
from court_registry import analysis_root, csv_path


def _merge_manifests(run_date: str, *manifests: dict) -> dict:
    """Собрать единый manifest court-run из точечных collect(..., only=...)."""
    sources = {}
    for manifest in manifests:
        for sid, rec in (manifest or {}).get("sources", {}).items():
            sources[sid] = rec

    ok, failed, incomplete = [], [], []
    for sid, rec in sources.items():
        state = rec.get("state")
        if state == "ok":
            ok.append(sid)
        elif state in {"failed", "missing"}:
            failed.append(sid)
        elif state in {"manual", "delegated"}:
            incomplete.append(f"{sid}:{state}")

    return {
        "date": run_date,
        "sources": sources,
        "_summary": {
            "ok": sorted(ok),
            "failed": sorted(failed),
            "incomplete": sorted(incomplete),
        },
    }


def _write_court_manifest(root: str, run_date: str, manifest: dict) -> None:
    raw_dir = Path(root).resolve() / "pipeline" / "raw" / run_date
    raw_dir.mkdir(parents=True, exist_ok=True)

    def atomic_write(path: Path, value: dict) -> None:
        fd, tmp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
        os.close(fd)
        tmp = Path(tmp_name)
        try:
            tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
            os.replace(tmp, path)
        finally:
            tmp.unlink(missing_ok=True)

    # Court receipt содержит только обязательные судебные источники.
    atomic_write(raw_dir / "collection_manifest_court.json", manifest)

    # Общий manifest остаётся накопительным: судебный запуск не имеет права
    # стирать уже собранные web/Telegram-источники этого дня.
    general_path = raw_dir / "collection_manifest.json"
    general_sources = {}
    if general_path.exists():
        try:
            current = json.loads(general_path.read_text(encoding="utf-8"))
            if current.get("date") == run_date:
                general_sources = dict(current.get("sources") or {})
        except (OSError, ValueError, json.JSONDecodeError):
            general_sources = {}
    general_sources.update(manifest.get("sources") or {})
    general = _merge_manifests(run_date, {"sources": general_sources})
    atomic_write(general_path, general)


def _load_json(path: Path) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError):
        return {}


def _court_artifact_coverage(root: str, run_date: str) -> dict:
    """Recompute full-text/analysis coverage from actual court artifacts."""
    project = Path(root).resolve()
    base = analysis_root(project)
    project_base = base.parent
    registry_path = csv_path(project)
    rows = []
    if registry_path.exists():
        with registry_path.open("r", encoding="utf-8", newline="") as handle:
            rows = [
                row for row in csv.DictReader(handle)
                if row.get("run_date") == run_date
                and row.get("source") in {"nl_rechtspraak", "ru_ras"}
            ]

    def path_exists(value: str) -> bool:
        if not value:
            return False
        path = Path(value)
        if not path.is_absolute():
            path = project_base / path
        return path.is_file()

    result = {}
    for source, identity_field in (("nl_rechtspraak", "ecli"), ("ru_ras", "case_number")):
        source_rows = [row for row in rows if row.get("source") == source]
        expected = {row.get(identity_field) for row in source_rows if row.get(identity_field)}
        if source == "nl_rechtspraak":
            manifest_path = project / "pipeline" / "raw" / run_date / "rechtspraak_fulltext" / "manifest.json"
            items = (_load_json(manifest_path).get("items") or [])
            fetched = {
                item.get("ecli") for item in items
                if item.get("state") in {"ok", "existing"}
                and (manifest_path.parent / str(item.get("file") or "")).is_file()
                and (manifest_path.parent / str(item.get("text_file") or "")).is_file()
            }
        else:
            manifest_path = base / "extracted_text" / "ras" / run_date / "manifest.json"
            items = (_load_json(manifest_path).get("items") or [])
            fetched = {
                item.get("case_number") for item in items
                if item.get("state") == "ok"
                and item.get("pdf_path") and Path(item["pdf_path"]).is_file()
            }
        analyzed = {
            row.get(identity_field) for row in source_rows
            if row.get(identity_field)
            and row.get("analysis_status") in {"relevant", "irrelevant"}
            and path_exists(row.get("extracted_text_path") or "")
        }
        relevant = {
            row.get(identity_field) for row in source_rows
            if row.get(identity_field) and row.get("analysis_status") == "relevant"
        }
        result[source] = {
            "registry_cases": len(expected),
            "fulltext_ok": len(expected & fetched),
            "analyzed_ok": len(expected & analyzed),
            "relevant": len(relevant),
            "missing_fulltext": sorted(expected - fetched),
            "missing_analysis": sorted(expected - analyzed),
            "manifest": str(manifest_path.relative_to(project_base)),
            "complete": expected <= fetched and expected <= analyzed,
        }
    result["complete"] = all(record["complete"] for record in result.values())
    return result


def run(root: str, run_date: str) -> dict:
    nl_manifest = collect_sources.collect(root, run_date, only="nl_rechtspraak")
    ras_manifest = collect_sources.collect(root, run_date, only="ru_ras")
    merged_manifest = _merge_manifests(run_date, nl_manifest, ras_manifest)
    # Preliminary receipt survives a later parse/full-text failure and never
    # claims artifact completeness before the court protocol has run.
    merged_manifest["artifacts"] = {"complete": False, "state": "not_run"}
    _write_court_manifest(root, run_date, merged_manifest)
    parsed = parse_feeds.run(run_date, root)
    protocol = court_protocol.run(root, run_date)
    merged_manifest["artifacts"] = _court_artifact_coverage(root, run_date)
    merged_manifest["_summary"]["complete"] = (
        not merged_manifest["_summary"]["failed"]
        and not merged_manifest["_summary"]["incomplete"]
        and merged_manifest["artifacts"]["complete"]
    )
    _write_court_manifest(root, run_date, merged_manifest)
    return {
        "parsed": parsed["total"],
        "sources_ok": ",".join(merged_manifest["_summary"]["ok"]),
        "sources_incomplete": ",".join(merged_manifest["_summary"]["incomplete"]),
        "complete": merged_manifest["_summary"]["complete"],
        **protocol,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="07:00 court-only morning run.")
    parser.add_argument("--date", default=date_cls.today().isoformat())
    parser.add_argument("--root", default=".")
    args = parser.parse_args()
    result = run(args.root, args.date)
    print(
        f"[court-morning] parsed={result['parsed']} updated={result['updated']} "
        f"kept={result['kept']} complete={str(result['complete']).lower()}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
