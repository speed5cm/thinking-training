"""Isolated record-layer and interrupted-answer tests; no evidence aggregation."""
import copy
import datetime as dt
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import sigma_session_store as store
from concept_authorization_fixture import write_authorization, question_event, event
from test_dynamic_candidate import publish_initial_plan

UNKNOWN = {'status':'unknown', 'answer_quote':'', 'wiki_path':'', 'wiki_quote':''}

def assessment():
    dimensions = {key: dict(UNKNOWN) for key in store.DIMENSIONS}
    dimensions['accuracy'] = {'status':'supported', 'answer_quote':'可核查',
        'wiki_path':'pilot-c01-c02/wiki/concepts/C01.md', 'wiki_quote':'可直接核查的描述和对原因、经历、意图的猜测不同。'}
    unknown = {'status':'unknown', 'question_quote':'', 'answer_quote':'', 'wiki_path':'', 'wiki_quote':'', 'reason':'', 'related_question_ids':[]}
    observations = {key: dict(unknown) for key in ('repetition', 'novel_transfer', 'misconception')}
    observations['support_complete'] = {'status':'unknown','support_event_ids':[]}
    return {'dimensions':dimensions, 'observations':observations}

class AssessmentRecords(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / 'project'
        shutil.copytree(ROOT, self.root, ignore=shutil.ignore_patterns('.git', 'records', '__pycache__', 'experiments'))
        self.folder = self.root / 'pilot-c01-c02/records/synthetic'
        self.folder.mkdir(parents=True)
        write_authorization(self.root)
        for obj, name, value in ((store.authorization, 'ROOT', self.root),
                                 (store.evidence.coach, 'ROOT', self.root / 'pilot-c01-c02'),
                                 (store.evidence, 'get_folder', lambda _: self.folder)):
            patch = mock.patch.object(obj, name, value); patch.start(); self.addCleanup(patch.stop)
        self.snap = {'state':{}, 'session':'', 'turns':[]}
        self.rev = 0
        self.commit([{'type':'session_start'}])
        publish_initial_plan(self.root, self.folder)

    def event(self, event_type, qid, **values):
        return event(event_type, qid, session_id=self.snap['session'], **values)

    def commit(self, events, **changes):
        proposal = copy.deepcopy(self.snap)
        proposal['turns'].extend(copy.deepcopy(events))
        proposal.update(changes)
        result = store.operate('synthetic', proposal, self.rev)
        self.snap = {k:result[k] for k in ('state','session','turns')}
        self.rev = result['revision']
        return result

    def question(self, purpose='assessment'):
        q = question_event(self.root, 'q1', purpose=purpose, session_id=self.snap['session'])
        self.commit([q])
        return self.snap['turns'][-1]

    def test_assessment_persistence_support_and_corrections(self):
        q = self.question()
        self.assertEqual(store.operate('synthetic')['turns'][-1], q)
        support = self.event('support','q1',event_id='s1',kind='hint',text='先看题目')
        self.commit([support])
        with self.assertRaises(store.Invalid): self.commit([support])
        a = self.event('answer','q1',text='这是可核查的描述')
        value = assessment(); value['observations']['support_complete']['support_event_ids'] = ['s1']
        analysis = self.event('analysis','q1',analysis=value)
        self.commit([a, analysis])
        original = copy.deepcopy(self.snap['turns'])
        changed = assessment(); changed['observations']['support_complete']['support_event_ids'] = ['s1']; changed['dimensions']['accuracy']['status'] = 'not_supported'
        self.commit([self.event('correction','q1',event_id='c1',reason='重新核对依据',replacement=changed)])
        self.commit([self.event('invalidation','q1',event_id='i1',reason='题意存在歧义')])
        self.assertEqual(self.snap['turns'][:len(original)], original)
        self.assertEqual(store.operate('synthetic')['turns'], self.snap['turns'])
        with self.assertRaises(store.Invalid): self.commit([self.event('invalidation','q1',event_id='i1',reason='重复')])
        altered = copy.deepcopy(self.snap); altered['turns'][1]['purpose'] = 'teaching'
        with self.assertRaises(store.Invalid): store.operate('synthetic', altered, self.rev)
        with self.assertRaises(store.Invalid): store.operate('synthetic', self.snap, self.rev - 1)

    def test_reject_bypass_invalid_basis_duplicate_and_uncommitted_question(self):
        q = question_event(self.root, 'q1', purpose='assessment', session_id=self.snap['session'])
        a = self.event('answer','q1',text='可核查')
        analysis = self.event('analysis','q1',analysis=assessment())
        with self.assertRaises(store.Invalid): self.commit([q, a, analysis])
        self.question()
        with self.assertRaises(store.Invalid): self.commit([question_event(self.root,'q2', session_id=self.snap['session'])])
        broken = assessment(); broken['dimensions']['accuracy']['answer_quote'] = '不存在'
        with self.assertRaises(store.Invalid): self.commit([a, self.event('analysis','q1',analysis=broken)])
        broken = assessment(); broken['dimensions']['explanation']['status'] = 'supported'
        with self.assertRaises(store.Invalid): self.commit([a, self.event('analysis','q1',analysis=broken)])
        self.commit([a,analysis])
        with self.assertRaises(store.Invalid): self.commit([a,analysis])
        with self.assertRaises(store.Invalid): self.commit([q])
        with self.assertRaises(store.Invalid): self.commit([self.event('analysis','q1',analysis=assessment())])
        with self.assertRaises(store.Invalid): self.commit([self.event('correction','q1',event_id='c1',reason='伪造',replacement={'purpose':'assessment'})])

    def test_teaching_cannot_become_assessment(self):
        self.question('teaching')
        with self.assertRaises(store.Invalid):
            changed = copy.deepcopy(self.snap); changed['turns'][1]['purpose'] = 'assessment'
            store.operate('synthetic', changed, self.rev)
        self.commit([self.event('answer','q1',text='可核查'), self.event('analysis','q1',analysis={'reason':'观察'})])
        with self.assertRaises(store.Invalid):
            self.commit([self.event('correction','q1',event_id='c1',reason='转评估',replacement=assessment())])

    def test_emergency_save_after_revoke_change_or_reauthorization(self):
        for failure in ('revoke', 'change', 'reauthorize'):
            with self.subTest(failure=failure):
                # Each case has its own snapshot and simulated authorization.
                if self.rev:
                    (self.folder / 'sigma/session-snapshot.json').unlink()
                    self.snap = {'state':{}, 'session':'', 'turns':[]}; self.rev = 0
                    write_authorization(self.root, version='base-' + failure)
                    self.commit([{'type':'session_start'}])
                self.question()
                if failure == 'revoke':
                    store.authorization.revoke()
                elif failure == 'change':
                    page = self.root / 'references/pedagogy.md'
                    page.write_text(page.read_text() + '\nchanged\n')
                else:
                    write_authorization(self.root, version='new-version')
                a = self.event('answer','q1',text='孩子已经说出的原答')
                stop = self.event('interruption','q1',reason='authorization_or_content_changed')
                for events in ([a, self.event('analysis','q1',analysis=assessment())], [a],
                               [a, stop, question_event(self.root,'q2', session_id=self.snap['session'])]):
                    with self.assertRaises(store.Invalid): self.commit(events)
                with self.assertRaises(store.Invalid): self.commit([a,stop], state={'status':'changed'})
                other = copy.deepcopy(self.snap); other['turns'].extend([a,stop])
                with self.assertRaises(store.Invalid): store.operate('child', other, self.rev)
                self.commit([a,stop])
                self.assertEqual([{k:v for k,v in e.items() if k != 'recorded_at'} for e in store.operate('synthetic')['turns'][-2:]], [a,stop])
                with self.assertRaises(store.Invalid): self.commit([a,stop])
                write_authorization(self.root, version='restored-' + failure)
                with self.assertRaises(store.Invalid): self.commit([self.event('analysis','q1',analysis=assessment())])
                with self.assertRaises(store.Invalid): self.commit([self.event('correction','q1',event_id='c1',reason='继续评分',replacement=assessment())])
                self.assertFalse((self.folder / 'evidence.jsonl').exists())

    def test_semantic_observations_and_support_completeness(self):
        self.commit([question_event(self.root, 'old', purpose='teaching', session_id=self.snap['session'])])
        self.commit([self.event('support','old',event_id='previous-support',kind='demonstration',text='前题演示')])
        self.commit([self.event('answer','old',text='可核查'), self.event('analysis','old',analysis={'reason':'旧题'})])
        self.question()
        self.commit([self.event('support','q1',event_id='s1',kind='hint',text='提示')])
        answer = self.event('answer','q1',text='可核查')
        value = assessment()
        with self.assertRaises(store.Invalid): self.commit([answer, self.event('analysis','q1',analysis=value)])
        value['observations']['support_complete'] = {'status':'unknown','support_event_ids':['previous-support','s1']}
        base = {'question_quote':'问题','answer_quote':'可核查',
                'wiki_path':'pilot-c01-c02/wiki/concepts/C01.md',
                'wiki_quote':'可直接核查的描述和对原因、经历、意图的猜测不同。',
                'reason':'比较前题的结构和情境','related_question_ids':[]}
        value['observations']['repetition'] = {'status':'yes', **base}
        with self.assertRaises(store.Invalid): self.commit([answer, self.event('analysis','q1',analysis=value)])
        value['observations']['repetition']['related_question_ids'] = ['old']
        value['observations']['novel_transfer'] = {'status':'yes', **base}
        with self.assertRaises(store.Invalid): self.commit([answer, self.event('analysis','q1',analysis=value)])
        value['observations']['novel_transfer']['related_question_ids'] = ['old']
        value['observations']['misconception'] = {'status':'resolved', **base, 'related_question_ids':['old']}
        with self.assertRaises(store.Invalid): self.commit([answer, self.event('analysis','q1',analysis=value)])
        value['observations']['misconception']['status'] = 'present'
        self.commit([answer, self.event('analysis','q1',analysis=value)])
        saved = store.operate('synthetic')['turns'][-1]['analysis']['observations']
        self.assertEqual(saved['repetition']['status'], 'yes')
        self.assertEqual(saved['support_complete']['status'], 'unknown')
        self.assertEqual(saved['support_complete']['support_event_ids'], ['previous-support','s1'])
        self.commit([question_event(self.root, 'q2', purpose='assessment', session_id=self.snap['session'])])
        followup = assessment()
        followup['observations']['misconception'] = {'status':'resolved', **base, 'related_question_ids':['q1']}
        followup['observations']['support_complete'] = {'status':'confirmed','support_event_ids':[]}
        self.commit([self.event('answer','q2',text='可核查'), self.event('analysis','q2',analysis=followup)])
        self.assertEqual(self.snap['turns'][-1]['analysis']['observations']['misconception']['status'], 'resolved')
        self.commit([self.event('invalidation','q1',event_id='invalid-q1',reason='原题歧义')])
        self.commit([question_event(self.root, 'q3', purpose='assessment', session_id=self.snap['session'])])
        with self.assertRaises(store.Invalid):
            self.commit([self.event('answer','q3',text='可核查'), self.event('analysis','q3',analysis=followup)])

    def test_server_time_sessions_and_forgery(self):
        q = question_event(self.root, 'q1', purpose='assessment', session_id=self.snap['session'])
        forged = dict(q, recorded_at='2000-01-01T00:00:00+00:00')
        with self.assertRaises(store.Invalid): self.commit([forged])
        with self.assertRaises(store.Invalid): self.commit([dict(q, session_id='fake')])
        with self.assertRaises(store.Invalid): self.commit([{'type':'session_resume'}])
        with self.assertRaises(store.Invalid): self.commit([{'type':'session_end','session_id':'fake'}])
        self.commit([q])
        with self.assertRaises(store.Invalid): self.commit([{'type':'session_end'}])
        stored = store.operate('synthetic')
        timestamp = dt.datetime.fromisoformat(stored['turns'][-1]['recorded_at'])
        self.assertEqual(timestamp.utcoffset(), dt.timedelta(0))
        with self.assertRaises(store.Invalid):
            self.commit([event('answer','q1',session_id='forged',text='可核查'), event('analysis','q1',session_id='forged',analysis=assessment())])
        with mock.patch.object(store, 'utc_now', return_value=timestamp - dt.timedelta(seconds=1)):
            with self.assertRaises(store.Invalid):
                self.commit([self.event('answer','q1',text='可核查'), self.event('analysis','q1',analysis=assessment())])
        with self.assertRaises(store.Invalid): store.operate('synthetic', self.snap, self.rev-1)
        altered = copy.deepcopy(self.snap); altered['turns'][-1]['recorded_at'] = '2000-01-01T00:00:00+00:00'
        with self.assertRaises(store.Invalid): store.operate('synthetic', altered, self.rev)

    def test_legacy_unanswered_question_can_only_save_interrupted_answer(self):
        old_question = question_event(self.root, 'legacy', purpose='teaching', session_id='old-session')
        old = {'schema_version':1, 'revision':1, 'state':{}, 'session':'', 'turns':[old_question]}
        (self.folder / 'sigma/session-snapshot.json').write_text(json.dumps(old, ensure_ascii=False))
        self.snap = {k:old[k] for k in ('state','session','turns')}; self.rev = 1
        answer = event('answer','legacy',session_id='old-session',text='已发生的原答')
        stop = event('interruption','legacy',session_id='old-session',reason='legacy_session_unverified')
        with self.assertRaises(store.Invalid):
            self.commit([answer, event('analysis','legacy',session_id='old-session',analysis={'reason':'评分'})])
        self.commit([answer, stop])
        self.assertNotIn('recorded_at', self.snap['turns'][0])
        self.assertIn('recorded_at', self.snap['turns'][1])
        self.assertEqual(self.snap['turns'][-1]['reason'], 'legacy_session_unverified')

    def test_cross_day_and_interval_times_are_preserved_without_aggregation(self):
        pairs = [
            (dt.datetime(2030,1,1,15,50,tzinfo=dt.timezone.utc), dt.datetime(2030,1,1,16,10,tzinfo=dt.timezone.utc), True, False),
            (dt.datetime(2030,1,1,16,10,tzinfo=dt.timezone.utc), dt.datetime(2030,1,2,5,10,tzinfo=dt.timezone.utc), False, True),
        ]
        zone = dt.timezone(dt.timedelta(hours=8))
        for first, second, crosses_day, twelve_hours in pairs:
            with self.subTest(first=first):
                (self.folder / 'sigma/session-snapshot.json').unlink()
                self.snap = {'state':{}, 'session':'', 'turns':[]}; self.rev = 0
                with mock.patch.object(store, 'utc_now', return_value=first):
                    self.commit([{'type':'session_start'}])
                    self.question()
                    self.commit([self.event('answer','q1',text='可核查'),self.event('analysis','q1',analysis=assessment())])
                    first_session = self.snap['session']
                    self.commit([{'type':'session_end'}])
                with mock.patch.object(store, 'utc_now', return_value=second):
                    self.commit([{'type':'session_resume'}])
                    self.assertNotEqual(first_session, self.snap['session'])
                    self.assertEqual(self.snap['turns'][-1]['previous_session_id'], first_session)
                    self.commit([question_event(self.root, 'q2', purpose='assessment', session_id=self.snap['session'])])
                    self.commit([self.event('answer','q2',text='可核查'), self.event('analysis','q2',analysis=assessment())])
                times = [dt.datetime.fromisoformat(e['recorded_at']) for e in self.snap['turns'] if e.get('type') == 'answer']
                self.assertEqual(times, [first, second])
                self.assertEqual(times[0].astimezone(zone).date() != times[1].astimezone(zone).date(), crosses_day)
                self.assertEqual(times[1] - times[0] >= dt.timedelta(hours=12), twelve_hours)
                self.assertFalse((self.folder / 'evidence.jsonl').exists())


if __name__ == '__main__': unittest.main()
