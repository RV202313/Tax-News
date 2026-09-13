#!/usr/bin/env python3
"""Регрессии Фазы 3 без внешних отправок."""

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
PORTAL = PROJECT / "portal"
sys.path.insert(0, str(SCRIPTS))
sys.path.insert(0, str(PORTAL))

import cards  # noqa: E402
import publish_batch  # noqa: E402
import publishers  # noqa: E402
import postiz_discover  # noqa: E402


CATALOG_HEADER = """# Каталог

| Дата | ID канала | ID чата | Статус | Заголовок | Нормализованная тема | Юрисдикции | Акт | Источники |
|---|---:|---:|---|---|---|---|---|---|
"""


class TempProject(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="news_phase3_"))
        self.root = self.tmp / "News Claude"
        self.root.mkdir()
        (self.tmp / "ОПУБЛИКОВАННЫЕ_НОВОСТИ.md").write_text(
            CATALOG_HEADER, encoding="utf-8"
        )
        self.image = self.root / "shared.jpg"
        cards.build_card(
            {"title": "Тестовая налоговая новость", "image_spec": {"badge": "TEST"}},
            self.image, "2026-07-18",
        )

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)

    def release(self, approved=True):
        items = []
        for number in range(1, 11):
            url = f"https://example.test/primary/{number}"
            item = {
                "slug": f"2026-07-18-test-{number}",
                "title": f"Налоговая новость {number}",
                "caption": (
                    f"Налоговая новость {number}.\n\nИсточник: {url}\n\n"
                    "#тест #АкадемияBEPS #АкадемияБЕПС"
                ),
                "theme": f"Тема {number}",
                "jurisdictions": "Россия",
                "act": f"Акт {number}",
                "sources": [{"label": "Official", "url": url}],
                "image_path": str(self.image),
                "image_credit": "Academy BEPS",
                "image_rights": "original artwork",
                "channels": ["telegram_channel"],
            }
            if approved:
                item["approval"] = {
                    "status": "approved", "by": "Роустам",
                    "evidence": f"test approval {number}",
                }
            items.append(item)
        return {"date": "2026-07-18", "release": "test-0900", "items": items}


class ValidationTests(TempProject):
    def test_dry_run_allows_unapproved_but_execute_does_not(self):
        release = self.release(approved=False)
        publish_batch.validate_release(release, execution=False)
        with self.assertRaisesRegex(ValueError, "нет индивидуального approval"):
            publish_batch.validate_release(release, execution=True)

    def test_count_and_primary_source_are_mandatory(self):
        release = self.release()
        release["items"] = release["items"][:9]
        with self.assertRaisesRegex(ValueError, "ровно 10"):
            publish_batch.validate_release(release, execution=False)
        release = self.release()
        release["items"][0]["caption"] = "#АкадемияBEPS #АкадемияБЕПС"
        with self.assertRaisesRegex(ValueError, "прямой ссылки"):
            publish_batch.validate_release(release, execution=False)

    def test_anglo_russian_mixture_is_rejected(self):
        release = self.release()
        url = release["items"][0]["sources"][0]["url"]
        release["items"][0]["caption"] = (
            "HMRC сообщила, что convention entered into force. "
            "Detached worker provision действует пять лет при наличии valid "
            "certificate of coverage. Почему это важно: меняется cost model "
            f"secondments.\n\nИсточник: {url}\n\n"
            "#АкадемияBEPS #АкадемияБЕПС"
        )
        with self.assertRaisesRegex(ValueError, "непереведённые английские слова"):
            publish_batch.validate_release(release, execution=False)

    def test_official_abbreviations_and_terms_are_allowed(self):
        release = self.release()
        url = release["items"][0]["sources"][0]["url"]
        release["items"][0]["caption"] = (
            "HMRC разъяснила применение правил BEPS и OECD, включая "
            "Pillar 2 и GloBE. Почему это важно: компаниям нужно проверить "
            f"расчёты.\n\nИсточник: {url}\n\n"
            "#АкадемияBEPS #АкадемияБЕПС"
        )
        publish_batch.validate_release(release, execution=False)

    def test_catalog_upsert_matches_source_url(self):
        catalog = self.tmp / "ОПУБЛИКОВАННЫЕ_НОВОСТИ.md"
        item = self.release()["items"][0]
        publish_batch.upsert_catalog(catalog, "2026-07-18", item, "100")
        publish_batch.upsert_catalog(catalog, "2026-07-18", item, "101")
        rows = [line for line in catalog.read_text(encoding="utf-8").splitlines() if line.startswith("| 2026-")]
        self.assertEqual(len(rows), 1)
        self.assertIn("| 101 |", rows[0])

    def test_run_record_uses_real_paths_hashes_and_is_immutable(self):
        approved_path = self.root / "pipeline/approved/2026-07-18_test.json"
        approved_path.parent.mkdir(parents=True)
        release = self.release()
        approved_path.write_text(json.dumps(release, ensure_ascii=False), encoding="utf-8")
        shortlist = self.root / "pipeline/shortlist/2026-07-18_shortlist.json"
        shortlist.parent.mkdir(parents=True)
        shortlist.write_text(json.dumps({"date": "2026-07-18", "items": []}), encoding="utf-8")
        digest = self.root / "pipeline/digest/2026-07-18_digest.md"
        digest.parent.mkdir(parents=True)
        digest.write_text("digest", encoding="utf-8")
        for item in release["items"]:
            publish_batch.append_delivery(self.root, {
                "date": release["date"], "release": release["release"],
                "slug": item["slug"], "delivery": "telegram_editorial",
                "post_id": str(700 + len(publish_batch.load_deliveries(self.root, release["date"]))),
            })
        run_id = publish_batch.release_run_id(release, approved_path, "editorial")
        release["run_id"] = run_id
        first = publish_batch.write_run_record(
            self.root, release, approved_path, scope="editorial"
        )
        first_bytes = first.read_bytes()
        second = publish_batch.write_run_record(
            self.root, release, approved_path, scope="editorial"
        )
        payload = json.loads(first.read_text(encoding="utf-8"))
        self.assertEqual(first, second)
        self.assertEqual(first.read_bytes(), first_bytes)
        self.assertEqual(payload["run_id"], run_id)
        self.assertEqual(payload["schema_version"], 3)
        self.assertEqual(payload["release_source_of_truth"], "approved.json")
        self.assertFalse(payload["daily_build_context_authoritative"])
        self.assertEqual(payload["artifacts"]["shortlist"]["state"], "copied")
        self.assertEqual(payload["artifacts"]["shortlist"]["role"], "context_only")
        self.assertEqual(payload["artifacts"]["shortlist"]["release_lineage"], "not_asserted")
        self.assertEqual(len(payload["artifacts"]["approved"]["sha256"]), 64)
        self.assertEqual(payload["artifacts"]["published_sidecar"]["records"], 10)
        publish_batch.verify_run_record(first)
        (first.parent / "2026-07-18_digest.md").write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "SHA-256"):
            publish_batch.verify_run_record(first)

    def test_run_record_rejects_approved_drift_after_execute_started(self):
        approved_path = self.root / "pipeline/approved/release.json"
        approved_path.parent.mkdir(parents=True)
        release = self.release()
        approved_path.write_text(json.dumps(release), encoding="utf-8")
        original_sha = publish_batch._sha256(approved_path)
        approved_path.write_text(json.dumps({**release, "release": "changed"}), encoding="utf-8")
        with self.assertRaisesRegex(RuntimeError, "изменился"):
            publish_batch.write_run_record(
                self.root, release, approved_path, scope="editorial",
                expected_approved_sha256=original_sha,
            )


class FakeClient:
    def __init__(self, username="academy_of_beps"):
        self.username = username
        self.calls = []
        self.next_id = 500

    async def connect(self):
        self.calls.append("connect")

    async def get_me(self):
        self.calls.append("get_me")
        return SimpleNamespace(username=self.username)

    async def send_file(self, chat_id, image, **kwargs):
        self.calls.append(("send_file", chat_id, image, kwargs))
        self.next_id += 1
        return SimpleNamespace(id=self.next_id)

    async def disconnect(self):
        self.calls.append("disconnect")


class EditorialDeliveryTests(TempProject):
    def test_sidecar_prevents_resend_and_catalog_is_repairable(self):
        release = self.release()
        assets = publish_batch.prepare_assets(self.root, release)
        session = self.tmp / "session.session"
        session.write_bytes(b"fixture")
        session.chmod(0o600)
        fake = FakeClient()
        with mock.patch.object(publish_batch, "ensure_session_idle", return_value=None), \
             mock.patch.dict(os.environ, {"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "hash"}):
            sent = asyncio.run(publish_batch.execute_editorial(
                self.root, release, assets, session_path=session,
                env_path=self.tmp / "missing.env", client_factory=lambda *_: fake,
            ))
        self.assertEqual(len(sent), 10)
        self.assertEqual(fake.calls[1], "get_me")
        sends = [index for index, call in enumerate(fake.calls) if isinstance(call, tuple)]
        self.assertTrue(all(fake.calls[index - 1] == "get_me" for index in sends))
        self.assertEqual(fake.calls.count("get_me"), 11)
        self.assertEqual(len([call for call in fake.calls if isinstance(call, tuple)]), 10)
        records = publish_batch.load_deliveries(self.root, "2026-07-18")
        self.assertEqual(len(records), 10)

        # Удаление строки каталога имитирует crash после сайдкара.
        catalog = self.tmp / "ОПУБЛИКОВАННЫЕ_НОВОСТИ.md"
        catalog.write_text(CATALOG_HEADER, encoding="utf-8")
        sent_again = asyncio.run(publish_batch.execute_editorial(
            self.root, release, assets, session_path=self.tmp / "does-not-exist",
            env_path=self.tmp / "missing.env", client_factory=lambda *_: None,
        ))
        self.assertEqual(sent_again, [])
        rows = [line for line in catalog.read_text(encoding="utf-8").splitlines() if line.startswith("| 2026-")]
        self.assertEqual(len(rows), 10)

    def test_wrong_account_disconnects_before_send(self):
        release = self.release()
        assets = publish_batch.prepare_assets(self.root, release)
        session = self.tmp / "session.session"
        session.write_bytes(b"fixture")
        session.chmod(0o600)
        fake = FakeClient(username="wrong_account")
        with mock.patch.object(publish_batch, "ensure_session_idle", return_value=None), \
             mock.patch.dict(os.environ, {"TELEGRAM_API_ID": "123", "TELEGRAM_API_HASH": "hash"}):
            with self.assertRaisesRegex(RuntimeError, "Неверный Telegram-аккаунт"):
                asyncio.run(publish_batch.execute_editorial(
                    self.root, release, assets, session_path=session,
                    env_path=self.tmp / "missing.env", client_factory=lambda *_: fake,
                ))
        self.assertEqual(fake.calls, ["connect", "get_me", "disconnect"])


class PostizTests(TempProject):
    def test_discovery_writes_only_unambiguous_non_tg_ids(self):
        config = self.root / "config"
        config.mkdir()
        (config / "postiz.yaml").write_text(
            "connection:\n  base_url: http://localhost:4007\n"
            "channel_map:\n  telegram_channel:\n    enabled: false\n"
            "  vk:\n    postiz_integration_id: ''\n"
            "  linkedin:\n    postiz_integration_id: ''\n",
            encoding="utf-8",
        )

        class Response:
            ok = True
            status_code = 200
            text = ""

            def json(self):
                return [
                    {"id": "tg-1", "identifier": "telegram", "name": "TG", "disabled": False},
                    {"id": "vk-1", "identifier": "vk", "name": "VK", "disabled": False},
                    {"id": "li-1", "identifier": "linkedin", "name": "LI", "disabled": False},
                ]

        session = mock.Mock()
        session.get.return_value = Response()
        with mock.patch.dict(os.environ, {"POSTIZ_API_KEY": "test-key"}):
            result = postiz_discover.discover(self.root, write=True, session=session)
        self.assertEqual(result["written"], ["vk", "linkedin"])
        saved = (config / "postiz.yaml").read_text(encoding="utf-8")
        self.assertIn("postiz_integration_id: vk-1", saved)
        self.assertIn("postiz_integration_id: li-1", saved)
        self.assertNotIn("postiz_integration_id: tg-1", saved)

    def test_upload_is_attached_to_post_payload(self):
        config = self.root / "config"
        config.mkdir()
        (config / "postiz.yaml").write_text(
            "connection:\n  base_url: http://localhost:4007\n"
            "channel_map:\n  vk:\n    enabled: true\n    postiz_integration_id: vk-1\n",
            encoding="utf-8",
        )

        class Response:
            ok = True
            status_code = 200
            text = ""

            def __init__(self, payload):
                self.payload = payload

            def json(self):
                return self.payload

        calls = []

        def fake_post(url, **kwargs):
            calls.append((url, kwargs))
            if url.endswith("/upload"):
                return Response({"id": "media-1", "path": "https://postiz.test/media.jpg"})
            return Response([{"postId": "post-1"}])

        with mock.patch.dict(os.environ, {"POSTIZ_API_KEY": "test-key"}), \
             mock.patch.object(publishers.requests, "post", side_effect=fake_post):
            result = publishers.publish_postiz(
                self.root, "vk", "content", media_paths=[self.image]
            )
        self.assertEqual(result["post_id"], "post-1")
        image_payload = calls[1][1]["json"]["posts"][0]["value"][0]["image"]
        self.assertEqual(image_payload, [{"id": "media-1", "path": "https://postiz.test/media.jpg"}])


if __name__ == "__main__":
    unittest.main(verbosity=2)
