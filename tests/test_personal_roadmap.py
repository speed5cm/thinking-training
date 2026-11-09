import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest import mock
from concept_authorization_fixture import question_event, event, begin, snapshot
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
spec = importlib.util.spec_from_file_location('personal_planner', ROOT / 'scripts/validate_personal_roadmap.py')
planner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(planner)

class PersonalRoadmapTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.plan = json.loads((ROOT / 'examples/ai-roadmap/fiction-plan.json').read_text())
        cls.ctx = {'curriculum': planner.base.build(), 'curriculum_digest': cls.plan['curriculum_digest'],
                   'evidence_digest': cls.plan['evidence_digest'], 'learner_digest': cls.plan['learner_digest'],
                   'current_recommendation': {'action': 'collect_or_reinforce', 'concept': 'C01'}}

    def check_invalid(self, plan, ctx=None):
        with self.assertRaises(planner.Invalid):
            planner.validate(plan, ctx or self.ctx, 'fiction-demo')

    def test_example_valid_and_no_teaching_authorization(self):
        result = planner.validate(self.plan, self.ctx, 'fiction-demo')
        self.assertTrue(result['valid'])
        self.assertEqual(result['current_recommendation']['concept'], 'C01')
        self.assertIn('不验证语义', result['notice'])

    def test_prerequisites_and_complete_coverage(self):
        plan = copy.deepcopy(self.plan)
        plan['steps'][0], plan['steps'][4] = plan['steps'][4], plan['steps'][0]
        self.check_invalid(plan)
        plan = copy.deepcopy(self.plan)
        plan['steps'] = [s for s in plan['steps'] if s['concept'] != 'C13']
        self.check_invalid(plan)
        plan = copy.deepcopy(self.plan)
        plan['steps'].append(copy.deepcopy(plan['steps'][0]))
        self.check_invalid(plan)

    def test_citations_and_early_review(self):
        plan = copy.deepcopy(self.plan)
        plan['steps'][0]['wiki_pages'] = ['wiki/concepts/not-real.md']
        self.check_invalid(plan)
        plan = copy.deepcopy(self.plan)
        plan['steps'][0]['kind'] = 'review'
        self.check_invalid(plan)
        plan = copy.deepcopy(self.plan)
        plan['steps'][0]['reason'] = ' '
        self.check_invalid(plan)

    def test_stale_or_other_learner_rejected(self):
        for key in ('evidence_digest', 'curriculum_digest', 'learner_digest', 'learner'):
            plan = copy.deepcopy(self.plan)
            plan[key] = 'changed'
            self.check_invalid(plan)

    def test_live_profile_change_invalidates_plan(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(planner.evidence.coach, 'learner_dir', return_value=Path(tmp)):
            profile = Path(tmp) / 'planner-profile.md'
            profile.write_text('诊断：未知', encoding='utf-8')
            ctx = planner.context('synthetic-demo')
            plan = copy.deepcopy(self.plan)
            plan['learner'] = 'synthetic-demo'
            for key in ('curriculum_digest', 'evidence_digest', 'learner_digest'):
                plan[key] = ctx[key]
            planner.validate(plan, ctx, 'synthetic-demo')
            profile.write_text('诊断：需要复核', encoding='utf-8')
            with self.assertRaises(planner.Invalid):
                planner.validate(plan, planner.context('synthetic-demo'), 'synthetic-demo')

    def test_old_tutor_state_is_not_a_planning_input(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(planner.evidence.coach, 'learner_dir', return_value=Path(tmp)):
            before = planner.context('synthetic-demo')['learner_digest']
            (Path(tmp) / 'tutor-state.json').write_text('{"status":"paused"}', encoding='utf-8')
            self.assertEqual(planner.context('synthetic-demo')['learner_digest'], before)

    @mock.patch.object(planner.sigma_session.authorization, 'check', return_value={'authorization_sha256':'a' * 64})
    def test_sigma_snapshot_and_planning_basis_invalidate_plan(self, _check):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(planner.evidence.coach, 'learner_dir', return_value=Path(tmp)):
            snap, rev = begin(planner.sigma_session, 'synthetic-demo')
            snap['state']['question'] = '原题'
            result = planner.sigma_session.operate('synthetic-demo', snap, rev)
            snap, rev = snapshot(result), result['revision']
            ctx = planner.context('synthetic-demo')
            plan = copy.deepcopy(self.plan)
            plan['learner'] = 'synthetic-demo'
            for key in ('curriculum_digest', 'evidence_digest', 'learner_digest'):
                plan[key] = ctx[key]
            planner.validate(plan, ctx, 'synthetic-demo')
            snap['state']['question'] = '下一题'
            snap['turns'].append(question_event(ROOT, 'q1', text='下一题', auth_sha='a' * 64, session_id=snap['session']))
            result = planner.sigma_session.operate('synthetic-demo', snap, rev)
            snap, rev = snapshot(result), result['revision']
            with self.assertRaises(planner.Invalid):
                planner.validate(plan, planner.context('synthetic-demo'), 'synthetic-demo')
            ctx = planner.context('synthetic-demo')
            for key in ('curriculum_digest', 'evidence_digest', 'learner_digest'): plan[key] = ctx[key]
            snap['turns'].append(event('answer', 'q1', text='回答', session_id=snap['session']))
            snap['turns'].append(event('analysis', 'q1', analysis={'reason': '普通教学观察'}, session_id=snap['session']))
            result = planner.sigma_session.operate('synthetic-demo', snap, rev)
            snap, rev = snapshot(result), result['revision']
            with self.assertRaises(planner.Invalid):
                planner.validate(plan, planner.context('synthetic-demo'), 'synthetic-demo')
            ctx = planner.context('synthetic-demo')
            for key in ('curriculum_digest', 'evidence_digest', 'learner_digest'): plan[key] = ctx[key]
            snap['state']['planning_basis'] = {'C01': '需要复习'}
            planner.sigma_session.operate('synthetic-demo', snap, rev)
            with self.assertRaises(planner.Invalid):
                planner.validate(plan, planner.context('synthetic-demo'), 'synthetic-demo')

    def test_proposed_actions_cannot_grant_mastery_or_teaching(self):
        for kind in ('mastered', 'teach', 'skip'):
            plan = copy.deepcopy(self.plan)
            plan['steps'][0]['kind'] = kind
            self.check_invalid(plan)
        plan = copy.deepcopy(self.plan)
        plan['current_recommendation'] = {'action': 'teach', 'concept': 'C02'}
        self.check_invalid(plan)

if __name__ == '__main__':
    unittest.main()
