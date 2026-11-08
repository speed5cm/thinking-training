import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'scripts'))
import tutor_loop as tutor

class TutorLoopTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.folder = Path(self.tmp.name) / 'anonymous'
        self.patch = patch.object(tutor.coach, 'learner_dir', return_value=self.folder)
        self.patch.start()

    def tearDown(self):
        self.patch.stop(); self.tmp.cleanup()

    def run_action(self, action, payload=None):
        return tutor.run(action, 'anonymous', payload or {})

    def test_pause_resume_and_raw_evidence(self):
        self.run_action('start')
        q = {'action': 'diagnose', 'reason': '了解起点', 'question': '你能确定什么？'}
        self.run_action('question', q)
        with self.assertRaises(tutor.Stop): self.run_action('question', q)
        self.run_action('pause', {'reason': '累了'})
        self.assertEqual(self.run_action('resume')['state']['turns'][-1]['question'], q['question'])
        analysis = {k: 'unknown' for k in tutor.FIELDS}
        analysis['evidence_quote'] = '我看见书'
        self.run_action('answer', {'response': '我看见书，不知道是谁放的', 'analysis': analysis, 'parent_observation': ''})
        t = self.run_action('context')['state']['turns'][-1]
        self.assertEqual(t['response'], '我看见书，不知道是谁放的')
        self.assertEqual(t['analysis']['evidence_quote'], '我看见书')
        self.assertEqual(self.run_action('context')['recommendation']['assessment']['assessments'][0]['mastery'], 'pending_confirmation')

    def test_fabricated_quote_does_not_save(self):
        self.run_action('start')
        self.run_action('question', {'action': 'diagnose', 'reason': '起点', 'question': '你看见什么？'})
        analysis = {k: 'unknown' for k in tutor.FIELDS}; analysis['evidence_quote'] = '捏造'
        with self.assertRaises(tutor.Stop): self.run_action('answer', {'response': '一本书', 'analysis': analysis, 'parent_observation': ''})
        self.assertIsNone(self.run_action('context')['state']['turns'][-1]['response'])

    def test_revoked_published_card_blocks_resume(self):
        self.run_action('start')
        self.run_action('pause', {'reason': ''})
        with patch.object(tutor.coach, 'load_card', side_effect=tutor.coach.Stop('撤销发布')):
            with self.assertRaises((tutor.Stop, tutor.coach.Stop)): self.run_action('resume')
        self.assertEqual(json.loads((self.folder / 'tutor-state.json').read_text())['status'], 'paused')

    def test_roadmap_digest_tracks_tutor_without_promoting_mastery(self):
        self.run_action('start')
        before = tutor.planner.context('anonymous')['learner_digest']
        self.run_action('question', {'action': 'diagnose', 'reason': '起点', 'question': '你看见什么？'})
        self.assertNotEqual(before, tutor.planner.context('anonymous')['learner_digest'])
        self.assertEqual(self.run_action('context')['state']['concept'], 'C01')

if __name__ == '__main__': unittest.main()
