import copy
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
from unittest import mock
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
            ctx = planner.context('fiction-demo')
            plan = copy.deepcopy(self.plan)
            for key in ('curriculum_digest', 'evidence_digest', 'learner_digest'):
                plan[key] = ctx[key]
            planner.validate(plan, ctx, 'fiction-demo')
            profile.write_text('诊断：需要复核', encoding='utf-8')
            with self.assertRaises(planner.Invalid):
                planner.validate(plan, planner.context('fiction-demo'), 'fiction-demo')

    def test_sigma_planning_basis_invalidates_plan_but_turns_do_not(self):
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(planner.evidence.coach, 'learner_dir', return_value=Path(tmp)):
            snapshot = {'state': {'question': '原题'}, 'session': '记录', 'turns': []}
            planner.sigma_session.operate('fiction-demo', snapshot, 0)
            ctx = planner.context('fiction-demo')
            plan = copy.deepcopy(self.plan)
            for key in ('curriculum_digest', 'evidence_digest', 'learner_digest'):
                plan[key] = ctx[key]
            planner.validate(plan, ctx, 'fiction-demo')
            snapshot['state']['question'] = '下一题'
            snapshot['turns'].append({'type': 'question', 'question_id': 'q1', 'text': '下一题'})
            planner.sigma_session.operate('fiction-demo', snapshot, 1)
            planner.validate(plan, planner.context('fiction-demo'), 'fiction-demo')
            snapshot['turns'].append({'type': 'answer', 'question_id': 'q1', 'text': '回答'})
            snapshot['turns'].append({'type': 'analysis', 'question_id': 'q1', 'analysis': {'reason': '普通教学观察'}})
            planner.sigma_session.operate('fiction-demo', snapshot, 2)
            planner.validate(plan, planner.context('fiction-demo'), 'fiction-demo')
            snapshot['state']['planning_basis'] = {'C01': '需要复习'}
            planner.sigma_session.operate('fiction-demo', snapshot, 3)
            with self.assertRaises(planner.Invalid):
                planner.validate(plan, planner.context('fiction-demo'), 'fiction-demo')
            (Path(tmp) / 'sigma' / 'state.json').write_text('{}', encoding='utf-8')
            with self.assertRaises(planner.sigma_session.Invalid):
                planner.context('fiction-demo')

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
