#!/usr/bin/env python3
"""Офлайн-приёмка raw → inbox → shortlist → digest → approved → delivery state."""

import asyncio
import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PROJECT = Path(__file__).resolve().parents[1]
SCRIPTS = PROJECT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import make_digest  # noqa: E402
import newsdb  # noqa: E402
import parse_feeds  # noqa: E402
import publish_batch  # noqa: E402
import select_news  # noqa: E402


CATALOG = """# Каталог

| Дата | ID канала | ID чата | Статус | Заголовок | Нормализованная тема | Юрисдикции | Акт | Источники |
|---|---:|---:|---|---|---|---|---|---|
"""


class FakeClient:
    def __init__(self, *_):
        self.calls = []
        self.next_id = 900

    async def connect(self):
        self.calls.append("connect")

    async def get_me(self):
        self.calls.append("get_me")
        return SimpleNamespace(username="academy_of_beps")

    async def iter_messages(self, chat_id, limit):
        if False:
            yield None

    async def send_file(self, chat_id, image, **kwargs):
        self.calls.append(("send_file", chat_id, image, kwargs))
        self.next_id += 1
        return SimpleNamespace(id=self.next_id)

    async def disconnect(self):
        self.calls.append("disconnect")


class EndToEndAcceptance(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="news_phase4_"))
        self.root = self.tmp / "News Claude"
        self.root.mkdir()
        shutil.copytree(PROJECT / "config", self.root / "config")
        (self.tmp / "ОПУБЛИКОВАННЫЕ_НОВОСТИ.md").write_text(CATALOG, encoding="utf-8")
        self.raw = self.root / "pipeline/raw/2099-01-01"
        self.raw.mkdir(parents=True)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_raw(self):
        topics = [
            "ФНС России обновила CRS и автоматический обмен налоговой информацией",
            "Россия уточнила контроль трансфертного ценообразования",
            "Россия и Казахстан обсудили соглашение об избежании двойного налогообложения",
            "Минфин России разъяснил постоянное представительство нерезидента",
            "ФНС напомнила о фактическом праве на доход при выплате дивидендов",
            "Россия подготовила правила Pillar Two и minimum tax",
            "ФНС изменила CbCR и страновую отчётность международных групп",
            "Россия уточнила налог у источника с трансграничных дивидендов",
            "Минфин описал взаимосогласительную процедуру MAP по налоговому соглашению",
            "ФНС запустила SPOT и контроль НДС при импорте из ЕАЭС",
        ]
        leads = []
        for number, title in enumerate(topics, start=1):
            leads.append({
                "url": f"https://example.test/official/{number}",
                "title": title,
                "summary": title,
                "published_at": "2099-01-01",
                "item_type": "telegram_lead", "lead": True,
                "channel": "@fixture", "message_id": number,
                "engagement": number * 2,
            })
        (self.raw / "telegram_leads_1.txt").write_text(
            json.dumps({"items": leads}, ensure_ascii=False), encoding="utf-8"
        )
        (self.raw / "ru_ras_1.txt").write_text(json.dumps({"items": [{
            "url": "https://ras.arbitr.ru/case/fixture",
            "act": "А40-100/2099", "title": "Арбитражное дело о двойном налогообложении",
            "summary": "Россия, соглашение об избежании двойного налогообложения",
            "published_at": "2099-01-01", "item_type": "court_decision"
        }]} , ensure_ascii=False), encoding="utf-8")
        (self.raw / "nl_rechtspraak_1.txt").write_text(
            "<feed><entry><id>ECLI:NL:HR:2099:1</id><title>Hoge Raad transfer pricing</title>"
            "<summary>Belastingrecht Nederland transfer pricing</summary><updated>2099-01-01T00:00:00Z</updated>"
            "<link rel=\"alternate\" href=\"https://uitspraken.rechtspraak.nl/details?id=ECLI:NL:HR:2099:1\"/>"
            "</entry></feed>", encoding="utf-8"
        )
        review = (
            '<div class="vs-items-title" data-year="2099" data-month="1" data-day="1">'
            '<a href="/documents/all/fixture/">Обзор судебной практики Верховного Суда Российской Федерации № 1 (2099)'
            '<span data-annotation="1">Налог и трансфертное ценообразование.</span></a></div>'
        )
        (self.raw / "ru_vs_1.txt").write_text(
            json.dumps({"list": [review]}, ensure_ascii=False), encoding="utf-8"
        )
        (self.raw / "ru_minfin_1.txt").write_text(
            '<a href="/ru/press-center/?id_4=999">Минфин России обсудил трансфертное ценообразование</a>'
            '<span class="news_date">01.01.99</span>', encoding="utf-8"
        )

    def test_end_to_end_without_external_network(self):
        self.write_raw()
        parsed = parse_feeds.run("2099-01-01", str(self.root))
        self.assertGreaterEqual(parsed["total"], 13)
        conn = newsdb.connect(str(self.root))
        newsdb.upsert_run(
            conn, "2099-01-01",
            sources_ok="nl_rechtspraak,ru_ras,ru_vs,ru_minfin,telegram_leads",
            sources_failed="",
        )
        newsdb.close(conn)
        first = select_news.run("2099-01-01", 10, str(self.root))
        shortlist = json.loads(Path(first["out_path"]).read_text(encoding="utf-8"))
        self.assertEqual(len(shortlist["items"]), 10)
        digest_path = make_digest.run("2099-01-01", str(self.root))
        digest = Path(digest_path).read_text(encoding="utf-8")
        self.assertIn("telegram_leads", digest)
        self.assertIn("первоисточник ОБЯЗАТЕЛЬНО", digest)

        release_items = []
        court_sources = {"nl_rechtspraak", "ru_ras", "ru_vs"}
        for item in shortlist["items"]:
            url = item["url"]
            court = item["source"] in court_sources
            disclaimer = "\n\nМатериал не является налоговой консультацией." if court else ""
            title = item["title"]
            title = title.replace("Hoge Raad transfer pricing", "Решение Верховного Суда по трансфертному ценообразованию")
            title = title.replace("minimum tax", "минимального налога")
            title = title.replace("CbCR", "страновой отчетности")
            release_items.append({
                "slug": f"2099-01-01-{item['n']:02d}-{item['source'].replace('_', '-')}",
                "title": title,
                "caption": (
                    f"{title}\n\nИсточник: {url}{disclaimer}\n\n"
                    "#налоги #АкадемияBEPS #АкадемияБЕПС"
                ),
                "theme": "Налоговая тема: " + ",".join(item.get("topics", [])),
                "jurisdictions": ",".join(item.get("jurisdiction_names", [])),
                "source_published_at": "2099-01-01",
                "publication_date_evidence": {"url": url, "source_quote": "2099-01-01"},
                "editorial_review": {"reviewed_by": "offline acceptance",
                    "event_key": f"acceptance-{item['n']}",
                    "cross_border_relevance": "Офлайн-проверка проводки источников, доставки и дедупликации международных налоговых материалов."},
                "act": item.get("act") or item.get("ecli") or "",
                "sources": [{"label": item["source"], "url": url}],
                "source_verifications": [{
                    "url": url,
                    "checked_at": "2026-01-01T08:00:00+00:00",
                    "status_code": 200,
                    "final_url": url,
                    "evidence": [{
                        "claim": title,
                        "source_quote": "Fixture source evidence for acceptance test",
                    }],
                }],
                "image_spec": {"badge": item["source"][:24]},
                "channels": ["telegram_channel", "vk", "linkedin", "email"],
                "item_type": item.get("item_type", ""), "court": court,
                "lead": bool(item.get("lead")),
                "primary_source_verified": True,
                "approval": {"status": "approved", "by": "offline acceptance",
                             "evidence": f"fixture-{item['n']}"},
            })
        # Geography in this engine fixture is explicit; collection scoring is
        # tested separately and does not impose the editorial release quotas.
        for n, item in enumerate(release_items):
            item['jurisdictions'] = 'Россия' if n < 2 else 'Казахстан' if n < 4 else 'Нидерланды'
        release = {"date": "2099-01-01", "release": "2099-01-01_0900_editorial", "items": release_items}
        publish_batch.validate_release(release, execution=True)
        assets = publish_batch.prepare_assets(self.root, release)
        self.assertEqual(len(assets), 10)

        session = self.tmp / "session.session"
        session.write_bytes(b"fixture")
        session.chmod(0o600)
        fake = FakeClient()
        with mock.patch.object(publish_batch, "ensure_session_idle", return_value=None), \
             mock.patch.object(publish_batch, "ensure_editorial_delivery_window", return_value=None), \
             mock.patch.dict(os.environ, {"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "hash"}):
            sent = asyncio.run(publish_batch.execute_editorial(
                self.root, release, assets, session_path=session,
                env_path=self.tmp / "missing.env", client_factory=lambda *_: fake,
            ))
        self.assertEqual(len(sent), 10)
        self.assertEqual(len(publish_batch.load_deliveries(self.root, "2099-01-01")), 10)
        self.assertEqual(len([
            line for line in (self.tmp / "ОПУБЛИКОВАННЫЕ_НОВОСТИ.md").read_text(encoding="utf-8").splitlines()
            if line.startswith("| 2099-")
        ]), 10)

        # Повторный отбор исключает доставленные темы и сохраняет два
        # неопубликованных кандидата для следующего выпуска.
        second = select_news.run("2099-01-01", 10, str(self.root))
        remaining = json.loads(Path(second["out_path"]).read_text(encoding="utf-8"))["items"]
        self.assertEqual(len(remaining), 2)
        self.assertFalse({i['url'] for i in remaining}.intersection(
            s['url'] for item in release_items for s in item['sources']))
        sent_again = asyncio.run(publish_batch.execute_editorial(
            self.root, release, assets, session_path=self.tmp / "missing.session",
            env_path=self.tmp / "missing.env", client_factory=lambda *_: None,
        ))
        self.assertEqual(sent_again, [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
