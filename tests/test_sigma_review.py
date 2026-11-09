"""Review task identity and migration in the experimental Sigma plan store."""
import datetime as dt
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest import mock
from concept_authorization_fixture import question_event, event, begin, snapshot

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('experimental_sigma_plan_store', ROOT / 'scripts/sigma_plan_store.py')
plans = importlib.util.module_from_spec(spec)
spec.loader.exec_module(plans)

class ReviewPersistence(unittest.TestCase):
    def publish(self, candidate):
        pending = plans.operate('prepare', 'test', candidate)
        return plans.operate('publish', 'test', candidate, confirmed_sha=pending['plan_sha256'])

    def test_confirmation_binds_candidate_and_live_inputs(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = root / 'learner'; folder.mkdir()
            candidate = root / 'proposal.json'; candidate.write_text('{"step":1}')
            ctx = {k:'one' for k in ('curriculum_digest','evidence_digest','learner_digest')}
            with mock.patch.object(plans.evidence.coach, 'ROOT', root), mock.patch.object(plans.evidence, 'get_folder', return_value=folder), mock.patch.object(plans.evidence, 'load_evidence', return_value=[]), mock.patch.object(plans.planner, 'context', side_effect=lambda *a, **kw: dict(ctx)), mock.patch.object(plans.planner, 'validate'):
                with self.assertRaises(plans.Invalid): plans.operate('publish', 'test', candidate)
                digest = plans.operate('prepare', 'test', candidate)['plan_sha256']
                candidate.write_text('{"step":2}')
                with self.assertRaises(plans.Invalid): plans.operate('publish', 'test', candidate, confirmed_sha=digest)
                candidate.write_text('{"step":1}')
                ctx['learner_digest'] = 'changed'
                with self.assertRaises(plans.Invalid): plans.operate('publish', 'test', candidate, confirmed_sha=digest)
                self.assertFalse((folder / 'sigma/plan-history.json').exists())
                digest = plans.operate('prepare', 'test', candidate)['plan_sha256']
                pending_path = folder / 'sigma/plan-pending.json'
                pending_copy = pending_path.read_text()
                self.assertEqual(plans.operate('publish', 'test', candidate, confirmed_sha=digest)['status'], 'current')
                # A confirmed proposal is single-use even if pending-file cleanup fails.
                pending_path.write_text(pending_copy)
                with self.assertRaises(plans.Invalid):
                    plans.operate('publish', 'test', candidate, confirmed_sha=digest)
                self.assertEqual(len(json.loads((folder / 'sigma/plan-history.json').read_text())['history']), 1)

    def test_dynamic_review_completes_and_schedules_next_without_formal_evidence(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp); folder = root / 'learner'; folder.mkdir()
            candidate = root / 'proposal.json'; candidate.write_text('{}')
            ctx = {k:'snapshot' for k in ('curriculum_digest','evidence_digest','learner_digest')}
            ctx['curriculum'] = {'concepts':[{'id':'C01'}]}
            with mock.patch.object(plans.evidence.coach, 'ROOT', root), mock.patch.object(plans.evidence, 'get_folder', return_value=folder), mock.patch.object(plans.evidence, 'load_evidence', return_value=[]), mock.patch.object(plans.planner, 'context', return_value=ctx), mock.patch.object(plans.planner, 'validate'), mock.patch.object(plans.sessions.authorization, 'check', return_value={'authorization_sha256':'a' * 64}):
                self.publish(candidate)
                snap, rev = begin(plans.sessions, 'test')
                snap['turns'].append(question_event(ROOT, 'q1', auth_sha='a' * 64, session_id=snap['session']))
                result = plans.sessions.operate('test', snap, rev)
                snap, rev = snapshot(result), result['revision']
                snap['turns'] += [event('answer', 'q1', text='不知道', session_id=snap['session']), event('analysis', 'q1', analysis={'reason':'需要复习'}, session_id=snap['session'])]
                result = plans.sessions.operate('test', snap, rev)
                snap, rev = snapshot(result), result['revision']
                scheduled = plans.operate('schedule-dynamic','test',payload={'concept':'C01','question_id':'q1','reason':'需要复习','interval_days':1})
                task = scheduled['dynamic_reviews'][0]
                self.assertEqual(scheduled['version'], 1)
                with self.assertRaises(plans.Invalid):
                    plans.operate('schedule-dynamic','test',payload={'concept':'C01','question_id':'q1','reason':'重复','interval_days':1})
                snap['turns'].append(question_event(ROOT, 'q2', auth_sha='a' * 64, review_task_id=task['task_id'], session_id=snap['session']))
                result = plans.sessions.operate('test', snap, rev)
                snap, rev = snapshot(result), result['revision']
                snap['turns'] += [event('answer', 'q2', text='回答', session_id=snap['session']), event('analysis', 'q2', analysis={'reason':'解释充分'}, session_id=snap['session'])]
                result = plans.sessions.operate('test', snap, rev)
                snap, rev = snapshot(result), result['revision']
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
                first = self.publish(candidate)
                records.append({'concept':'C01','session_id':'review','card':{},'captured_at':now.isoformat()})
                completed = plans.operate('complete-review','test',session='review')
                self.assertEqual(completed['review_queue'][0]['status'], 'completed')
                republished = self.publish(candidate)
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
