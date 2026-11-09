"""Exercise the actual command boundary in an isolated project copy."""
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from concept_authorization_fixture import write_authorization

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
            args = ('commit', '--learner', 'synthetic', '--expected-revision', '0')
            question = {'state': {}, 'session': '', 'turns': [{'type':'question','concept':'C01','question_id':'q1','text':'测试'}]}
            def commit(): return run('sigma_session_store.py', *args, data=question)
            self.assertNotEqual(commit().returncode, 0)
            path = write_authorization(root)
            self.assertEqual(run('concept_authorization.py', 'check', '--learner', 'synthetic').returncode, 0)
            self.assertNotEqual(run('concept_authorization.py', 'check', '--learner', 'child').returncode, 0)
            original = json.loads(path.read_text())
            for change in ({'review': {'kind':'human', 'actor':'someone', 'basis':'claim'}},
                           {'review': {'kind':'ai', 'actor':'agent', 'basis':'claim'}},
                           {'sources': []}, {'scope': ''}, {'status':'revoked'}, {'content_sha256': {}}):
                path.write_text(json.dumps({**original, **change}, ensure_ascii=False))
                self.assertNotEqual(commit().returncode, 0, change)
            path.write_text(json.dumps(original, ensure_ascii=False))
            source = root / 'references/pedagogy.md'
            source.write_text(source.read_text() + '\nchanged\n')
            self.assertNotEqual(commit().returncode, 0)
            write_authorization(root, version='synthetic-2')
            bad = {'state': {}, 'session':'', 'turns':[{'question':'bypass'}]}
            self.assertNotEqual(run('sigma_session_store.py', *args, data=bad).returncode, 0)
            for concept in (None, 'C02'):
                bypass = {'state': {}, 'session':'', 'turns':[{'type':'question', 'concept':concept, 'question_id':'x', 'text':'测试'}]}
                self.assertNotEqual(run('sigma_session_store.py', *args, data=bypass).returncode, 0)
            self.assertEqual(commit().returncode, 0)
            self.assertEqual(run('concept_authorization.py', 'revoke').returncode, 0)
            question['turns'].extend([{'type':'answer','question_id':'q1','text':'回答'}, {'type':'analysis','question_id':'q1','analysis':{'reason':'评价'}}])
            self.assertNotEqual(run('sigma_session_store.py', 'commit', '--learner','synthetic','--expected-revision','1',data=question).returncode, 0)
            saved = run('sigma_session_store.py','read','--learner','synthetic')
            self.assertEqual(len(json.loads(saved.stdout)['turns']), 1)

if __name__ == '__main__': unittest.main()
