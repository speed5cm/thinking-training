"""C01 dynamic candidates: synthetic files and simulated times only."""
import copy
import datetime as dt
import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest import mock
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import sigma_session_store as store
import learning_evidence as evidence
from concept_authorization_fixture import write_authorization, question_event, event

WIKI = 'pilot-c01-c02/wiki/concepts/C01.md'
QUOTE = '可直接核查的描述和对原因、经历、意图的猜测不同。'

def publish_initial_plan(root, folder):
    def call(script, action, *args):
        result = subprocess.run([sys.executable, str(root / 'scripts' / script), action,
                                 '--learner', 'synthetic', *args], cwd=root,
                                capture_output=True, text=True, timeout=30, check=True)
        return json.loads(result.stdout)
    ctx = call('validate_personal_roadmap.py', 'context')
    plan = json.loads((root / 'examples/ai-roadmap/fiction-plan.json').read_text())
    plan['learner'] = 'synthetic'
    for key in ('curriculum_digest', 'learner_digest', 'evidence_digest'):
        plan[key] = ctx[key]
    steps = {step['concept']:step for step in plan['steps'] if step['kind'] == 'introduce'}
    plan['steps'] = [steps[concept['id']] for concept in ctx['curriculum']['concepts']]
    path = folder / 'initial-plan.json'
    path.write_text(json.dumps(plan, ensure_ascii=False), encoding='utf-8')
    prepared = call('sigma_plan_store.py', 'prepare', '--plan', str(path))
    call('sigma_plan_store.py', 'publish', '--plan', str(path), '--confirmed-sha',
         prepared['plan_sha256'], '--synthetic-confirmation')

class DynamicCandidate(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns('.git', 'records', '__pycache__', 'experiments'))
        self.folder = self.root / 'pilot-c01-c02/records/synthetic'; self.folder.mkdir(parents=True)
        write_authorization(self.root)
        for obj, name, val in ((store.authorization, 'ROOT', self.root), (evidence.coach, 'ROOT', self.root / 'pilot-c01-c02'), (evidence, 'get_folder', lambda _: self.folder)):
            p = mock.patch.object(obj, name, val); p.start(); self.addCleanup(p.stop)
        self.snap = {'state': {}, 'session': '', 'turns': []}; self.rev = 0
        # Fixture timestamps precede the real clock so subprocess writes cannot
        # appear to travel backwards after the simulated sessions.
        self.now = dt.datetime(2020, 1, 1, 4, tzinfo=dt.timezone.utc)
        self.commit([{'type':'session_start'}])
        publish_initial_plan(self.root, self.folder)

    def commit(self, events):
        obj = copy.deepcopy(self.snap); obj['turns'].extend(copy.deepcopy(events))
        with mock.patch.object(store, 'utc_now', return_value=self.now):
            result = store.operate('synthetic', obj, self.rev)
        self.snap = {k:result[k] for k in ('state', 'session', 'turns')}; self.rev = result['revision']

    def ev(self, event_type, qid, **kwargs):
        return event(event_type, qid, session_id=self.snap['session'], **kwargs)

    def assessment(self, qid, *, repeat='no', novel='no', misconception='absent', related=None, support=None, accuracy='supported'):
        ref = {'answer_quote':'原答', 'wiki_path':WIKI, 'wiki_quote':QUOTE}
        dims = {d:{'status':'supported', **ref} for d in store.DIMENSIONS}
        dims['accuracy']['status'] = accuracy
        if novel != 'yes': dims['novel_application'] = {'status':'unknown', 'answer_quote':'', 'wiki_path':'', 'wiki_quote':''}
        def observation(status, ids=None):
            return {'status':status, 'question_quote':'问题', **ref, 'reason':'结合原题原答与先前情境进行比较', 'related_question_ids':ids or []}
        return {'dimensions':dims, 'observations':{'repetition':observation(repeat, related if repeat == 'yes' else None),
                 'novel_transfer':observation(novel, related if novel == 'yes' else None),
                 'misconception':observation(misconception, related if misconception == 'resolved' else None),
                 'support_complete':{'status':'confirmed', 'support_event_ids':support or []}}}

    def question(self, qid, **kwargs):
        q = question_event(self.root, qid, text='问题' + qid, purpose='assessment', session_id=self.snap['session'],
                           dimensions=list(store.DIMENSIONS), context='情境' + qid, practice=qid == 'q3')
        self.commit([q])
        if kwargs.get('support'):
            self.commit([self.ev('support', qid, event_id=kwargs['support'][0], kind='hint', text='提示方向')])
        self.commit([self.ev('answer', qid, text='原答'), self.ev('analysis', qid, analysis=self.assessment(qid, **kwargs))])

    def build(self, second_time=None):
        self.question('q1'); self.question('q2')
        self.commit([{'type':'session_end'}])
        self.now = second_time or self.now + dt.timedelta(hours=24)
        self.commit([{'type':'session_resume'}])
        self.question('q3', novel='yes', related=['q1'])

    def result(self): return evidence.dynamic_candidate('synthetic')

    def test_ready_and_recomputed_correction_invalidation(self):
        self.build(); before = self.result(); self.assertTrue(before['candidate'], before)
        self.assertTrue(all(c['met'] for c in before['conditions'].values()))
        without_practice = copy.deepcopy(self.snap); without_practice.update(schema_version=1, revision=self.rev)
        next(e for e in without_practice['turns'] if e.get('question_id') == 'q3' and e['type'] == 'question')['practice'] = False
        auth = store.authorization.check('C01', 'synthetic')
        self.assertFalse(evidence.aggregate_dynamic(without_practice, auth, '', store, store.authorization)['conditions']['generative_practice']['met'])
        replacement = self.assessment('q3', novel='no', accuracy='not_supported')
        self.commit([self.ev('correction','q3', event_id='c1', reason='核对后更正', replacement=replacement)])
        after = self.result(); self.assertFalse(after['candidate']); self.assertNotEqual(before['evidence_digest'], after['evidence_digest'])
        self.assertEqual(after['evidence'][-1]['correctness'], 'not_supported')
        self.assertTrue(after['conditions']['valid_questions']['met'])
        self.assertFalse(after['conditions']['novel_transfer']['met'])
        self.commit([self.ev('invalidation','q3', event_id='i1', reason='题意歧义')])
        self.assertFalse(self.result()['conditions']['valid_questions']['met'])

    def test_insufficient_and_duplicate(self):
        self.question('q1'); self.question('q2', repeat='yes', related=['q1'])
        result = self.result(); self.assertFalse(result['candidate']); self.assertTrue(result['evidence'][1]['valid']); self.assertFalse(result['evidence'][1]['eligible_for_coverage'])
        self.assertEqual(result['conditions']['valid_questions']['evidence_ids'], ['q1'])

    def test_utc8_boundaries(self):
        for delta in (dt.timedelta(hours=4), dt.timedelta(hours=13)):
            with self.subTest(delta=delta):
                # First at 15:00 UTC: 4h crosses midnight, 13h crosses midnight too;
                # for the latter use 16:10 UTC so 13h stays on the same UTC+8 day.
                self.now = dt.datetime(2030,1,1,15 if delta.total_seconds() == 14400 else 16,10,tzinfo=dt.timezone.utc)
                self.build(self.now + delta)
                self.assertFalse(self.result()['conditions']['independent_sessions']['met'])
                (self.folder / 'sigma/session-snapshot.json').unlink()
                self.snap = {'state':{},'session':'','turns':[]}; self.rev = 0
                self.now = dt.datetime(2030,1,1,0,tzinfo=dt.timezone.utc); self.commit([{'type':'session_start'}])

    def test_resume_link_and_missing_time(self):
        self.build(); snap = copy.deepcopy(self.snap)
        resume = next(e for e in snap['turns'] if e['type'] == 'session_resume'); resume['previous_session_id'] = 'forged'
        snap.update(schema_version=1, revision=self.rev)
        auth = store.authorization.check('C01', 'synthetic')
        result = evidence.aggregate_dynamic(snap, auth, '', store, store.authorization)
        self.assertFalse(result['conditions']['independent_sessions']['met']); self.assertFalse(result['candidate'])
        resume['previous_session_id'] = next(e['session_id'] for e in snap['turns'] if e['type'] == 'session_end')
        next(e for e in snap['turns'] if e['type'] == 'answer').pop('recorded_at')
        self.assertFalse(evidence.aggregate_dynamic(snap, auth, '', store, store.authorization)['candidate'])

    def test_hints_unknown_and_misconception(self):
        self.question('q1', support=['hint1']); self.question('q2', misconception='present')
        self.commit([{'type':'session_end'}]); self.now += dt.timedelta(days=1); self.commit([{'type':'session_resume'}])
        self.question('q3', novel='yes', related=['q1'])
        result = self.result(); self.assertFalse(result['conditions']['no_unresolved_misconception']['met'])
        self.assertNotIn('q1', result['conditions']['unprompted_reasoned']['evidence_ids'])
        self.question('q4', misconception='resolved', related=['q2'])
        self.assertTrue(self.result()['conditions']['no_unresolved_misconception']['met'])
        replacement = self.assessment('q4', misconception='unknown')
        self.commit([self.ev('correction','q4', event_id='c4', reason='依据不足', replacement=replacement)])
        self.assertFalse(self.result()['conditions']['no_unresolved_misconception']['met'])

    def test_exact_twelve_hours_and_referenced_invalidation(self):
        self.now = dt.datetime(2030, 1, 1, 10, tzinfo=dt.timezone.utc)
        self.build(self.now + dt.timedelta(hours=12))
        self.assertTrue(self.result()['candidate'])
        # An invalidated prior question no longer supports the novelty claim.
        old_sid = next(e['session_id'] for e in self.snap['turns'] if e.get('question_id') == 'q1')
        self.commit([event('invalidation', 'q1', session_id=old_sid, event_id='old-invalid', reason='原题无效')])
        self.assertFalse(self.result()['conditions']['novel_transfer']['met'])

    def test_interrupted_answer_is_never_assessed(self):
        q = question_event(self.root, 'q1', purpose='assessment', session_id=self.snap['session'])
        self.commit([q]); store.authorization.revoke()
        self.commit([self.ev('answer','q1',text='原答'), self.ev('interruption','q1',reason='authorization_or_content_changed')])
        write_authorization(self.root, version='new-authorization')
        result = self.result()
        self.assertFalse(result['candidate'])
        self.assertFalse(result['evidence'][0]['valid'])
        self.assertIn('授权或旧会话中断', result['evidence'][0]['reasons'])

    def test_authorization_revocation_and_interruption(self):
        self.build(); self.assertTrue(self.result()['candidate'])
        store.authorization.revoke(); result = self.result()
        self.assertFalse(result['candidate']); self.assertFalse(result['conditions']['authorization']['met'])
        self.assertFalse(any(item['valid'] for item in result['evidence']))

if __name__ == '__main__': unittest.main()
