"""Exercise the actual command boundary in an isolated project copy."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from concept_authorization_fixture import write_authorization, question_event, event
from test_dynamic_candidate import publish_initial_plan

ROOT = Path(__file__).resolve().parents[1]

class ConceptAuthorization(unittest.TestCase):
    def test_authorization_lifecycle_and_bypasses(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / 'project'
            shutil.copytree(ROOT, root, ignore=shutil.ignore_patterns('.git', 'records', '__pycache__', 'experiments'))
            (root / 'pilot-c01-c02/records/synthetic').mkdir(parents=True)
            def run(script, *args, data=None):
                return subprocess.run([sys.executable, str(root / 'scripts' / script), *args],
                    input=json.dumps(data, ensure_ascii=False) if data is not None else None,
                    capture_output=True, text=True, cwd=root, timeout=15)
            learner = ('--learner','synthetic')
            start = {'state':{}, 'session':'', 'turns':[{'type':'session_start'}]}
            def run_commit(data, revision):
                return run('sigma_session_store.py', 'commit', *learner, '--expected-revision', str(revision), data=data)
            started = json.loads(run_commit(start, 0).stdout)
            path = write_authorization(root)
            publish_initial_plan(root, root / 'pilot-c01-c02/records/synthetic')
            self.assertEqual(run('concept_authorization.py', 'check', '--learner', 'synthetic').returncode, 0)
            self.assertNotEqual(run('concept_authorization.py', 'check', '--learner', 'child').returncode, 0)
            original = json.loads(path.read_text())
            question = {k:started[k] for k in ('state','session','turns')}
            candidate = {**question, 'turns':question['turns'] + [question_event(root, 'q1', session_id=question['session'])]}
            for change in ({'review': {'kind':'human', 'actor':'someone', 'basis':'claim'}},
                           {'review': {'kind':'ai', 'actor':'agent', 'basis':'claim'}},
                           {'sources': []}, {'scope': ''}, {'status':'revoked'}, {'content_sha256': {}}):
                path.write_text(json.dumps({**original, **change}, ensure_ascii=False))
                self.assertNotEqual(run_commit(candidate, 1).returncode, 0, change)
            path.write_text(json.dumps(original, ensure_ascii=False))
            source = root / 'references/pedagogy.md'
            source.write_text(source.read_text() + '\nchanged\n')
            self.assertNotEqual(run_commit(candidate, 1).returncode, 0)
            write_authorization(root, version='synthetic-2')
            # The Wiki input changed, so the route must also be republished.
            publish_initial_plan(root, root / 'pilot-c01-c02/records/synthetic')
            bad = {**question, 'turns':question['turns'] + [{'question':'bypass'}]}
            self.assertNotEqual(run_commit(bad, 1).returncode, 0)
            for concept in (None, 'C02'):
                q = question_event(root, 'x', session_id=question['session'], concept=concept)
                bypass = {**question, 'turns':question['turns'] + [q]}
                self.assertNotEqual(run_commit(bypass, 1).returncode, 0)
            question['turns'].append(question_event(root, 'q1', text='测试', session_id=question['session']))
            stored = run_commit(question, 1)
            self.assertEqual(stored.returncode, 0, stored.stderr)
            question = {k:json.loads(stored.stdout)[k] for k in ('state','session','turns')}
            self.assertEqual(run('concept_authorization.py', 'revoke').returncode, 0)
            question['turns'].extend([event('answer','q1',text='回答',session_id=question['session']), event('analysis','q1',analysis={'reason':'评价'},session_id=question['session'])])
            self.assertNotEqual(run('sigma_session_store.py', 'commit', '--learner','synthetic','--expected-revision','2',data=question).returncode, 0)
            saved = run('sigma_session_store.py','read','--learner','synthetic')
            self.assertEqual(len(json.loads(saved.stdout)['turns']), 2)

if __name__ == '__main__': unittest.main()
