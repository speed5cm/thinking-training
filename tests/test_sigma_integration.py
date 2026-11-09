"""Exercise the repository commands together in an isolated project copy."""
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
sys.path.insert(0, str(Path(__file__).resolve().parent))

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
            from concept_authorization_fixture import write_authorization
            write_authorization(root)
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
            def publish():
                pending = call('sigma_plan_store.py', 'prepare', *learner, '--plan', str(candidate))
                return call('sigma_plan_store.py', 'publish', *learner, '--plan', str(candidate), '--confirmed-sha', pending['plan_sha256'])
            published = publish()
            self.assertEqual(published['status'], 'current')
            self.assertTrue(published['review_queue'][0]['due'])
            # Routine coach events do not change formal evidence or the plan.
            (folder / 'events.jsonl').write_text(json.dumps({'type':'parent_feedback','text':'普通记录'}, ensure_ascii=False) + '\n')
            self.assertEqual(call('sigma_plan_store.py', 'status', *learner)['status'], 'current')
            events = [[{'type':'question','concept':'C01','question_id':'q1','text':'问题'}],
                      [{'type':'answer','question_id':'q1','text':'回答'}, {'type':'analysis','question_id':'q1','analysis':{'reason':'分析'}}],
                      [{'type':'question','concept':'C01','question_id':'q2','text':'追问'}]]
            for revision, batch in enumerate(events, 1):
                snapshot['turns'].extend(batch)
                call('sigma_session_store.py', 'commit', *learner, '--expected-revision', str(revision), data=snapshot)
            snapshot['state']['status'] = 'paused'
            call('sigma_session_store.py', 'commit', *learner, '--expected-revision', '4', data=snapshot)
            resumed = call('sigma_session_store.py', 'read', *learner)
            self.assertEqual(resumed['turns'][-1], events[-1][0])
            self.assertEqual(call('sigma_plan_store.py', 'status', *learner)['status'], 'current')
            snapshot['state']['planning_basis'] = {'C01':'需要复习'}
            call('sigma_session_store.py', 'commit', *learner, '--expected-revision', '5', data=snapshot)
            self.assertEqual(call('sigma_plan_store.py', 'status', *learner)['status'], 'stale')
            ctx = call('validate_personal_roadmap.py', 'context', *learner)
            for key in ('curriculum_digest','evidence_digest','learner_digest'): plan[key] = ctx[key]
            candidate.write_text(json.dumps(plan, ensure_ascii=False))
            publish()
            scheduled = call('sigma_plan_store.py', 'schedule-dynamic', *learner, data={
                'concept':'C01', 'question_id':'q1', 'reason':'需要复习', 'interval_days':1})
            task = scheduled['dynamic_reviews'][0]
            history = folder / 'sigma/plan-history.json'
            saved = json.loads(history.read_text())
            saved['dynamic_reviews'][0]['due_at'] = '2020-01-01T00:00:00+00:00'
            history.write_text(json.dumps(saved, ensure_ascii=False))
            snapshot['turns'].extend([
                {'type':'answer','question_id':'q2','text':'回答'},
                {'type':'analysis','question_id':'q2','analysis':{'reason':'分析'}},
                {'type':'question','concept':'C01','question_id':'q3','text':'复习题','review_task_id':task['task_id']},
                {'type':'answer','question_id':'q3','text':'复习回答'},
                {'type':'analysis','question_id':'q3','analysis':{'reason':'复习分析'}}])
            call('sigma_session_store.py', 'commit', *learner, '--expected-revision', '6', data=snapshot)
            before = history.read_bytes()
            call('concept_authorization.py', 'revoke')
            denied = subprocess.run([sys.executable, str(root / 'scripts/sigma_plan_store.py'), 'complete-dynamic', *learner],
                                    input=json.dumps({'task_id':task['task_id'],'question_id':'q3','result':'correct','next_interval_days':2}),
                                    capture_output=True, text=True, cwd=root, timeout=15)
            self.assertNotEqual(denied.returncode, 0)
            self.assertEqual(history.read_bytes(), before)
            write_authorization(root)
            with (root / 'wiki/concepts/observation-vs-inference.md').open('a') as page: page.write('\n<!-- test -->\n')
            self.assertEqual(call('sigma_plan_store.py', 'status', *learner)['status'], 'stale')
            for action, payload in (
                ('schedule-dynamic', {'concept':'C01','question_id':'q1','reason':'复习','interval_days':1}),
                ('complete-dynamic', {'task_id':task['task_id'],'question_id':'q3','result':'correct','next_interval_days':2}),
            ):
                result = subprocess.run([sys.executable, str(root / 'scripts/sigma_plan_store.py'), action, *learner],
                                        input=json.dumps(payload, ensure_ascii=False), capture_output=True, text=True, cwd=root, timeout=15)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn('路线已过期', result.stderr)
                self.assertEqual(history.read_bytes(), before)
            self.assertEqual(call('sigma_session_store.py', 'read', *learner)['turns'], snapshot['turns'])
            # A harmless Wiki change can be incorporated into a validated new plan.
            ctx = call('validate_personal_roadmap.py', 'context', *learner)
            for key in ('curriculum_digest','evidence_digest','learner_digest'): plan[key] = ctx[key]
            candidate.write_text(json.dumps(plan, ensure_ascii=False))
            write_authorization(root, version='synthetic-2')  # Simulated review of changed content.
            republished = publish()
            self.assertEqual((republished['status'], republished['version']), ('current', 3))
            completed = call('sigma_plan_store.py', 'complete-dynamic', *learner, data={
                'task_id':task['task_id'],'question_id':'q3','result':'correct','next_interval_days':2})
            self.assertEqual([t['status'] for t in completed['dynamic_reviews']], ['completed','pending'])
