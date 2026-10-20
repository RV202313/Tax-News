#!/usr/bin/env python3
"""Регрессии Фазы 1: персистентность, каталог, транспорт и парсеры."""

import json
import os
import shutil
import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import yaml

PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import collect_sources  # noqa: E402
import newsdb  # noqa: E402
import parse_feeds  # noqa: E402
import select_news  # noqa: E402


class TempProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="news_phase1_"))
        self.newsdb_connections = []
        self.sqlite_connections = []

    def tearDown(self):
        for conn in reversed(self.sqlite_connections):
            conn.close()
        for conn in reversed(self.newsdb_connections):
            newsdb.close(conn)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def track_newsdb(self, conn):
        self.newsdb_connections.append(conn)

    def track_sqlite(self, conn):
        self.sqlite_connections.append(conn)

    def copy_configs(self):
        target = self.tmp / "config"
        target.mkdir(parents=True, exist_ok=True)
        for src in (PROJECT / "config").glob("*.yaml"):
            shutil.copy2(src, target / src.name)


class PersistenceTests(TempProject):
    def test_old_schema_migrates_without_recreation(self):
        dest = Path(newsdb.db_path(str(self.tmp)))
        dest.parent.mkdir(parents=True)
        old = sqlite3.connect(dest)
        old.execute(
            """CREATE TABLE items (
                id INTEGER PRIMARY KEY, url TEXT UNIQUE, ecli TEXT, source TEXT,
                title TEXT, title_norm TEXT, summary TEXT, published_at TEXT,
                first_seen TEXT, run_date TEXT, score REAL, topics TEXT,
                status TEXT, channels TEXT
            )"""
        )
        old.execute(
            "INSERT INTO items(url,title,first_seen) VALUES (?,?,?)",
            ("https://example.test/preserve", "preserve", newsdb.now_iso()),
        )
        old.commit()
        old.close()
        conn = newsdb.connect(str(self.tmp))
        self.track_newsdb(conn)
        columns = {r[1] for r in conn.execute("PRAGMA table_info(items)")}
        self.assertIn("act", columns)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0], 1)
        self.assertEqual(list(dest.parent.glob("news_state.sqlite.bak-*")), [])

    def test_unreadable_existing_dest_is_not_overwritten(self):
        dest = Path(newsdb.db_path(str(self.tmp)))
        dest.parent.mkdir(parents=True)
        original = b"must-survive-copy-error"
        dest.write_bytes(original)
        real_copy = newsdb.shutil.copyfile

        def fail_source(src, dst, *args, **kwargs):
            if os.path.abspath(src) == os.path.abspath(dest):
                raise OSError("simulated read failure")
            return real_copy(src, dst, *args, **kwargs)

        with mock.patch.object(newsdb.shutil, "copyfile", side_effect=fail_source):
            with self.assertRaises(newsdb.PersistenceError):
                newsdb.connect(str(self.tmp))
        self.assertEqual(dest.read_bytes(), original)

    def test_corrupt_dest_is_backed_up_before_recreate(self):
        dest = Path(newsdb.db_path(str(self.tmp)))
        dest.parent.mkdir(parents=True)
        original = b"not-a-sqlite-database"
        dest.write_bytes(original)
        conn = newsdb.connect(str(self.tmp))
        self.track_newsdb(conn)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM items").fetchone()[0], 0)
        backups = list(dest.parent.glob("news_state.sqlite.bak-*"))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), original)
        persisted = sqlite3.connect(dest)
        self.track_sqlite(persisted)
        persisted.execute("SELECT COUNT(*) FROM items").fetchone()

    @unittest.skipIf(os.name == "nt", "Windows uses direct SQLite, not the FUSE mirror")
    def test_failed_atomic_replace_preserves_target(self):
        conn = newsdb.connect(str(self.tmp))
        self.track_newsdb(conn)
        dest = Path(newsdb.db_path(str(self.tmp)))
        before = dest.read_bytes()
        conn.execute(
            "INSERT INTO runs(run_date, started) VALUES (?, ?)",
            ("2099-01-01", "now"),
        )
        conn.commit()
        with mock.patch.object(newsdb.os, "replace", side_effect=OSError("simulated")):
            self.assertFalse(newsdb.sync(conn))
        self.assertEqual(dest.read_bytes(), before)
        self.assertTrue((self.tmp / "log" / "newsdb_sync.log").exists())


class CatalogTests(TempProject):
    def test_item_ecli_dedup_is_case_insensitive(self):
        conn = newsdb.connect(str(self.tmp))
        self.track_newsdb(conn)
        item_id, is_new = newsdb.upsert_item(
            conn,
            {
                "url": "https://example.test/ecli-upper",
                "ecli": "ecli:nl:hr:2026:42",
                "title": "Tax judgment",
            },
        )
        self.assertTrue(is_new)
        self.assertEqual(
            conn.execute("SELECT ecli FROM items WHERE id=?", (item_id,)).fetchone()[0],
            "ECLI:NL:HR:2026:42",
        )
        self.assertTrue(
            newsdb.is_duplicate(
                conn, "https://example.test/another", "ECLI:nl:hr:2026:42", "other"
            )
        )

    def test_catalog_ingest_is_idempotent_and_blocks_keys(self):
        conn = newsdb.connect(str(self.tmp))
        self.track_newsdb(conn)
        catalog = self.tmp / "catalog.md"
        catalog.write_text(
            "| Дата | ID канала | ID чата | Статус | Заголовок | Нормализованная тема | Юрисдикции | Акт | Источники |\n"
            "|---|---|---|---|---|---|---|---|---|\n"
            "| 2026-07-17 | — | 10 | На обсуждении | Суд решил налоговый спор | Судебный налоговый спор | NL | ECLI:NL:HR:2026:42 | [Суд](https://example.test/case) |\n",
            encoding="utf-8",
        )
        self.assertEqual(newsdb.ingest_published_catalog(conn, str(catalog)), 1)
        self.assertEqual(newsdb.ingest_published_catalog(conn, str(catalog)), 1)
        self.assertEqual(conn.execute("SELECT COUNT(*) FROM catalog_entries").fetchone()[0], 1)
        self.assertTrue(newsdb.is_duplicate(conn, "https://example.test/case", "", "другое"))
        self.assertTrue(newsdb.is_duplicate(conn, "", "ECLI:NL:HR:2026:42", "другое"))
        self.assertTrue(newsdb.is_duplicate(
            conn, "", "", "другое", newsdb.normalize_title("ECLI:NL:HR:2026:42")
        ))
        self.assertTrue(newsdb.is_duplicate(
            conn, "", "", newsdb.normalize_title("Суд решил налоговый спор")
        ))


class ParserTransportTests(TempProject):
    def test_short_tax_abbreviation_does_not_match_japan(self):
        topics = [{'id': 'apa', 'priority': 1, 'keywords': ['apa']}]
        self.assertFalse(select_news.match_topics('Toshiba expands Japanese capacity', topics)[3])
        self.assertTrue(select_news.match_topics('APA tax agreement', topics)[3])

    def test_unpublished_collected_item_remains_available_but_receipt_blocks_it(self):
        conn = newsdb.connect(str(self.tmp))
        self.track_newsdb(conn)
        item_id, _ = newsdb.upsert_item(conn, {'url': 'https://example.test/reserve',
            'title': 'International tax treaty reserve', 'status': 'collected'})
        title = newsdb.normalize_title('International tax treaty reserve')
        self.assertFalse(newsdb.is_duplicate(conn, 'https://example.test/reserve', '', title, include_collected=False))
        newsdb.add_published(conn, item_id, 'telegram', post_id='42')
        self.assertTrue(newsdb.is_duplicate(conn, 'https://example.test/reserve', '', title, include_collected=False))

    RSS = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss version="2.0"><channel><item><title>International tax treaty update</title>
<link>https://example.test/treaty?utm_source=rss</link><description><![CDATA[<p>Summary</p>]]></description>
<pubDate>Fri, 17 Jul 2026 08:00:00 +0000</pubDate></item></channel></rss>"""

    def test_generic_rss_parser(self):
        items = parse_feeds.parse_rss_atom(self.RSS.decode(), {})
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["url"], "https://example.test/treaty")
        self.assertEqual(items[0]["published_at"], "2026-07-17")
        self.assertEqual(items[0]["summary"], "Summary")

    def test_rss_honours_source_url_excludes(self):
        rss = self.RSS.replace(
            b"https://example.test/treaty?utm_source=rss",
            b"https://example.test/agenda/course?utm_source=rss",
        )
        items = parse_feeds.parse_rss_atom(
            rss.decode(),
            {"html": {"base": "https://example.test/", "exclude": ["/agenda/"]}},
        )
        self.assertEqual(items, [])

    def test_html_prefers_card_publication_date(self):
        html = """
        <div class="card"><a href="/doc/tax-case">Belastingrente na arrest Hoge Raad</a>
        <p>Arrest van 16 januari 2026 over fiscale rente.</p>
        <span class="wk-icon-calendar"></span>17 juli 2026</div>
        """
        src = {
            "lang": "nl",
            "html": {
                "base": "https://example.test/",
                "include": [r"/doc/"],
            },
        }
        items = parse_feeds.parse_html_links(html, src, "sample")
        self.assertEqual(len(items), 1)
        self.assertEqual(items[0]["published_at"], "2026-07-17")

    def test_rss_first_skips_html_and_marks_manual(self):
        (self.tmp / "config").mkdir(parents=True)
        (self.tmp / "config" / "sources.yaml").write_text(
            "sources:\n"
            "  - id: feed\n    method: http\n    parser: auto\n"
            "    rss_endpoints: [https://example.test/feed]\n"
            "    endpoints: [https://example.test/html]\n"
            "  - id: browser\n    method: chrome\n    parser: none\n",
            encoding="utf-8",
        )
        calls = []

        def fake_fetch(_session, url):
            calls.append(url)
            return self.RSS, 200, "application/rss+xml", url, None

        with mock.patch.object(collect_sources, "fetch", side_effect=fake_fetch), \
             mock.patch.object(collect_sources, "PAUSE", 0):
            manifest = collect_sources.collect(str(self.tmp), "2026-07-17")
        self.assertEqual(calls, ["https://example.test/feed"])
        self.assertEqual(manifest["sources"]["feed"]["state"], "ok")
        self.assertEqual(manifest["_summary"]["incomplete"], ["browser:manual"])
        saved_manifest = json.loads(
            (self.tmp / "pipeline/raw/2026-07-17/collection_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        self.assertEqual(saved_manifest["_summary"], manifest["_summary"])
        self.assertEqual(
            (self.tmp / "pipeline/raw/2026-07-17/feed_1.txt").read_bytes(), self.RSS
        )

    def test_cross_source_batch_duplicate_keeps_one(self):
        self.copy_configs()
        inbox = self.tmp / "pipeline" / "inbox"
        inbox.mkdir(parents=True)
        title = "ФНС установила новый порядок автоматического обмена данными"
        records = [
            {"source": "ru_garant", "url": "https://a.test/1", "ecli": "",
             "title": title, "summary": "обмен налоговой информацией",
             "published_at": "2026-07-17", "lang": "ru"},
            {"source": "ru_fns", "url": "https://b.test/2", "ecli": "",
             "title": title, "summary": "обмен налоговой информацией",
             "published_at": "2026-07-17", "lang": "ru"},
        ]
        (inbox / "2026-07-17_items.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8",
        )
        result = select_news.run("2026-07-17", 15, str(self.tmp))
        self.assertEqual(result["n_shortlisted"], 1)

    def test_broad_source_requires_target_topic(self):
        self.copy_configs()
        sources_path = self.tmp / "config" / "sources.yaml"
        sources = yaml.safe_load(sources_path.read_text(encoding="utf-8"))
        for source in sources["sources"]:
            if source["id"] == "ru_fns":
                source["require_topics_any"] = ["exchange_info"]
        sources_path.write_text(
            yaml.safe_dump(sources, allow_unicode=True, sort_keys=False),
            encoding="utf-8",
        )
        inbox = self.tmp / "pipeline" / "inbox"
        inbox.mkdir(parents=True)
        records = [
            {
                "source": "ru_fns",
                "url": "https://example.test/domestic",
                "title": "ФНС напомнила срок подачи налоговой декларации",
                "summary": "НК РФ и налоговое администрирование",
                "published_at": "2026-07-17",
            },
            {
                "source": "ru_fns",
                "url": "https://example.test/crs",
                "title": "ФНС обновила правила автоматического обмена по CRS",
                "summary": "Международный обмен налоговой информацией",
                "published_at": "2026-07-17",
            },
        ]
        (inbox / "2026-07-17_items.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
            encoding="utf-8",
        )
        result = select_news.run("2026-07-17", 15, str(self.tmp))
        shortlist = json.loads(
            Path(result["out_path"]).read_text(encoding="utf-8")
        )
        self.assertEqual(
            [item["url"] for item in shortlist["items"]],
            ["https://example.test/crs"],
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
