"""Synthetic integration of the common gates; no real child or reviewer."""
import copy
import datetime as dt
import hashlib
import json
import subprocess
import sys
import unittest

import test_dynamic_candidate as fixture
from concept_authorization_fixture import write_c02_authorization


class GenericLoop(unittest.TestCase):
    def setUp(self):
        self.f = fixture.DynamicCandidate('test_ready_and_recomputed_correction_invalidation')
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.root, self.folder = self.f.root, self.f.folder
        write_c02_authorization(self.root)
        for card in ('ST-C01-01.json', 'ST-C02-01.json'):
            (self.root / 'pilot-c01-c02/cards' / card).unlink()
        (self.folder / 'evidence.jsonl').write_text('{"concept":"C01","card":{"id":"deleted"}}\n')
        self.cli('scripts/sigma_plan_store.py', 'status')
        ctx = self.cli('scripts/validate_personal_roadmap.py', 'context')
        plan = json.loads((self.root / 'examples/ai-roadmap/fiction-plan.json').read_text())
        plan['learner'] = 'synthetic'
        for k in ('curriculum_digest', 'learner_digest', 'evidence_digest'):
            plan[k] = ctx[k]
        introduction = {s['concept']: s for s in plan['steps'] if s['kind'] == 'introduce'}
        plan['steps'] = [introduction[f'C{i:02}'] for i in range(1, 15)]
        path = self.folder / 'candidate.json'
        path.write_text(json.dumps(plan, ensure_ascii=False))
        prepared = self.cli('scripts/sigma_plan_store.py', 'prepare', '--plan', str(path))
        self.cli('scripts/sigma_plan_store.py', 'publish', '--plan', str(path),
                 '--confirmed-sha', prepared['plan_sha256'], '--synthetic-confirmation')

    def cli(self, script, action, *args, ok=True):
        proc = subprocess.run([sys.executable, str(self.root / script), action, '--learner', 'synthetic', *args],
                              cwd=self.root, capture_output=True, text=True, timeout=30)
        if ok:
            self.assertEqual(proc.returncode, 0, proc.stderr)
            return json.loads(proc.stdout)
        self.assertNotEqual(proc.returncode, 0, proc.stdout)
        return proc

    def test_session_lifecycle_does_not_require_c01_authorization(self):
        folder = self.root / 'pilot-c01-c02/records/synthetic-new'
        folder.mkdir()
        (self.root / 'pilot-c01-c02/concept-authorizations/C01.json').unlink()
        proc = subprocess.run([sys.executable, str(self.root / 'scripts/sigma_session_store.py'),
                               'commit', '--learner', 'synthetic-new', '--expected-revision', '0'],
                              input=json.dumps({'state':{}, 'session':'', 'turns':[{'type':'session_start'}]}),
                              cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        proc = subprocess.run([sys.executable, str(self.root / 'scripts/learning_evidence.py'),
                               'check', '--learner', 'synthetic-new', '--concept', 'C01'],
                              cwd=self.root, capture_output=True, text=True, timeout=30)
        self.assertNotEqual(proc.returncode, 0)

    def test_confirmed_loop_and_revocation(self):
        self.f.build()
        self.assertTrue(self.f.result()['candidate'])
        self.cli('scripts/learning_evidence.py', 'check', '--concept', 'C02', ok=False)
        record = json.loads((self.root / 'pilot-c01-c02/concept-authorizations/C02.json').read_text())
        digest = fixture.evidence.evidence_digest([record])
        pages = ['wiki/concepts/attribute-comparison.md', 'pilot-c01-c02/wiki/concepts/C02.md']
        question = {'type':'question', 'concept':'C02', 'session_id':self.f.snap['session'],
                    'question_id':'c02-q1', 'purpose':'teaching', 'text':'请比较两组材料。',
                    'wiki_sources':{p:hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in pages},
                    'authorization_sha256':digest}
        with self.assertRaises(fixture.store.Invalid):
            self.f.commit([question])
        self.cli('scripts/learning_evidence.py', 'confirm', '--concept', 'C01', '--synthetic-confirmation')
        self.cli('scripts/learning_evidence.py', 'confirm', '--concept', 'C01', '--synthetic-confirmation', ok=False)
        self.cli('pilot-c01-c02/scripts/coach.py', 'start', '--mode', 'C02', ok=False)
        self.assertEqual(self.cli('scripts/sigma_plan_store.py', 'status')['status'], 'current')
        self.assertEqual(self.cli('scripts/learning_evidence.py', 'check', '--concept', 'C02')['allowed'], 'C02')
        def state_change(state):
            proposal = copy.deepcopy(self.f.snap)
            proposal['state'] = state
            result = fixture.store.operate('synthetic', proposal, self.f.rev)
            self.f.snap = {k:result[k] for k in ('state', 'session', 'turns')}
            self.f.rev = result['revision']
        state_change({'planning_basis':{'change':'学习目标需要重核'}})
        self.assertEqual(self.cli('scripts/sigma_plan_store.py', 'status')['status'], 'stale')
        self.cli('scripts/learning_evidence.py', 'check', '--concept', 'C02', ok=False)
        state_change({})
        # A real C02 dynamic question is stored without reading a Coach card.
        self.f.commit([question])
        self.f.commit([self.f.ev('answer', 'c02-q1', text='合成回答'),
                       self.f.ev('analysis', 'c02-q1', analysis={'reason':'合成观察'})])
        self.assertEqual(self.cli('scripts/sigma_plan_store.py', 'status')['status'], 'current')
        basis = fixture.store.authorization.concept_basis('C03')
        auth = {'schema_version':1, 'concept':'C03', 'version':'synthetic-1',
                'review':{'kind':'synthetic_simulation', 'actor':'fixture', 'basis':'isolated test'},
                'status':'active', 'teaching_goal':basis['goal'], 'scope':basis['scope'], 'sources':basis['sources'],
                'content_sha256':{p:hashlib.sha256((self.root / p).read_bytes()).hexdigest() for p in basis['files']}}
        (self.root / 'pilot-c01-c02/concept-authorizations/C03.json').write_text(json.dumps(auth, ensure_ascii=False))
        # C03 content is authorized, but C02 mastery is not confirmed.
        self.cli('scripts/learning_evidence.py', 'check', '--concept', 'C03', ok=False)
        def assess(qid, novel=False):
            q = copy.deepcopy(question)
            q.update(question_id=qid, purpose='assessment', text='问题' + qid,
                     session_id=self.f.snap['session'], context='情境' + qid,
                     dimensions=list(fixture.store.DIMENSIONS), answer_basis=record['scope'], practice=qid == 'c02-a4')
            self.f.commit([q])
            analysis = self.f.assessment(qid, novel='yes' if novel else 'no', related=['c02-a1'] if novel else None)
            for d in analysis['dimensions'].values():
                if d['status'] != 'unknown':
                    d['wiki_path'], d['wiki_quote'] = pages[1], record['scope']
            for key in ('repetition', 'novel_transfer', 'misconception'):
                analysis['observations'][key]['wiki_path'] = pages[1]
                analysis['observations'][key]['wiki_quote'] = record['scope']
            self.f.commit([self.f.ev('answer', qid, text='原答'), self.f.ev('analysis', qid, analysis=analysis)])
        assess('c02-a1'); assess('c02-a2')
        self.f.commit([{'type':'session_end'}])
        self.f.now += dt.timedelta(hours=24)
        self.f.commit([{'type':'session_resume'}])
        assess('c02-a3', novel=True)
        assess('c02-a4')
        self.assertTrue(self.cli('scripts/learning_evidence.py', 'dynamic-candidate', '--concept', 'C02')['candidate'])
        self.cli('scripts/learning_evidence.py', 'check', '--concept', 'C03', ok=False)
        self.cli('scripts/learning_evidence.py', 'confirm', '--concept', 'C02', '--synthetic-confirmation')
        self.assertEqual(self.cli('scripts/learning_evidence.py', 'check', '--concept', 'C03')['allowed'], 'C03')
        self.assertEqual(self.cli('scripts/sigma_plan_store.py', 'status')['status'], 'current')
        c03 = {'type':'question', 'concept':'C03', 'session_id':self.f.snap['session'],
               'question_id':'c03-q1', 'purpose':'teaching', 'text':'怎样给这些事物分类？',
               'wiki_sources':{p:auth['content_sha256'][p] for p in basis['required_sources']},
               'authorization_sha256':fixture.evidence.evidence_digest([auth])}
        self.f.commit([c03])
        page = self.root / next(iter(basis['required_sources']))
        old = page.read_text(encoding='utf-8')
        page.write_text(old + '\n<!-- synthetic change -->\n', encoding='utf-8')
        self.cli('scripts/learning_evidence.py', 'check', '--concept', 'C03', ok=False)
        self.assertEqual(fixture.store.operate('synthetic')['turns'][-1]['text'], c03['text'])
        page.write_text(old, encoding='utf-8')
        self.assertEqual(self.cli('scripts/learning_evidence.py', 'check', '--concept', 'C03')['allowed'], 'C03')
        self.f.commit([self.f.ev('answer', 'c03-q1', text='合成回答'),
                       self.f.ev('analysis', 'c03-q1', analysis={'reason':'合成观察'})])
        q3 = next(e for e in self.f.snap['turns'] if e.get('question_id') == 'c02-a3' and e['type'] == 'question')
        self.f.commit([{'type':'invalidation', 'session_id':q3['session_id'], 'question_id':'c02-a3',
                        'event_id':'invalidate-c02-a3', 'reason':'合成测试中撤销证据'}])
        self.cli('scripts/learning_evidence.py', 'check', '--concept', 'C03', ok=False)
        self.cli('scripts/concept_authorization.py', 'revoke', '--concept', 'C01')
        self.cli('scripts/learning_evidence.py', 'check', '--concept', 'C02', ok=False)


if __name__ == '__main__':
    unittest.main()
