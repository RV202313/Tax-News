import copy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from unittest import mock
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_editorial_sources as sources


QUOTE = "An official agreement has been signed today."
CLAIM = "Налоговое соглашение подписано сегодня."


class Handler(BaseHTTPRequestHandler):
    def do_GET(self):
        if self.path == "/redirect":
            self.send_response(302)
            self.send_header("Location", "/ok")
            self.end_headers()
            return
        if self.path == "/missing":
            self.send_error(404)
            return
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        body = (f'<script>{QUOTE}</script><p>Empty page</p>' if self.path == "/script"
                else f"<p>{QUOTE}</p>")
        self.wfile.write(body.encode("utf-8"))

    def log_message(self, *args):
        pass


class SourceChecks(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.thread = threading.Thread(target=cls.server.serve_forever, daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()
        cls.thread.join()

    def candidate(self, path="/ok"):
        url = self.base + path
        return {"title": "Соглашение", "caption": CLAIM + "\nИсточник: " + url,
                "sources": [{"url": url}],
                "source_verifications": [{"url": url, "evidence": [
                    {"claim": CLAIM, "source_quote": QUOTE}]}]}

    def test_200_exact_url_visible_quote_and_russian_caption(self):
        check = sources.check_candidate(self.candidate())
        self.assertTrue(check["passed"])
        self.assertEqual(check["checks"][0]["status_code"], 200)
        self.assertEqual(check["checks"][0]["final_url"], self.base + "/ok")

    def test_redirect_404_and_script_only_quote_fail(self):
        for path in ("/redirect", "/missing", "/script"):
            with self.subTest(path=path):
                self.assertFalse(sources.check_candidate(self.candidate(path))["passed"])

    def test_claim_and_url_must_be_in_caption(self):
        for caption in (CLAIM, self.base + "/ok"):
            candidate = self.candidate()
            candidate["caption"] = caption
            check = sources.check_candidate(candidate)
            self.assertFalse(check["passed"])
            self.assertFalse(check["checks"][0]["performed"])

    def test_expired_deadline_never_opens_url(self):
        def forbidden(*args, **kwargs):
            self.fail("request after deadline")
        check = sources.check_candidate(self.candidate(), opener=forbidden,
                                        deadline=datetime.now(timezone.utc) - timedelta(seconds=1))
        self.assertFalse(check["passed"])
        self.assertFalse(check["checks"][0]["performed"])

    def test_each_completed_source_is_saved_before_output_and_other_checks(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "evidence.json"
            completed = []
            def report(message):
                saved = json.loads(target.read_text(encoding="utf-8"))
                completed.append(saved["current_run_completed_count"])
                raise UnicodeEncodeError("cp1252", "Россия", 0, 1, "cannot encode")
            result = sources.checkpoint_candidates(
                {"candidates": [self.candidate(), self.candidate("/missing")]},
                target, workers=1, report=report)
            self.assertEqual(completed, [1, 2])
            saved = json.loads(target.read_text(encoding="utf-8"))
            self.assertEqual(saved["source_gate_candidate_count"], 1)
            self.assertEqual(saved["current_run_completed_count"], 2)
            self.assertFalse(result["approved"])
            self.assertEqual(saved["candidates"][0]["source_verifications"][0]["status_code"], 200)

    def test_worker_exception_retains_other_source_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            def checker(item, **kwargs):
                if item["sources"][0]["url"].endswith("/missing"):
                    raise RuntimeError("bad source")
                return sources.check_candidate(item, **kwargs)
            result = sources.checkpoint_candidates(
                {"candidates": [self.candidate(), self.candidate("/missing")]},
                Path(tmp) / "evidence.json", checker=checker, report=lambda _: None)
            self.assertEqual(result["source_gate_candidate_count"], 1)
            self.assertIn("bad source", result["candidates"][1]["current_run_check"]["error"])

    def test_failed_retry_preserves_previous_verification(self):
        candidate = self.candidate("/missing")
        historical = copy.deepcopy(candidate["source_verifications"])
        candidate["current_run_check"] = {"passed": True, "checked_at": "historical"}
        with tempfile.TemporaryDirectory() as tmp:
            result = sources.checkpoint_candidates({"candidates": [candidate]},
                Path(tmp) / "evidence.json", report=lambda _: None)
        item = result["candidates"][0]
        self.assertFalse(item["source_gate_passed"])
        self.assertEqual(item["source_verifications"], historical)
        self.assertEqual(item["previous_run_check"]["checked_at"], "historical")

    def test_windows_temporary_rename_lock_retries_without_partial_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "evidence.json"
            original = sources.os.replace
            calls = []
            def replace(source, destination):
                calls.append(destination)
                if len(calls) < 3:
                    raise PermissionError("Windows indexer sharing violation")
                original(source, destination)
            with mock.patch.object(sources.os, "replace", side_effect=replace), \
                 mock.patch.object(sources.time, "sleep"):
                sources.atomic_json(target, {"proof": "сохранено"})
            self.assertEqual(len(calls), 3)
            self.assertEqual(json.loads(target.read_text(encoding="utf-8")), {"proof": "сохранено"})


if __name__ == "__main__":
    unittest.main()
