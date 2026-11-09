"""Failure and conflict checks for the Sigma session snapshot."""
import concurrent.futures
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from concept_authorization_fixture import question_event, event

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('sigma_session_store_test', ROOT / 'scripts/sigma_session_store.py')
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

@mock.patch.object(store.authorization, 'check', return_value={'authorization_sha256':'a' * 64})
class SnapshotTests(unittest.TestCase):
    def test_analysis_survives_multiple_turns_and_rejects_missing_or_duplicate(self, _check):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(store.evidence, 'get_folder', return_value=Path(tmp)), mock.patch.object(store.evidence.coach, 'ROOT', Path(tmp)):
            proposed = {'state': {}, 'session': '', 'turns': []}
            revision = 0
            for i in range(5):
                qid = f'q{i}'
                proposed['turns'].append(question_event(ROOT, qid, auth_sha='a' * 64))
                revision = store.operate('synthetic', proposed, revision)['revision']
                proposed['turns'].append(event('answer', qid, text=f'原话{i}'))
                with self.assertRaises(store.Invalid):
                    store.operate('synthetic', proposed, revision)
                proposed['turns'].append(event('analysis', qid, analysis={'reason':f'分析{i}'}))
                revision = store.operate('synthetic', proposed, revision)['revision']
            restored = store.operate('synthetic')
            self.assertEqual([e['analysis']['reason'] for e in restored['turns'] if e.get('type') == 'analysis'], [f'分析{i}' for i in range(5)])
            proposed['turns'].append(event('analysis', 'q0', analysis={'reason':'重复'}))
            with self.assertRaises(store.Invalid): store.operate('synthetic', proposed, revision)
            self.assertEqual(store.operate('synthetic'), restored)
    def test_failure_and_conflict_leave_complete_snapshot(self, _check):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            proposed = {'state': {'status':'active'}, 'session':'synthetic', 'turns':[question_event(ROOT, 'q', text='synthetic', auth_sha='a' * 64)]}
            with mock.patch.object(store.evidence, 'get_folder', return_value=folder), mock.patch.object(store.evidence.coach, 'ROOT', folder):
                store.operate('synthetic', proposed, 0)
                with mock.patch.object(store.os, 'replace', side_effect=OSError('synthetic disk error')):
                    with self.assertRaises(OSError):
                        store.operate('synthetic', proposed, 1)
                self.assertEqual(store.operate('synthetic')['revision'], 1)
                def commit():
                    try:
                        return store.operate('synthetic', proposed, 1)['revision']
                    except store.Invalid:
                        return 'conflict'
                with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
                    results = list(pool.map(lambda _: commit(), range(2)))
                self.assertCountEqual(results, [2, 'conflict'])
                self.assertEqual(store.operate('synthetic')['turns'], proposed['turns'])
                with self.assertRaises(store.Invalid):
                    store.operate('synthetic', {**proposed, 'turns': []}, 2)

if __name__ == '__main__': unittest.main()
