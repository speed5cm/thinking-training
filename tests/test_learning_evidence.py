import importlib.util
import json
import tempfile
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
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
        for learner in ('synthetic-a', 'synthetic-b'):
            (mod.coach.ROOT / 'records' / learner).mkdir(parents=True)
        self.candidate = {'candidate': False, 'rule_version':'test-rule', 'evidence_digest':'test-digest', 'evidence':[], 'conditions':{'authorization':{'met':True},'record_integrity':{'met':True}}}
        p = patch.object(mod, 'dynamic_candidate', side_effect=lambda *args, **kwargs: dict(self.candidate)); p.start(); self.addCleanup(p.stop)
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
        self.make_session('synthetic-a', 's1')
        mod.capture('synthetic-a', 's1', self.extra)
        record = mod.load_evidence(mod.get_folder('synthetic-a'))[0]
        self.assertEqual((record['raw_response'], record['reason_quote'], record['ai_temporary_correctness'], record['explanation_quality'], record['hint_level']), ('因为看见了', '因为看见了', 'correct', 'valid', 0))
        self.assertEqual(record['coach_parent_feedback'], ['家长观察'])
        self.assertEqual(record['parent_feedback'], '需要休息')
        self.assertEqual(record['transfer']['status'], 'unknown')
        self.assertEqual(mod.assess('synthetic-a')['training_status'], 'completed')
        self.assertEqual(mod.assess('synthetic-a')['assessments'][0]['mastery'], 'pending_confirmation')
        self.assertEqual(mod.assess('synthetic-b')['assessments'][0]['learning_progress']['evidence_opportunities'], 0)
        with self.assertRaises(mod.EvidenceError): mod.capture('synthetic-a', 's1', self.extra)

    def test_last_attempt_captures_actual_hints_and_support(self):
        self.make_session('synthetic-a', 's1', correctness='unknown', explanation='none')
        folder = mod.get_folder('synthetic-a')
        events = mod.coach.load_events(folder)
        events[2]['session_completed'] = False
        (folder / 'events.jsonl').write_text(''.join(json.dumps(e, ensure_ascii=False)+'\n' for e in events))
        mod.coach.append(folder, {'type':'hint','session_id':'s1','question':'ST-C01-01','level':1})
        mod.coach.append(folder, {'type':'attempt','session_id':'s1','question':'ST-C01-01','raw_response':'因为看见了','ai_assessment':{'correctness':'correct','explanation':'valid'},'session_completed':True})
        mod.capture('synthetic-a', 's1', self.extra)
        record = mod.load_evidence(folder)[0]
        self.assertEqual((record['hint_level'], record['prior_attempts']), (1, 1))

    def test_same_card_repeated_cannot_prove_mastery(self):
        for sid in ('s1','s2','s3'):
            self.make_session('synthetic-a', sid)
            mod.capture('synthetic-a', sid, self.extra)
        result = mod.assess('synthetic-a')['assessments'][0]
        self.assertEqual(result['learning_progress']['evidence_opportunities'], 0)
        self.assertEqual(result['mastery'], 'pending_confirmation')

    def test_legacy_card_observations_do_not_create_dynamic_candidate(self):
        for sid in ('s1', 's2'):
            self.make_session('synthetic-a', sid)
            mod.capture('synthetic-a', sid, self.extra)
        result = mod.assess('synthetic-a')
        self.assertEqual(result['historical_evidence_pending_review'], 2)
        self.assertEqual(result['assessments'][0]['mastery'], 'pending_confirmation')

    def test_diagnosis_and_revoked_cards_block(self):
        self.make_session('synthetic-a', 's1')
        with patch.object(mod.coach, 'load_card', side_effect=mod.coach.Stop('撤销')):
            with self.assertRaises(mod.coach.Stop): mod.capture('synthetic-a', 's1', self.extra)
        mod.capture('synthetic-a', 's1', self.extra)
        self.candidate['conditions'] = {'authorization':{'met':False}}
        self.assertEqual(mod.recommend('synthetic-a')['action'], 'blocked')

    def test_parent_confirmation_and_c02_gate(self):
        with self.assertRaises(mod.EvidenceError): mod.confirm_c01('synthetic-a')
        self.candidate['candidate'] = True
        destination = {'authorization':{'authorization_sha256':'synthetic'}, 'wiki_digest':'wiki', 'prerequisites':['C01']}
        with patch.object(mod, 'destination_basis', return_value=destination):
            self.assertEqual(mod.recommend('synthetic-a')['action'], 'parent_review')
            self.assertEqual(mod.confirm_c01('synthetic-a', synthetic_confirmation=True)['confirmation'], 'synthetic_simulation')
            self.assertEqual(mod.recommend('synthetic-a')['concept'], 'C02')
            self.candidate['evidence_digest'] = 'changed'
            self.assertEqual(mod.recommend('synthetic-a')['action'], 'parent_review')

    def test_confirmation_scope_and_legacy_fail_closed(self):
        candidate = {'rule_version':'dynamic-v1', 'evidence_digest':'new'}
        destination = {'synthetic':'destination'}
        current = {'concept':'C01', 'confirmation':'synthetic_simulation', 'rule_version':'dynamic-v1',
                   'evidence_digest':'new', 'destination_digest':mod.evidence_digest([destination])}
        self.assertTrue(mod.confirmation_valid(current, candidate, destination))
        self.assertFalse(mod.confirmation_valid({'concept':'C01','confirmation':'parent','evidence_digest':'new'}, candidate, destination))
        self.assertFalse(mod.confirmation_valid(current, {**candidate,'rule_version':'new-rule'}, destination))
        self.assertFalse(mod.confirmation_valid(current, candidate, {'synthetic':'changed'}))

    def test_recommendation_is_only_c01_and_respects_live_gate(self):
        self.assertEqual(mod.recommend('synthetic-a')['concept'], 'C01')
        self.candidate['conditions'] = {'authorization': {'met':False}}
        self.assertEqual(mod.recommend('synthetic-a')['action'], 'blocked')

if __name__ == '__main__': unittest.main()
