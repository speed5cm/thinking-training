"""Review task identity and migration in the experimental Sigma plan store."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('experimental_sigma_plan_store', ROOT / 'experiments/sigma-integration/blocker-validation/overlay/scripts/sigma_plan_store.py')
plans = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plans)

class ReviewPersistence(unittest.TestCase):
    def test_republish_preserves_completion_and_legacy_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'learner'
            folder.mkdir()
            candidate = root / 'proposal.json'
            candidate.write_text('{}')
            now = dt.datetime.now(dt.timezone.utc)
            records = [{'concept':'C01','session_id':'old','captured_at':(now-dt.timedelta(days=2)).isoformat()}]
            ctx = {k:'snapshot' for k in ('curriculum_digest','evidence_digest','learner_digest')}
            with mock.patch.object(plans.evidence.coach, 'ROOT', root), mock.patch.object(plans.evidence, 'get_folder', return_value=folder), mock.patch.object(plans.evidence, 'load_evidence', side_effect=lambda f: records), mock.patch.object(plans.planner, 'context', return_value=ctx), mock.patch.object(plans.planner, 'validate'):
                first = plans.operate('publish','test',candidate)
                records.append({'concept':'C01','session_id':'review','captured_at':now.isoformat()})
                completed = plans.operate('complete-review','test',session='review')
                self.assertEqual(completed['review_queue'][0]['status'], 'completed')
                republished = plans.operate('publish','test',candidate)
                self.assertEqual(len(republished['review_queue']), 1)
                self.assertEqual(republished['review_queue'][0]['status'], 'completed')
                self.assertEqual(republished['review_queue'][0]['task_id'], first['review_queue'][0]['task_id'])
                path = folder / 'sigma/plan-history.json'
                store = json.loads(path.read_text())
                del store['review_events'][0]['task_id']
                path.write_text(json.dumps(store))
                self.assertEqual(plans.operate('status','test')['review_queue'][0]['status'], 'completed')
                with self.assertRaises(plans.Invalid):
                    plans.operate('complete-review','test',session='review')

if __name__ == '__main__':
    unittest.main()
