import importlib.util
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('learning_evidence', ROOT / 'scripts/learning_evidence.py')
mod = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mod)

class EvidenceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_root = mod.coach.ROOT
        mod.coach.ROOT = Path(self.tmp.name)
        self.addCleanup(setattr, mod.coach, 'ROOT', self.old_root)
        self.patches = [patch.object(mod.coach, 'gate', return_value=[]),
                        patch.object(mod.coach, 'load_card', return_value=({'version': '1.1.0'}, 'abc'))]
        for p in self.patches:
            p.start()
            self.addCleanup(p.stop)
        for learner in ('a', 'b'):
            (mod.coach.ROOT / 'records' / learner).mkdir(parents=True)
        self.extra = {'reason_quote': '因为看见了', 'transfer': {'status': 'unknown', 'observation': '', 'parent_verified_novel': False}, 'parent_feedback': '需要休息'}

    def make_session(self, learner, sid, response='因为看见了', correctness='correct', explanation='valid'):
        folder = mod.coach.learner_dir(learner)
        q = {'id': 'ST-C01-01', 'concept': 'C01', 'version': '1.1.0', 'sha256': 'abc', 'source': 'wiki/sources/project-research.md'}
        for e in [{'type':'start','session_id':sid,'mode':'C01','questions':[q]},
                  {'type':'show','session_id':sid,'question':q['id']},
                  {'type':'attempt','session_id':sid,'question':q['id'],'raw_response':response,'ai_assessment':{'correctness':correctness,'explanation':explanation},'session_completed':True},
                  {'type':'parent_feedback','session_id':sid,'text':'家长观察'}]:
            mod.coach.append(folder, e)

    def test_capture_fields_isolation_duplicate_and_completion(self):
        self.make_session('a', 's1')
        mod.capture('a', 's1', self.extra)
        record = mod.load_evidence(mod.get_folder('a'))[0]
        self.assertEqual((record['raw_response'], record['reason_quote'], record['ai_temporary_correctness'], record['explanation_quality'], record['hint_level']), ('因为看见了', '因为看见了', 'correct', 'valid', 0))
        self.assertEqual(record['coach_parent_feedback'], ['家长观察'])
        self.assertEqual(record['parent_feedback'], '需要休息')
        self.assertEqual(record['transfer']['status'], 'unknown')
        self.assertEqual(mod.assess('a')['training_status'], 'completed')
        self.assertEqual(mod.assess('a')['assessments'][0]['mastery'], 'pending_confirmation')
        self.assertEqual(mod.assess('b')['assessments'][0]['learning_progress']['evidence_opportunities'], 0)
        with self.assertRaises(mod.EvidenceError): mod.capture('a', 's1', self.extra)

    def test_last_attempt_captures_actual_hints_and_support(self):
        self.make_session('a', 's1', correctness='unknown', explanation='none')
        folder = mod.get_folder('a')
        events = mod.coach.load_events(folder)
        events[2]['session_completed'] = False
        (folder / 'events.jsonl').write_text(''.join(json.dumps(e, ensure_ascii=False)+'\n' for e in events))
        mod.coach.append(folder, {'type':'hint','session_id':'s1','question':'ST-C01-01','level':1})
        mod.coach.append(folder, {'type':'attempt','session_id':'s1','question':'ST-C01-01','raw_response':'因为看见了','ai_assessment':{'correctness':'correct','explanation':'valid'},'session_completed':True})
        mod.capture('a', 's1', self.extra)
        record = mod.load_evidence(folder)[0]
        self.assertEqual((record['hint_level'], record['prior_attempts']), (1, 1))

    def test_same_card_repeated_cannot_prove_mastery(self):
        for sid in ('s1','s2','s3'):
            self.make_session('a', sid)
            mod.capture('a', sid, self.extra)
        result = mod.assess('a')['assessments'][0]
        self.assertEqual(result['eligible_sessions'], 3)
        self.assertEqual(result['eligible_distinct_cards'], 1)
        self.assertEqual(result['mastery'], 'pending_confirmation')

    def test_evaluation_needs_transfer_and_distinct_sessions_and_cards(self):
        base = {'concept':'C01','session_id':'s1','card':{'id':'q1'},'ai_temporary_correctness':'correct', 'explanation_quality':'valid', 'raw_response':'因为看见了','reason_quote':'因为看见了','hint_level':0,'prior_attempts':0,'prior_support':[], 'transfer':{'status':'unknown','parent_verified_novel':False,'observation':''}}
        other = {**base, 'session_id':'s2', 'card':{'id':'q2'}}
        self.assertEqual(mod.evaluate([base, other], 'C01')['mastery'], 'pending_confirmation')
        other = {**other, 'transfer':{'status':'yes','parent_verified_novel':True,'observation':'陌生场景'}}
        self.assertEqual(mod.evaluate([base, other], 'C01')['mastery'], 'mastered_candidate')
        self.assertEqual(mod.evaluate([base, {**other, 'session_id':'s1'}], 'C01')['mastery'], 'pending_confirmation')
        self.assertEqual(mod.evaluate([base, {**other, 'prior_support':['demo']}], 'C01')['mastery'], 'pending_confirmation')

    def test_diagnosis_and_revoked_cards_block(self):
        self.make_session('a', 's1')
        with patch.object(mod.coach, 'load_card', side_effect=mod.coach.Stop('撤销')):
            with self.assertRaises(mod.coach.Stop): mod.capture('a', 's1', self.extra)
        mod.capture('a', 's1', self.extra)
        with patch.object(mod.coach, 'load_card', side_effect=mod.coach.Stop('撤销')):
            with self.assertRaises(mod.coach.Stop): mod.recommend('a')

    def test_parent_confirmation_and_c02_gate(self):
        with self.assertRaises(mod.EvidenceError): mod.confirm_c01('a')
        candidate = {'concept':'C01', 'mastery':'mastered_candidate', 'learning_progress':{'evidence_opportunities':2}, 'eligible_sessions':2, 'eligible_distinct_cards':2, 'novel_transfer_observed':True, 'unclear_explanations':0, 'difficulty_observations':0}
        data = {'concepts':[{'id':'C01','formal_teaching_available':True}, {'id':'C02','formal_teaching_available':True,'hard_prerequisites':['C01']}]}
        with patch.object(mod, 'evaluate', return_value=candidate), patch.object(mod.roadmap, 'build', return_value=data):
            self.assertEqual(mod.recommend('a')['action'], 'parent_review')
            mod.confirm_c01('a')
            self.assertEqual(mod.recommend('a')['concept'], 'C02')
            data['concepts'][1]['formal_teaching_available'] = False
            self.assertEqual(mod.recommend('a')['action'], 'blocked')
            data['concepts'][1]['formal_teaching_available'] = True
            # Confirmation is tied to the exact evidence, including later additions.
            with patch.object(mod, 'evidence_digest', return_value='changed'):
                self.assertEqual(mod.recommend('a')['action'], 'parent_review')

    def test_recommendation_is_only_c01_and_respects_live_gate(self):
        data = {'concepts':[{'id':'C01','formal_teaching_available':True}, {'id':'C02','formal_teaching_available':True}]}
        with patch.object(mod.roadmap, 'build', return_value=data):
            self.assertEqual(mod.recommend('a')['concept'], 'C01')
            data['concepts'][0]['formal_teaching_available'] = False
            self.assertEqual(mod.recommend('a')['action'], 'blocked')
            self.assertIsNone(mod.recommend('a')['concept'])

if __name__ == '__main__': unittest.main()
