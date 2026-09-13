#!/usr/bin/env python3
"""Регрессии Фазы 2: ВС/РАС, full text Rechtspraak и Telegram-лиды."""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT / "scripts"
FIXTURES = PROJECT / "tests" / "fixtures"
sys.path.insert(0, str(SCRIPTS))

import collect_sources  # noqa: E402
import collect_telegram  # noqa: E402
import collect_vs  # noqa: E402
import court_registry  # noqa: E402
import court_protocol  # noqa: E402
import court_morning_run  # noqa: E402
import fetch_rechtspraak_fulltext  # noqa: E402
import make_digest  # noqa: E402
import parse_feeds  # noqa: E402
import select_news  # noqa: E402
import session_guard  # noqa: E402


class TempProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="news_phase2_"))

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def copy_configs(self):
        target = self.tmp / "config"
        target.mkdir(parents=True, exist_ok=True)
        for src in (PROJECT / "config").glob("*.yaml"):
            shutil.copy2(src, target / src.name)


class FakeResponse:
    def __init__(self, content, url="https://official.example/item"):
        self.content = content
        self.url = url

    def raise_for_status(self):
        return None

    def json(self):
        return json.loads(self.content)


class SourceParserTests(TempProject):
    def test_vs_parser_preserves_review_type_and_date(self):
        fragment = """
        <div class="vs-items-title" data-year="2026" data-month="7" data-day="3">
          <a href="/documents/all/34101/">
            Обзор судебной практики Верховного Суда Российской Федерации № 2 (2026)
            <span data-annotation="1">Включена налоговая практика.</span>
          </a>
        </div>
        """
        items = parse_feeds.parse_vs_ajax_json(
            json.dumps({"list": [fragment]}, ensure_ascii=False), {}
        )
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["item_type"], "court_review")
        self.assertEqual(items[0]["published_at"], "2026-07-03")
        self.assertTrue(items[0]["url"].startswith("https://vsrf.ru/"))

    def test_collect_vs_uses_unfiltered_reviews_and_tax_press(self):
        payload = json.dumps({"list": ["<div>ok</div>"]}).encode()
        response = FakeResponse(payload)
        client = mock.Mock()
        client.get.return_value = response
        saved = collect_vs.collect(str(self.tmp), "2026-07-18", session=client)
        self.assertEqual(len(saved), 2)
        calls = client.get.call_args_list
        self.assertNotIn("keyword", calls[0].kwargs["params"])
        self.assertEqual(calls[1].kwargs["params"]["keyword"], "налог")

    def test_minfin_two_digit_year_date(self):
        html = """
        <article><a href="/ru/press-center/?id_4=40001">
        Минфин обсудил механизм SPOT и трансграничные налоги</a>
        <span class="news_date">17.07.26</span></article>
        """
        cfg = {
            "lang": "ru",
            "html": {
                "base": "https://minfin.gov.ru/",
                "include": [r"/ru/press-center/\?id_4="],
            },
        }
        items = parse_feeds.parse_html_links(html, cfg, "ru_minfin")
        self.assertEqual(items[0]["published_at"], "2026-07-17")


class FullTextTests(TempProject):
    def test_rechtspraak_fulltext_writes_raw_text_and_manifest(self):
        xml = b"<?xml version='1.0' encoding='UTF-8'?><uitspraak><id>ECLI:NL:HR:2026:42</id><para>Tax decision text</para></uitspraak>"
        client = mock.Mock()
        client.get.return_value = FakeResponse(xml, "https://data.rechtspraak.nl/content?id=x")
        result = fetch_rechtspraak_fulltext.fetch(
            str(self.tmp), "2026-07-18", only_ecli="ECLI:NL:HR:2026:42",
            session=client, pause=0,
        )
        self.assertEqual(result["items"][0]["state"], "ok")
        out = self.tmp / "pipeline/raw/2026-07-18/rechtspraak_fulltext"
        self.assertIn("Tax decision text", next(out.glob("*.txt")).read_text(encoding="utf-8"))
        self.assertTrue((out / "manifest.json").exists())

    def test_rechtspraak_manifest_accumulates_without_losing_previous_ecli(self):
        client = mock.Mock()
        client.get.side_effect = [
            FakeResponse(b"<uitspraak><id>ECLI:NL:HR:2026:1</id><p>one</p></uitspraak>"),
            FakeResponse(b"<uitspraak><id>ECLI:NL:HR:2026:2</id><p>two</p></uitspraak>"),
        ]
        fetch_rechtspraak_fulltext.fetch(
            str(self.tmp), "2026-07-18",
            eclis=["ECLI:NL:HR:2026:1", "ECLI:NL:HR:2026:2"],
            session=client, pause=0,
        )
        manifest = json.loads(
            (self.tmp / "pipeline/raw/2026-07-18/rechtspraak_fulltext/manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual({item["ecli"] for item in manifest["items"]}, {
            "ECLI:NL:HR:2026:1", "ECLI:NL:HR:2026:2",
        })


class CollectorIntegrationTests(TempProject):
    def test_telegram_refuses_session_used_by_another_process(self):
        returned = SimpleNamespace(stdout="12345\n")
        with mock.patch.object(collect_telegram.shutil, "which", return_value="/usr/bin/lsof"), \
             mock.patch.object(collect_telegram.subprocess, "run", return_value=returned):
            with self.assertRaisesRegex(RuntimeError, "уже используется"):
                collect_telegram.ensure_session_idle(Path("/tmp/test.session"))

    def test_telegram_ownership_check_is_fail_closed_without_lsof(self):
        with mock.patch.object(collect_telegram.shutil, "which", return_value=None):
            with self.assertRaisesRegex(RuntimeError, "lsof не найден"):
                collect_telegram.ensure_session_idle(Path("/tmp/test.session"))

    def test_session_lock_serializes_project_clients(self):
        session = self.tmp / "session.session"
        session.write_bytes(b"fixture")
        session.chmod(0o600)
        with session_guard.exclusive_session_lock(session):
            with self.assertRaisesRegex(RuntimeError, "зарезервирована"):
                with session_guard.exclusive_session_lock(session):
                    pass

    @unittest.skipIf(sys.platform == "win32", "POSIX permissions not supported on Windows")
    def test_session_lock_rejects_group_or_world_readable_file(self):
        session = self.tmp / "session.session"
        session.write_bytes(b"fixture")
        session.chmod(0o644)
        with self.assertRaisesRegex(RuntimeError, "0600"):
            with session_guard.exclusive_session_lock(session):
                pass

    def test_short_empty_collector_envelope_is_valid_input(self):
        self.assertFalse(parse_feeds.looks_like_binary('{"items": []}'))
        self.assertEqual(parse_feeds.parse_json_items('{"items": []}', {}), [])

    def test_cdp_unavailable_is_manual_not_failed(self):
        self.copy_configs()
        returned = SimpleNamespace(returncode=3, stdout="", stderr="CDP_UNAVAILABLE")
        with mock.patch.object(collect_sources.subprocess, "run", return_value=returned):
            manifest = collect_sources.collect(str(self.tmp), "2026-07-18", only="ru_ras")
        self.assertEqual(manifest["sources"]["ru_ras"]["state"], "manual")
        self.assertEqual(manifest["_summary"]["incomplete"], ["ru_ras:manual"])

    def test_targeted_manifests_do_not_erase_other_source_coverage(self):
        raw = self.tmp / "pipeline/raw/2026-07-18"
        raw.mkdir(parents=True)
        (raw / "collection_manifest.json").write_text(json.dumps({
            "date": "2026-07-18",
            "sources": {"ru_garant": {"state": "ok", "files": ["ru_garant_1.txt"]}},
            "_summary": {"ok": ["ru_garant"], "failed": [], "incomplete": []},
        }))
        targeted = {
            "date": "2026-07-18",
            "sources": {"ru_ras": {"state": "manual"}},
            "_summary": {"ok": [], "failed": [], "incomplete": ["ru_ras:manual"]},
        }
        collect_sources._persist_manifest(raw, targeted, only="ru_ras")
        combined = json.loads((raw / "collection_manifest.json").read_text(encoding="utf-8"))
        self.assertEqual(set(combined["sources"]), {"ru_garant", "ru_ras"})
        self.assertTrue((raw / "collection_manifest_ru_ras.json").exists())

    def test_court_manifest_preserves_general_manifest(self):
        raw = self.tmp / "pipeline/raw/2026-07-18"
        raw.mkdir(parents=True)
        (raw / "collection_manifest.json").write_text(json.dumps({
            "date": "2026-07-18", "sources": {"ru_garant": {"state": "ok"}}
        }))
        court = court_morning_run._merge_manifests("2026-07-18", {
            "sources": {"nl_rechtspraak": {"state": "ok"}, "ru_ras": {"state": "manual"}}
        })
        court_morning_run._write_court_manifest(str(self.tmp), "2026-07-18", court)
        general = json.loads((raw / "collection_manifest.json").read_text(encoding="utf-8"))
        receipt = json.loads((raw / "collection_manifest_court.json").read_text(encoding="utf-8"))
        self.assertEqual(set(general["sources"]), {"ru_garant", "nl_rechtspraak", "ru_ras"})
        self.assertEqual(set(receipt["sources"]), {"nl_rechtspraak", "ru_ras"})

    def test_court_artifact_coverage_is_recomputed_from_files(self):
        registry = self.tmp / "court_analysis"
        registry.mkdir(parents=True)
        (registry / "court_decisions.csv").write_text(
            "id,source,run_date,decision_date,case_number,ecli,title,query_text,url,local_artifact_path,extracted_text_path,analysis_status,relevance,summary_comment,notes\n"
            "nl:1,nl_rechtspraak,2026-07-18,2026-07-18,,ECLI:NL:HR:2026:1,t,q,u,raw,court_analysis/extracted_text/rechtspraak/2026-07-18/ECLI_NL_HR_2026_1.txt,relevant,international_tax,c,\n"
            "ras:1,ru_ras,2026-07-18,2026-07-18,А40-1/2026,,t,q,u,raw,,fulltext_failed,,,\n",
            encoding="utf-8",
        )
        nl_raw = self.tmp / "pipeline/raw/2026-07-18/rechtspraak_fulltext"
        nl_raw.mkdir(parents=True)
        (nl_raw / "case.xml").write_text("xml", encoding="utf-8")
        (nl_raw / "case.txt").write_text("text", encoding="utf-8")
        (nl_raw / "manifest.json").write_text(json.dumps({
            "date": "2026-07-18", "items": [{
                "ecli": "ECLI:NL:HR:2026:1", "state": "ok",
                "file": "case.xml", "text_file": "case.txt",
            }],
        }))
        nl_canonical = registry / "extracted_text/rechtspraak/2026-07-18"
        nl_canonical.mkdir(parents=True)
        (nl_canonical / "ECLI_NL_HR_2026_1.txt").write_text("text", encoding="utf-8")
        coverage = court_morning_run._court_artifact_coverage(str(self.tmp), "2026-07-18")
        self.assertTrue(coverage["nl_rechtspraak"]["complete"])
        self.assertFalse(coverage["ru_ras"]["complete"])
        self.assertFalse(coverage["complete"])

    def test_court_registry_is_written_to_root_level_analysis_folder(self):
        rows = [
            {
                "source": "ru_ras",
                "url": "https://ras.example/doc.pdf",
                "act": "А40-185826/2024",
                "title": "Арбитражное дело А40-185826/2024: избежании двойного налогообложения",
                "summary": "Оставить без изменения решение",
                "published_at": "2026-07-14",
                "query": "избежании двойного налогообложения",
            },
            {
                "source": "nl_rechtspraak",
                "url": "https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2026:1287",
                "ecli": "ECLI:NL:HR:2026:1287",
                "title": "ECLI:NL:HR:2026:1287",
                "summary": "Belastingrecht",
                "published_at": "2026-07-17",
            },
        ]
        exported, registry = court_registry.upsert_court_decisions(self.tmp, "2026-07-18", rows)
        self.assertEqual(exported, 2)
        registry_path = Path(registry)
        self.assertEqual(registry_path.resolve(), (self.tmp / "court_analysis" / "court_decisions.csv").resolve())
        content = registry_path.read_text(encoding="utf-8")
        self.assertIn("ru_ras:А40-185826/2024:2026-07-14", content)
        self.assertIn("nl_rechtspraak:ECLI:NL:HR:2026:1287", content)
        self.assertIn("News Claude/pipeline/raw/2026-07-18/ru_ras_1.txt", content)
        self.assertIn("News Claude/pipeline/raw/2026-07-18/nl_rechtspraak_2.txt", content)

    def test_court_protocol_keeps_only_international_tax_decisions(self):
        registry = self.tmp / "court_analysis"
        registry.mkdir(parents=True, exist_ok=True)
        csv_path = registry / "court_decisions.csv"
        csv_path.write_text(
            "id,source,run_date,decision_date,case_number,ecli,title,query_text,url,local_artifact_path,extracted_text_path,analysis_status,relevance,summary_comment,notes\n"
            "ru_ras:1,ru_ras,2026-07-18,2026-07-14,А40-185826/2024,,Арбитражное дело А40-185826/2024,избежании двойного налогообложения,https://ras.example/1,News Claude/pipeline/raw/2026-07-18/ru_ras_1.txt,,collected,,,,\n"
            "nl_rechtspraak:1,nl_rechtspraak,2026-07-18,2026-07-18,,ECLI:NL:HR:2026:1287,ECLI:NL:HR:2026:1287,bestuursrecht_belastingrecht,https://uitspraken.example/1,News Claude/pipeline/raw/2026-07-18/nl_rechtspraak_1.txt,,collected,,,,\n",
            encoding="utf-8",
        )
        ras_dir = registry / "extracted_text" / "ras" / "2026-07-18"
        ras_dir.mkdir(parents=True, exist_ok=True)
        (ras_dir / "А40-185826_2024__2026-07-14.txt").write_text(
            "Спор о применении соглашения об избежании двойного налогообложения и фактическом праве на доход.",
            encoding="utf-8",
        )
        nl_dir = registry / "extracted_text" / "rechtspraak_fulltext"
        nl_dir.mkdir(parents=True, exist_ok=True)
        (nl_dir / "ECLI_NL_HR_2026_1287.txt").write_text(
            "Korte procedurele beslissing zonder belastingverdrag of internationale fiscale analyse.",
            encoding="utf-8",
        )
        with mock.patch.object(court_protocol, "_rechtspraak_texts", return_value={"nl_rechtspraak:1": nl_dir / "ECLI_NL_HR_2026_1287.txt"}), \
             mock.patch.object(court_protocol, "_ras_texts", return_value={"ru_ras:1": ras_dir / "А40-185826_2024__2026-07-14.txt"}):
            result = court_protocol.run(str(self.tmp), "2026-07-18")
        self.assertEqual(result["updated"], 2)
        self.assertEqual(result["kept"], 1)
        curated_ras = registry / "ras"
        curated_nl = registry / "rechtspraak"
        self.assertTrue(any(curated_ras.iterdir()))
        self.assertFalse(any(curated_nl.iterdir()))

    @unittest.skipUnless(shutil.which("node"), "node is unavailable")
    def test_ras_fixture_filters_noise_and_keeps_act(self):
        result = subprocess.run(
            [
                shutil.which("node"), str(SCRIPTS / "collect_ru_ras.js"),
                "--date", "2026-07-18", "--root", str(self.tmp),
                "--fixture", str(FIXTURES / "ras_rows.json"),
            ],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(
            (self.tmp / "pipeline/raw/2026-07-18/ru_ras_1.txt").read_text(encoding="utf-8")
        )
        self.assertEqual(len(payload["items"]), 1)
        self.assertEqual(payload["items"][0]["act"], "А40-185826/2024")

    @unittest.skipUnless(shutil.which("node"), "node is unavailable")
    def test_ras_window_helper_rejects_explicit_old_decision(self):
        script = (
            "const m=require(process.argv[1]);"
            "process.stdout.write(String(m.isExplicitlyInWindow('2026-06-01','2026-07-12','2026-07-18')));"
        )
        result = subprocess.run(
            [shutil.which("node"), "-e", script, str(SCRIPTS / "collect_ru_ras.js")],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(result.stdout, "false")

    def test_telegram_fixture_reaches_shortlist_with_lead_warning(self):
        self.copy_configs()
        result = subprocess.run(
            [
                sys.executable, str(SCRIPTS / "collect_telegram.py"),
                "--date", "2026-07-18", "--root", str(self.tmp),
                "--config", "unused", "--session", "unused", "--env", "unused",
                "--fixture", str(FIXTURES / "telegram_leads.json"),
            ],
            text=True, capture_output=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        parsed = parse_feeds.run("2026-07-18", str(self.tmp))
        self.assertEqual(parsed["total"], 1)
        selected = select_news.run("2026-07-18", 15, str(self.tmp))
        shortlist = json.loads(Path(selected["out_path"]).read_text(encoding="utf-8"))
        lead = shortlist["items"][0]
        self.assertTrue(lead["lead"])
        self.assertEqual(lead["channel"], "@example_tax")
        self.assertEqual(lead["engagement"], 50.0)
        digest = make_digest.build_markdown(shortlist, "test")
        self.assertIn("Telegram lead", digest)
        self.assertIn("первоисточник ОБЯЗАТЕЛЬНО подтвердить", digest)


if __name__ == "__main__":
    unittest.main(verbosity=2)
