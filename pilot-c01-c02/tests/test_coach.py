"""Closed fixed-card entry and retained historical Coach records."""
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / 'pilot-c01-c02'
spec = importlib.util.spec_from_file_location('coach', SOURCE / 'scripts/coach.py')
coach = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coach)

def args(action, learner='synthetic-a', **kw):
    return SimpleNamespace(action=action, learner=learner, **kw)

class CoachTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.parent = Path(self.tmp.name); self.root = self.parent / 'pilot-c01-c02'
        shutil.copytree(SOURCE, self.root, ignore=shutil.ignore_patterns('records', '__pycache__'))
        for name in ('wiki/concepts/observation-vs-inference.md', 'wiki/concepts/attribute-comparison.md', 'question-bank/original-examples.md', 'references/sources.md', 'references/pedagogy.md'):
            dest = self.parent / name; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy(PROJECT / name, dest)
        old = coach.ROOT; coach.ROOT = self.root; self.addCleanup(setattr, coach, 'ROOT', old)

    def seed(self, learner='synthetic-a'):
        folder = coach.learner_dir(learner); folder.mkdir(parents=True)
        q = {'id':'ST-C01-01', 'concept':'C01', 'version':'1.1.0', 'sha256':'historical', 'source':'wiki/sources/project-research.md'}
        coach.append(folder, {'type':'start', 'session_id':learner, 'mode':'C01', 'questions':[q]})
        return folder

    def blocked(self, action, **kw):
        with self.assertRaisesRegex(coach.Stop, '固定题卡训练入口已关闭'):
            coach.run(args(action, **kw))
        self.assertFalse((self.root / 'records/synthetic-a/events.jsonl').exists())

    def test_start_c01_closed(self): self.blocked('start', mode='C01')
    def test_start_c02_closed(self): self.blocked('start', mode='C02')
    def test_diagnosis_closed(self): self.blocked('start', mode='diagnosis')
    def test_show_closed(self): self.blocked('show')
    def test_attempt_closed(self): self.blocked('attempt', response='合成', correctness='correct', explanation='valid')
    def test_hint_closed(self): self.blocked('hint')
    def test_demo_closed(self): self.blocked('demo')
    def test_explain_closed(self): self.blocked('explain', consent=True)
    def test_skip_closed(self): self.blocked('skip')
    def test_complete_closed(self): self.blocked('complete')
    def test_resume_closed(self): self.blocked('resume')

    def test_real_learner_rejected(self):
        with self.assertRaisesRegex(coach.Stop, '真实儿童入口关闭'): coach.run(args('progress', 'real-child'))
    def test_progress_without_history(self): self.assertEqual(coach.run(args('progress'))['status'], 'none')
    def test_progress_reads_history(self):
        self.seed(); result = coach.run(args('progress'))
        self.assertEqual((result['status'], result['current']['id']), ('active', 'ST-C01-01'))
    def test_pause_history(self):
        self.seed(); self.assertEqual(coach.run(args('pause', text='休息'))['status'], 'paused')
        self.assertEqual(coach.run(args('progress'))['status'], 'paused')
    def test_pause_twice_rejected(self):
        self.seed(); coach.run(args('pause', text=''))
        with self.assertRaises(coach.Stop): coach.run(args('pause', text=''))
    def test_end_history(self):
        self.seed(); self.assertEqual(coach.run(args('end', text='结束'))['status'], 'completed')
        self.assertEqual(coach.run(args('progress'))['status'], 'completed')
    def test_end_completed_is_idempotent(self):
        folder = self.seed(); coach.run(args('end', text=''))
        before = coach.load_events(folder); coach.run(args('end', text=''))
        self.assertEqual(coach.load_events(folder), before)
    def test_feedback_preserved_in_summary(self):
        self.seed(); coach.run(args('feedback', text='合成观察'))
        self.assertEqual(coach.run(args('end', text=''))['summary']['parent_feedback'], ['合成观察'])
    def test_histories_are_isolated(self):
        a = self.seed(); b = self.seed('synthetic-b')
        coach.run(args('feedback', text='仅甲'))
        self.assertIn('仅甲', (a / 'events.jsonl').read_text())
        self.assertNotIn('仅甲', (b / 'events.jsonl').read_text())
    def test_append_failure_not_reported_as_pause(self):
        self.seed()
        with patch.object(coach, 'append', side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): coach.run(args('pause', text=''))
        self.assertEqual(coach.run(args('progress'))['status'], 'active')
    def test_concurrent_starts_both_rejected(self):
        cmd = [sys.executable, str(self.root / 'scripts/coach.py'), 'start', '--learner', 'synthetic-a', '--mode', 'C01']
        processes = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        output = [p.communicate(timeout=15) for p in processes]
        self.assertEqual([p.returncode for p in processes], [1, 1], output)
        self.assertFalse((self.root / 'records/synthetic-a/events.jsonl').exists())
    def test_historical_card_change_fails_integrity(self):
        path = coach.card_path('ST-C01-01'); card = json.loads(path.read_text())
        card['stem'] += ' 修改'; path.write_text(json.dumps(card, ensure_ascii=False))
        with self.assertRaises(coach.Stop): coach.load_card('ST-C01-01', 'C01')
    def test_historical_review_cannot_be_ai_approved(self):
        path = self.root / 'reviews/ST-C01-01@1.1.0.json'; review = json.loads(path.read_text())
        review['transitions'][1]['actor_type'] = 'ai'; path.write_text(json.dumps(review))
        with self.assertRaises(coach.Stop): coach.load_card('ST-C01-01', 'C01')

if __name__ == '__main__': unittest.main(verbosity=2)
