"""End-to-end C02 gates with synthetic cards, evidence and parent confirmation."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class C02Integration(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        for name in ('scripts', 'wiki', 'references', 'question-bank'):
            shutil.copytree(ROOT / name, self.root / name, ignore=shutil.ignore_patterns('__pycache__'))
        pilot = self.root / 'pilot-c01-c02'
        for name in ('scripts', 'cards', 'reviews', 'wiki'):
            shutil.copytree(ROOT / 'pilot-c01-c02' / name, pilot / name, ignore=shutil.ignore_patterns('__pycache__'))
        self.pilot = pilot
        self.script = pilot / 'scripts/coach.py'
        src = self.script.read_text().replace("'C01': ['ST-C01-01']", "'C01': ['ST-C01-01', 'SYN-C01-02']")
        self.script.write_text(src)
        cards = pilot / 'cards'
        card = json.loads((cards / 'ST-C01-01.json').read_text())
        card['id'] = 'SYN-C01-02'
        path = cards / 'SYN-C01-02.json'
        path.write_text(json.dumps(card, ensure_ascii=False, indent=2) + '\n')
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        registry_path = cards / 'versions.json'
        registry = json.loads(registry_path.read_text())
        registry[card['id']] = {card['version']: sha}
        registry_path.write_text(json.dumps(registry))
        archive = cards / 'archive' / card['id']
        archive.mkdir()
        shutil.copy(path, archive / (card['version'] + '.json'))
        review = json.loads((pilot / 'reviews/ST-C01-01@1.1.0.json').read_text())
        review.update(card_id=card['id'], content_sha256=sha)
        for t in review['transitions']:
            t['actor'] = 'SYNTHETIC_TEST_ONLY'
        (pilot / 'reviews/SYN-C01-02@1.1.0.json').write_text(json.dumps(review))
        self.folder = pilot / 'records/synthetic'
        self.folder.mkdir(parents=True)
        def record(sid, qid, digest):
            return {'concept':'C01', 'session_id':sid, 'card':{'id':qid, 'version':'1.1.0', 'sha256':digest}, 'ai_temporary_correctness':'correct', 'explanation_quality':'valid', 'raw_response':'因为有证据', 'reason_quote':'因为有证据', 'hint_level':0, 'prior_attempts':0, 'prior_support':[], 'transfer':{'status':'yes','parent_verified_novel':True,'observation':'SYNTHETIC ONLY'}}
        sha1 = hashlib.sha256((cards / 'ST-C01-01.json').read_bytes()).hexdigest()
        self.records = [record('synthetic-1', 'ST-C01-01', sha1), record('synthetic-2', card['id'], sha)]
        self.save_records()

    def save_records(self):
        (self.folder / 'evidence.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False)+'\n' for r in self.records))

    def evidence(self, action, *args, input=None):
        return subprocess.run([sys.executable, str(self.root / 'scripts/learning_evidence.py'), action, '--learner', 'synthetic', *args], input=input, text=True, capture_output=True)

    def coach(self, action, *args):
        return subprocess.run([sys.executable, str(self.script), action, '--learner', 'synthetic', *args], text=True, capture_output=True)

    def test_legacy_cards_and_confirmation_cannot_authorize_c02(self):
        # Historical card evidence and parent-shaped confirmation cannot authorize the new rule.
        self.assertNotEqual(self.evidence('confirm-c01', '--synthetic-confirmation').returncode, 0)
        (self.folder / 'mastery-confirmation.json').write_text(json.dumps({'concept':'C01','confirmation':'parent','evidence_digest':'legacy'}))
        self.assertNotEqual(self.coach('start', '--mode', 'C02').returncode, 0)
        self.assertNotEqual(self.coach('show').returncode, 0)

    def test_revoked_c02_and_concurrent_legacy_starts_are_denied(self):
        (self.pilot / 'reviews/ST-C02-01@1.1.0.json').unlink()
        command = [sys.executable, str(self.script), 'start', '--learner', 'synthetic', '--mode', 'C02']
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        output = [p.communicate(timeout=15) for p in processes]
        self.assertEqual([p.returncode for p in processes], [1, 1], output)

    def test_old_card_records_remain_archived_and_never_satisfy_dynamic_rule(self):
        result = self.evidence('assess')
        self.assertEqual(result.returncode, 0, result.stderr)
        assessment = json.loads(result.stdout)
        self.assertEqual(assessment['historical_evidence_pending_review'], 2)
        self.assertEqual(assessment['assessments'][0]['mastery'], 'pending_confirmation')
        self.assertNotEqual(self.coach('start', '--mode', 'C02').returncode, 0)
        self.assertTrue((self.folder / 'evidence.jsonl').is_file())

if __name__ == '__main__':
    unittest.main()
