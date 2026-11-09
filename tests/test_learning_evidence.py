"""Historical evidence remains readable; retired C01/C02 APIs cannot execute."""
import importlib.util
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('learning_evidence_test', ROOT / 'scripts/learning_evidence.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.folder = Path(self.tmp.name)

    def test_missing_archive_is_empty(self):
        self.assertEqual(mod.load_evidence(self.folder), [])

    def test_archived_records_remain_unchanged(self):
        path = self.folder / 'evidence.jsonl'
        content = '{"concept":"C01","raw_response":"合成原话"}\n'
        path.write_text(content, encoding='utf-8')
        self.assertEqual(mod.load_evidence(self.folder)[0]['raw_response'], '合成原话')
        self.assertEqual(path.read_text(encoding='utf-8'), content)

    def test_corrupt_archive_is_rejected(self):
        (self.folder / 'evidence.jsonl').write_text('{invalid\n')
        with self.assertRaises(mod.EvidenceError): mod.load_evidence(self.folder)

    def test_non_object_archive_is_rejected(self):
        (self.folder / 'evidence.jsonl').write_text('[]\n')
        with self.assertRaises(mod.EvidenceError): mod.load_evidence(self.folder)

    def assert_retired(self, action):
        result = subprocess.run([sys.executable, str(ROOT / 'scripts/learning_evidence.py'), action,
                                 '--learner', 'synthetic'], capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('invalid choice', result.stderr)

    def test_capture_is_retired(self): self.assert_retired('capture')
    def test_assess_is_retired(self): self.assert_retired('assess')
    def test_confirm_c01_is_retired(self): self.assert_retired('confirm-c01')
    def test_recommend_is_retired(self): self.assert_retired('recommend')

if __name__ == '__main__': unittest.main()
