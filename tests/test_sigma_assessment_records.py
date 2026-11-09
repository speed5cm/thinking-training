"""Isolated record-layer and interrupted-answer tests; no evidence aggregation."""
import copy
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

UNKNOWN = {'status':'unknown', 'answer_quote':'', 'wiki_path':'', 'wiki_quote':''}

def assessment():
    dimensions = {key: dict(UNKNOWN) for key in store.DIMENSIONS}
    dimensions['accuracy'] = {'status':'supported', 'answer_quote':'可核查',
        'wiki_path':'pilot-c01-c02/wiki/concepts/C01.md', 'wiki_quote':'可直接核查的描述和对原因、经历、意图的猜测不同。'}
    return {'dimensions':dimensions}

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

    def commit(self, events, **changes):
        proposal = copy.deepcopy(self.snap)
        proposal['turns'].extend(copy.deepcopy(events))
        proposal.update(changes)
        result = store.operate('synthetic', proposal, self.rev)
        self.snap = proposal
        self.rev = result['revision']
        return result

    def question(self, purpose='assessment'):
        q = question_event(self.root, 'q1', purpose=purpose)
        self.commit([q])
        return q

    def test_assessment_persistence_support_and_corrections(self):
        q = self.question()
        self.assertEqual(store.operate('synthetic')['turns'], [q])
        support = event('support','q1',event_id='s1',kind='hint',text='先看题目')
        self.commit([support])
        with self.assertRaises(store.Invalid): self.commit([support])
        a = event('answer','q1',text='这是可核查的描述')
        analysis = event('analysis','q1',analysis=assessment())
        self.commit([a, analysis])
        original = copy.deepcopy(self.snap['turns'])
        changed = assessment(); changed['dimensions']['accuracy']['status'] = 'not_supported'
        self.commit([event('correction','q1',event_id='c1',reason='重新核对依据',replacement=changed)])
        self.commit([event('invalidation','q1',event_id='i1',reason='题意存在歧义')])
        self.assertEqual(self.snap['turns'][:len(original)], original)
        self.assertEqual(store.operate('synthetic')['turns'], self.snap['turns'])
        with self.assertRaises(store.Invalid): self.commit([event('invalidation','q1',event_id='i1',reason='重复')])
        altered = copy.deepcopy(self.snap); altered['turns'][0]['purpose'] = 'teaching'
        with self.assertRaises(store.Invalid): store.operate('synthetic', altered, self.rev)
        with self.assertRaises(store.Invalid): store.operate('synthetic', self.snap, self.rev - 1)

    def test_reject_bypass_invalid_basis_duplicate_and_uncommitted_question(self):
        q = question_event(self.root, 'q1', purpose='assessment')
        a = event('answer','q1',text='可核查')
        analysis = event('analysis','q1',analysis=assessment())
        with self.assertRaises(store.Invalid): self.commit([q, a, analysis])
        self.question()
        with self.assertRaises(store.Invalid): self.commit([question_event(self.root,'q2')])
        broken = assessment(); broken['dimensions']['accuracy']['answer_quote'] = '不存在'
        with self.assertRaises(store.Invalid): self.commit([a, event('analysis','q1',analysis=broken)])
        broken = assessment(); broken['dimensions']['explanation']['status'] = 'supported'
        with self.assertRaises(store.Invalid): self.commit([a, event('analysis','q1',analysis=broken)])
        self.commit([a,analysis])
        with self.assertRaises(store.Invalid): self.commit([a,analysis])
        with self.assertRaises(store.Invalid): self.commit([q])
        with self.assertRaises(store.Invalid): self.commit([event('analysis','q1',analysis=assessment())])
        with self.assertRaises(store.Invalid): self.commit([event('correction','q1',event_id='c1',reason='伪造',replacement={'purpose':'assessment'})])

    def test_teaching_cannot_become_assessment(self):
        self.question('teaching')
        with self.assertRaises(store.Invalid):
            changed = copy.deepcopy(self.snap); changed['turns'][0]['purpose'] = 'assessment'
            store.operate('synthetic', changed, self.rev)
        self.commit([event('answer','q1',text='可核查'), event('analysis','q1',analysis={'reason':'观察'})])
        with self.assertRaises(store.Invalid):
            self.commit([event('correction','q1',event_id='c1',reason='转评估',replacement=assessment())])

    def test_emergency_save_after_revoke_change_or_reauthorization(self):
        for failure in ('revoke', 'change', 'reauthorize'):
            with self.subTest(failure=failure):
                # Each case has its own snapshot and simulated authorization.
                if self.rev:
                    (self.folder / 'sigma/session-snapshot.json').unlink()
                    self.snap = {'state':{}, 'session':'', 'turns':[]}; self.rev = 0
                    write_authorization(self.root, version='base-' + failure)
                self.question()
                if failure == 'revoke':
                    store.authorization.revoke()
                elif failure == 'change':
                    page = self.root / 'references/pedagogy.md'
                    page.write_text(page.read_text() + '\nchanged\n')
                else:
                    write_authorization(self.root, version='new-version')
                a = event('answer','q1',text='孩子已经说出的原答')
                stop = event('interruption','q1',reason='authorization_or_content_changed')
                for events in ([a, event('analysis','q1',analysis=assessment())], [a],
                               [a, stop, question_event(self.root,'q2')]):
                    with self.assertRaises(store.Invalid): self.commit(events)
                with self.assertRaises(store.Invalid): self.commit([a,stop], state={'status':'changed'})
                other = copy.deepcopy(self.snap); other['turns'].extend([a,stop])
                with self.assertRaises(store.Invalid): store.operate('child', other, self.rev)
                self.commit([a,stop])
                self.assertEqual(store.operate('synthetic')['turns'][-2:], [a,stop])
                with self.assertRaises(store.Invalid): self.commit([a,stop])
                write_authorization(self.root, version='restored-' + failure)
                with self.assertRaises(store.Invalid): self.commit([event('analysis','q1',analysis=assessment())])
                with self.assertRaises(store.Invalid): self.commit([event('correction','q1',event_id='c1',reason='继续评分',replacement=assessment())])
                self.assertFalse((self.folder / 'evidence.jsonl').exists())

if __name__ == '__main__': unittest.main()
