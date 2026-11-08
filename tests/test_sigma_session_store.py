"""Crash and concurrent update checks for the experimental session snapshot."""
import concurrent.futures
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('experimental_sigma_session_store', ROOT / 'experiments/sigma-integration/blocker-validation/overlay/scripts/sigma_session_store.py')
store = importlib.util.module_from_spec(spec)
spec.loader.exec_module(store)

class SnapshotTests(unittest.TestCase):
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
