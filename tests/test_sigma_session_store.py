"""Failure, conflict and legacy checks for the Sigma session snapshot."""
import concurrent.futures
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('sigma_session_store_test', ROOT / 'scripts/sigma_session_store.py')
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

class SnapshotTests(unittest.TestCase):
    def test_legacy_files_block_read_and_commit_even_after_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            with mock.patch.object(store.evidence, 'get_folder', return_value=folder):
                proposed = {'state': {'pending_question': '原题'}, 'session': '记录', 'turns': []}
                store.operate('synthetic', proposed, 0)
                for name in store.LEGACY:
                    legacy = folder / 'sigma' / name
                    legacy.write_text('旧数据', encoding='utf-8')
                    with self.assertRaises(store.Invalid):
                        store.operate('synthetic')
                    with self.assertRaises(store.Invalid):
                        store.operate('synthetic', proposed, 1)
                    self.assertEqual(legacy.read_text(encoding='utf-8'), '旧数据')
                    legacy.unlink()
                self.assertEqual(store.operate('synthetic')['state'], proposed['state'])

    def test_failure_and_conflict_leave_complete_snapshot(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            proposed = {'state': {'status':'active'}, 'session':'synthetic', 'turns':[{'question':'synthetic'}]}
            with mock.patch.object(store.evidence, 'get_folder', return_value=folder):
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
