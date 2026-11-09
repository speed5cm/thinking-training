"""Failure and conflict checks for the Sigma session snapshot."""
import concurrent.futures
import copy
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from concept_authorization_fixture import question_event, event, begin, snapshot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('sigma_session_store_test', ROOT / 'scripts/sigma_session_store.py')
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

@mock.patch.object(store.authorization, 'check', return_value={'concept':'C01', 'authorization_sha256':'a' * 64})
class SnapshotTests(unittest.TestCase):
    def setUp(self):
        # Storage-only tests isolate persistence; route gates have integration tests.
        gate = mock.patch.object(store.evidence, 'authorize_concept_locked', return_value={'allowed':'C01'})
        gate.start()
        self.addCleanup(gate.stop)

    def test_stale_route_cannot_be_recorded_as_authorization_interruption(self, _check):
        _check.return_value = {'concept': 'C01', 'authorization_sha256': 'a' * 64}
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(store.evidence, 'get_folder', return_value=Path(tmp)), mock.patch.object(store.evidence.coach, 'ROOT', Path(tmp)):
            proposed, revision = begin(store, 'synthetic')
            proposed['turns'].append(question_event(ROOT, 'q', auth_sha='a' * 64, session_id=proposed['session']))
            with mock.patch.object(store.evidence, 'authorize_concept_locked', return_value={'allowed': 'C01'}):
                result = store.operate('synthetic', proposed, revision)
            proposed = snapshot(result)
            proposed['turns'].extend([event('answer', 'q', text='原答', session_id=proposed['session']),
                                      event('interruption', 'q', reason='authorization_or_content_changed', session_id=proposed['session'])])
            with mock.patch.object(store.evidence, 'authorize_concept_locked', side_effect=store.evidence.EvidenceError('路线已过期')):
                with self.assertRaisesRegex(store.Invalid, '路线、先修或概念门禁不可用'):
                    store.operate('synthetic', proposed, result['revision'])
            self.assertEqual(store.operate('synthetic')['turns'][-1]['type'], 'question')

    def test_analysis_survives_multiple_turns_and_rejects_missing_or_duplicate(self, _check):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(store.evidence, 'get_folder', return_value=Path(tmp)), mock.patch.object(store.evidence.coach, 'ROOT', Path(tmp)):
            proposed, revision = begin(store, 'synthetic')
            for i in range(5):
                qid = f'q{i}'
                proposed['turns'].append(question_event(ROOT, qid, auth_sha='a' * 64, session_id=proposed['session']))
                result = store.operate('synthetic', proposed, revision)
                proposed = snapshot(result); revision = result['revision']
                proposed['turns'].append(event('answer', qid, text=f'原话{i}', session_id=proposed['session']))
                with self.assertRaises(store.Invalid):
                    store.operate('synthetic', proposed, revision)
                proposed['turns'].append(event('analysis', qid, analysis={'reason':f'分析{i}'}, session_id=proposed['session']))
                result = store.operate('synthetic', proposed, revision)
                proposed = snapshot(result); revision = result['revision']
            restored = store.operate('synthetic')
            self.assertEqual([e['analysis']['reason'] for e in restored['turns'] if e.get('type') == 'analysis'], [f'分析{i}' for i in range(5)])
            proposed['turns'].append(event('analysis', 'q0', analysis={'reason':'重复'}, session_id=proposed['session']))
            with self.assertRaises(store.Invalid): store.operate('synthetic', proposed, revision)
            self.assertEqual(store.operate('synthetic'), restored)
    def test_failure_and_conflict_leave_complete_snapshot(self, _check):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with mock.patch.object(store.evidence, 'get_folder', return_value=folder), mock.patch.object(store.evidence.coach, 'ROOT', folder):
                proposed, revision = begin(store, 'synthetic')
                proposed['state']['status'] = 'active'
                proposed['turns'].append(question_event(ROOT, 'q', text='synthetic', auth_sha='a' * 64, session_id=proposed['session']))
                result = store.operate('synthetic', proposed, revision)
                proposed = snapshot(result); revision = result['revision']
                with mock.patch.object(store.os, 'replace', side_effect=OSError('synthetic disk error')):
                    with self.assertRaises(OSError):
                        store.operate('synthetic', proposed, revision)
                self.assertEqual(store.operate('synthetic')['revision'], revision)
                def commit():
                    try:
                        return store.operate('synthetic', proposed, revision)['revision']
                    except store.Invalid:
                        return 'conflict'
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: commit(), range(2)))
                self.assertCountEqual(results, [revision + 1, 'conflict'])
                self.assertEqual(store.operate('synthetic')['turns'], proposed['turns'])
                with self.assertRaises(store.Invalid):
                    store.operate('synthetic', {**proposed, 'turns': []}, revision + 1)

if __name__ == '__main__': unittest.main()
