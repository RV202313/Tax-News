"""Failed verification cannot leave a deliverable approved package."""
import io
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import prepare_editorial_handoff as handoff


class HandoffTests(unittest.TestCase):
    def test_concurrent_handoff_commit_cannot_replace_existing_slot(self):
        with tempfile.TemporaryDirectory() as folder:
            target=Path(folder)/'approved.json'
            handoff.commit_handoff(target, {'writer': 'first'})
            with self.assertRaises(FileExistsError):
                handoff.commit_handoff(target, {'writer': 'second'})
            self.assertEqual(json.loads(target.read_text())['writer'], 'first')
            self.assertEqual(list(Path(folder).glob('*.tmp')), [])

    def test_failed_source_checkpoint_never_commits(self):
        self.run_handoff(source_count=9)

    def test_failed_final_live_check_withdraws_only_own_commit(self):
        self.run_handoff(source_count=10, final_failure=True)

    def run_handoff(self, source_count, final_failure=False):
        with tempfile.TemporaryDirectory() as folder:
            workspace = Path(folder)
            root = workspace / 'News Claude'
            root.mkdir()
            authored = workspace / 'authored.json'
            authored.write_text(json.dumps({'candidates': [{}]*10}))
            release = '2099-01-01_0900_editorial'
            argv = ['prepare', str(authored), '--root', str(root), '--release', release,
                    '--deadline', '2099-01-01T08:50:00+03:00']
            items = [{'title': str(n), 'slug': str(n)} for n in range(10)]
            runs = [None, subprocess.CalledProcessError(1, ['publish'])] if final_failure else []
            with patch.object(sys, 'argv', argv), patch.object(sys, 'stdout', io.StringIO()), \
                 patch.object(sys, 'stderr', io.StringIO()), \
                 patch.object(handoff, 'materialize', return_value=items), \
                 patch.object(handoff, 'check_history'), \
                 patch.object(handoff, 'checkpoint_candidates', return_value={'source_gate_candidate_count': source_count}), \
                 patch.object(handoff, 'validate_release'), \
                 patch.object(handoff, 'prepare_assets', return_value={str(n): root/'card.jpg' for n in range(10)}), \
                 patch.object(handoff.subprocess, 'run', side_effect=runs) as runner:
                self.assertEqual(handoff.main(), 1)
            target = root / 'pipeline' / 'approved' / (release+'.json')
            self.assertFalse(target.exists())
            status = json.loads((workspace/'runtime-logs/editorial-preparation-status.json').read_text())
            self.assertEqual(status['result'], 'failed')
            self.assertFalse(status['delivery_performed'])
            if final_failure:
                self.assertEqual(runner.call_count, 2)
                self.assertTrue((workspace/'runtime-logs'/f'{release}-failed-final-check.json').exists())
            else:
                runner.assert_not_called()


if __name__ == '__main__': unittest.main()
