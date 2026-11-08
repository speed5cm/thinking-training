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
spec = importlib.util.spec_from_file_location('experimental_sigma_plan_store', ROOT / 'scripts/sigma_plan_store.py')
plans = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plans)

class ReviewPersistence(unittest.TestCase):
    def test_dynamic_review_completes_and_schedules_next_without_formal_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = root / 'learner'; folder.mkdir()
            candidate = root / 'proposal.json'; candidate.write_text('{}')
            ctx = {k:'snapshot' for k in ('curriculum_digest','evidence_digest','learner_digest')}
            ctx['curriculum'] = {'concepts':[{'id':'C01'}]}
            with mock.patch.object(plans.evidence.coach, 'ROOT', root), mock.patch.object(plans.evidence, 'get_folder', return_value=folder), mock.patch.object(plans.evidence, 'load_evidence', return_value=[]), mock.patch.object(plans.planner, 'context', return_value=ctx), mock.patch.object(plans.planner, 'validate'):
                plans.operate('publish','test',candidate)
                snap = {'state':{}, 'session':'', 'turns':[
                    {'type':'question','question_id':'q1','text':'问题'},
                    {'type':'answer','question_id':'q1','text':'不知道'},
                    {'type':'analysis','question_id':'q1','analysis':{'reason':'需要复习'}}]}
                plans.sessions.operate('test', snap, 0)
                scheduled = plans.operate('schedule-dynamic','test',payload={'concept':'C01','question_id':'q1','reason':'需要复习','interval_days':1})
                task = scheduled['dynamic_reviews'][0]
                self.assertEqual(scheduled['version'], 1)
                with self.assertRaises(plans.Invalid):
                    plans.operate('schedule-dynamic','test',payload={'concept':'C01','question_id':'q1','reason':'重复','interval_days':1})
                snap['turns'] += [{'type':'question','question_id':'q2','text':'复习题','review_task_id':task['task_id']},
                                  {'type':'answer','question_id':'q2','text':'回答'},
                                  {'type':'analysis','question_id':'q2','analysis':{'reason':'解释充分'}}]
                plans.sessions.operate('test', snap, 1)
                result = {'task_id':task['task_id'],'question_id':'q2','result':'correct','next_interval_days':2}
                with self.assertRaises(plans.Invalid): plans.operate('complete-dynamic','test',payload=result)
                path = folder / 'sigma/plan-history.json'
                data = json.loads(path.read_text()); data['dynamic_reviews'][0]['due_at'] = '2020-01-01T00:00:00+00:00'; path.write_text(json.dumps(data))
                completed = plans.operate('complete-dynamic','test',payload=result)
                self.assertEqual([x['status'] for x in completed['dynamic_reviews']], ['completed','pending'])
                self.assertEqual(completed['dynamic_reviews'][1]['interval_days'], 2)
                self.assertEqual(completed['version'], 1)
                self.assertFalse((folder / 'evidence.jsonl').exists())
                with self.assertRaises(plans.Invalid): plans.operate('complete-dynamic','test',payload=result)
                self.assertEqual(plans.operate('status','test')['dynamic_reviews'], completed['dynamic_reviews'])

    def test_republish_preserves_completion_and_legacy_events(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            folder = root / 'learner'
            folder.mkdir()
            candidate = root / 'proposal.json'
            candidate.write_text('{}')
            now = dt.datetime.now(dt.timezone.utc)
            records = [{'concept':'C01','session_id':'old','card':{},'captured_at':(now-dt.timedelta(days=2)).isoformat()}]
            ctx = {k:'snapshot' for k in ('curriculum_digest','evidence_digest','learner_digest')}
            with mock.patch.object(plans.evidence.coach, 'ROOT', root), mock.patch.object(plans.evidence, 'get_folder', return_value=folder), mock.patch.object(plans.evidence, 'load_evidence', side_effect=lambda f: records), mock.patch.object(plans.evidence, 'current_card', return_value=True), mock.patch.object(plans.planner, 'context', return_value=ctx), mock.patch.object(plans.planner, 'validate'):
                first = plans.operate('publish','test',candidate)
                records.append({'concept':'C01','session_id':'review','card':{},'captured_at':now.isoformat()})
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
