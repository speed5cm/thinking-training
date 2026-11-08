"""Exercise the repository commands together in an isolated project copy."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]

class SigmaIntegration(unittest.TestCase):
    def test_snapshot_plan_review_and_wiki_change(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'project'
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('.git', 'records', '__pycache__', 'experiments'))
            folder = root / 'pilot-c01-c02/records/synthetic'
            folder.mkdir(parents=True)
            def call(script, *args, data=None):
                result = subprocess.run([sys.executable, str(root / 'scripts' / script), *args], input=json.dumps(data, ensure_ascii=False) if data is not None else None, capture_output=True, text=True, cwd=root, timeout=15)
                self.assertEqual(result.returncode, 0, result.stderr)
                return json.loads(result.stdout)
            learner = ('--learner', 'synthetic')
            snapshot = {'state': {}, 'session': '', 'turns': []}
            call('sigma_session_store.py', 'commit', *learner, '--expected-revision', '0', data=snapshot)
            card_path = root / 'pilot-c01-c02/cards/ST-C01-01.json'
            card = json.loads(card_path.read_text())
            record = {'concept':'C01', 'session_id':'synthetic-evidence', 'captured_at':'2020-01-01T00:00:00+00:00', 'card':{'id':'ST-C01-01','version':card['version'],'sha256':hashlib.sha256(card_path.read_bytes()).hexdigest()}, 'ai_temporary_correctness':'correct','explanation_quality':'valid','reason_quote':'因为','raw_response':'因为','hint_level':0,'prior_attempts':0,'prior_support':[],'transfer':{'status':'unknown','parent_verified_novel':False,'observation':''}}
            (folder / 'evidence.jsonl').write_text(json.dumps(record, ensure_ascii=False) + '\n')
            ctx = call('validate_personal_roadmap.py', 'context', *learner)
            plan = json.loads((root / 'examples/ai-roadmap/fiction-plan.json').read_text())
            plan['learner'] = 'synthetic'
            for key in ('curriculum_digest','evidence_digest','learner_digest'): plan[key] = ctx[key]
            candidate = folder / 'candidate.json'
            candidate.write_text(json.dumps(plan, ensure_ascii=False))
            published = call('sigma_plan_store.py', 'publish', *learner, '--plan', str(candidate))
            self.assertEqual(published['status'], 'current')
            self.assertTrue(published['review_queue'][0]['due'])
            events = [{'type':'question','question_id':'q1','text':'问题'}, {'type':'answer','question_id':'q1','text':'回答'}, {'type':'question','question_id':'q2','text':'追问'}]
            for revision, event in enumerate(events, 1):
                snapshot['turns'].append(event)
                call('sigma_session_store.py', 'commit', *learner, '--expected-revision', str(revision), data=snapshot)
            snapshot['state']['status'] = 'paused'
            call('sigma_session_store.py', 'commit', *learner, '--expected-revision', '4', data=snapshot)
            resumed = call('sigma_session_store.py', 'read', *learner)
            self.assertEqual(resumed['turns'][-1], events[-1])
            self.assertEqual(call('sigma_plan_store.py', 'status', *learner)['status'], 'current')
            snapshot['state']['planning_basis'] = {'C01':'需要复习'}
            call('sigma_session_store.py', 'commit', *learner, '--expected-revision', '5', data=snapshot)
            self.assertEqual(call('sigma_plan_store.py', 'status', *learner)['status'], 'stale')
            ctx = call('validate_personal_roadmap.py', 'context', *learner)
            for key in ('curriculum_digest','evidence_digest','learner_digest'): plan[key] = ctx[key]
            candidate.write_text(json.dumps(plan, ensure_ascii=False))
            call('sigma_plan_store.py', 'publish', *learner, '--plan', str(candidate))
            with (root / 'wiki/concepts/observation-vs-inference.md').open('a') as page: page.write('\n<!-- test -->\n')
            self.assertEqual(call('sigma_plan_store.py', 'status', *learner)['status'], 'stale')
