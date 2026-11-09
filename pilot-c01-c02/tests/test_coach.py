import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from pathlib import Path
from types import SimpleNamespace

PROJECT = Path(__file__).resolve().parents[2]
SOURCE = PROJECT / 'pilot-c01-c02'
spec = importlib.util.spec_from_file_location('coach', SOURCE / 'scripts' / 'coach.py')
coach = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coach)

def args(action, learner='synthetic-a', **kw):
    return SimpleNamespace(action=action, learner=learner, **kw)

class CoachTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.parent = Path(self.tmp.name)
        self.root = self.parent / 'pilot-c01-c02'
        shutil.copytree(SOURCE, self.root, ignore=shutil.ignore_patterns('records','__pycache__'))
        # 每项测试从未审核状态开始；正式发布记录只保留在源目录。
        for review in (self.root / 'reviews').glob('*@*.json'):
            review.unlink()
        for name in ('wiki/concepts/observation-vs-inference.md','wiki/concepts/attribute-comparison.md','question-bank/original-examples.md','references/sources.md','references/pedagogy.md'):
            dest=self.parent/name; dest.parent.mkdir(parents=True, exist_ok=True); shutil.copy(PROJECT/name,dest)
        coach.ROOT = self.root

    def tearDown(self):
        self.tmp.cleanup()

    def approve_fixture(self, qid):
        card=coach.json_read(coach.card_path(qid))
        entries=[{'state':s,'actor_type':'human','actor':'SIMULATED_TEST_ONLY','time':'2026-11-04T10:00:00+08:00','note':'test fixture, not human approval'} for s in ('verified','approved','published')]
        review={'card_id':qid,'version':card['version'],'content_sha256':coach.digest(coach.card_path(qid)),'transitions':entries}
        (self.root/'reviews'/f"{qid}@{card['version']}.json").write_text(json.dumps(review),encoding='utf-8')

    def start(self, learner='synthetic-a',mode='C01'):
        for q in coach.MODES[mode]: self.approve_fixture(q)
        coach.run(args('start',learner,mode=mode))
        return coach.run(args('show',learner))

    def attempt(self, response='不知道', correct='unknown', explanation='none',learner='synthetic-a'):
        return coach.run(args('attempt',learner,response=response,correctness=correct,explanation=explanation))

    def test_unreviewed_card_is_rejected(self):
        with self.assertRaises(coach.Stop): coach.run(args('start',mode='C01'))
        self.assertFalse((self.root/'records/synthetic-a/events.jsonl').exists())

    def test_real_published_reviews_allow_all_modes(self):
        # 复制正式审核记录到隔离目录，不构造或修改审核内容。
        for review in (SOURCE / 'reviews').glob('*@*.json'):
            shutil.copy2(review, self.root / 'reviews' / review.name)
        for mode in ('diagnosis', 'C01', 'C02'):
            learner = 'synthetic-published_' + mode
            # This test checks published snapshots; authorization has separate tests.
            with patch.object(coach, 'authorize_c02_locked'):
                coach.run(args('start', learner, mode=mode))
                self.assertEqual(coach.run(args('show', learner))['id'], coach.MODES[mode][0])

    def test_direct_c02_without_evidence_is_rejected(self):
        # Use the actual evidence module in an isolated copy, with no authorization mock.
        scripts = self.parent / 'scripts'
        scripts.mkdir()
        for name in ('learning_evidence.py', 'generate_roadmap.py'):
            shutil.copy(PROJECT / 'scripts' / name, scripts / name)
        result = subprocess.run([sys.executable, str(self.root / 'scripts/coach.py'),
                                 'start', '--learner', 'synthetic-a', '--mode', 'C02'],
                                capture_output=True, text=True)
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('C02 授权失败', result.stderr)
        self.assertFalse((self.root / 'records/synthetic-a/events.jsonl').exists())

    def test_concurrent_starts_create_only_one_session(self):
        self.approve_fixture('ST-C01-01')
        command = [sys.executable, str(self.root / 'scripts/coach.py'),
                   'start', '--learner', 'synthetic-a', '--mode', 'C01']
        processes = [subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                                      text=True) for _ in range(2)]
        results = [p.communicate(timeout=10) for p in processes]
        self.assertEqual(sorted(p.returncode for p in processes), [0, 1], results)
        events = coach.load_events(self.root / 'records/synthetic-a')
        self.assertEqual(sum(e['type'] == 'start' for e in events), 1)

    def test_ai_cannot_approve(self):
        self.approve_fixture('ST-C01-01')
        p=self.root/'reviews/ST-C01-01@1.1.0.json'; x=json.loads(p.read_text()); x['transitions'][1]['actor_type']='ai'; p.write_text(json.dumps(x))
        with self.assertRaises(coach.Stop): coach.run(args('start',mode='C01'))

    def test_changed_card_cannot_use_old_approval_or_same_version(self):
        self.start(); p=coach.card_path('ST-C01-01'); c=json.loads(p.read_text()); c['hints'][2]='修改的提示'; p.write_text(json.dumps(c,ensure_ascii=False))
        with self.assertRaises(coach.Stop): coach.run(args('show'))
        self.approve_fixture('ST-C01-01')
        with self.assertRaises(coach.Stop): coach.run(args('show'))

    def test_h3_does_not_disclose_complete_answer_for_selected_cards(self):
        for qid in coach.MODES['C01']+coach.MODES['C02']:
            c=coach.json_read(coach.card_path(qid))
            self.assertNotIn(c['answer'], c['hints'][2])
        self.start(); self.attempt()
        hints=[coach.run(args('hint'))['hint'] for _ in range(3)]
        self.assertFalse('A、C' in hints[2] or '剩下' in hints[2])
        with self.assertRaises(coach.Stop): coach.run(args('hint'))

    def test_correct_answer_wrong_explanation_does_not_mark_mastery(self):
        self.start(); self.attempt('B，因为水迹证明碰倒了', 'correct','invalid')
        e=coach.load_events(coach.learner_dir('synthetic-a'))[-1]
        self.assertEqual(e['raw_response'],'B，因为水迹证明碰倒了')
        self.assertEqual(e['ai_assessment'],{'correctness':'correct','explanation':'invalid'})
        self.assertNotIn('mastered',json.dumps(e))

    def test_two_consecutive_wrong_then_stop(self):
        self.start(); self.attempt('A','incorrect','invalid'); out=self.attempt('C','incorrect','invalid')
        self.assertIn('暂停',out['message'])
        with self.assertRaises(coach.Stop): self.attempt('B','correct','valid')
        demo=coach.run(args('demo')); self.assertIn('平行',coach.load_events(coach.learner_dir('synthetic-a'))[-1]['kind'].replace('parallel','平行'))
        self.assertIn('parallel_demo',demo)

    def test_dont_know_allows_hint_or_pause(self):
        self.start(); self.attempt(); self.assertEqual(coach.run(args('hint'))['level'],1)
        self.assertEqual(coach.run(args('pause',text='休息'))['status'],'paused')

    def test_no_hint_or_demo_before_attempt(self):
        self.start()
        for action in ('hint','demo'):
            with self.assertRaises(coach.Stop): coach.run(args(action))

    def test_pause_resume_restores_question_and_hint_count(self):
        self.start(); self.attempt(); coach.run(args('hint')); coach.run(args('pause',text=''))
        with self.assertRaises(coach.Stop): coach.run(args('show'))
        result=coach.run(args('resume')); self.assertEqual(result['current_question'],'ST-C01-01')
        self.assertEqual(coach.run(args('hint'))['level'],2)

    def test_new_process_resume_from_disk(self):
        self.start(); self.attempt(); coach.run(args('hint')); coach.run(args('pause',text=''))
        script=self.root/'scripts/coach.py'
        proc=subprocess.run([sys.executable,str(script),'resume','--learner','synthetic-a'],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['current_question'],'ST-C01-01')
        proc=subprocess.run([sys.executable,str(script),'hint','--learner','synthetic-a'],capture_output=True,text=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout)['level'],2)

    def test_missing_wiki_or_broken_links_stop(self):
        self.approve_fixture('ST-C01-01')
        (self.root/'wiki/concepts/C01.md').unlink()
        with self.assertRaises(coach.Stop): coach.run(args('start',mode='C01'))
        shutil.copy(SOURCE/'wiki/concepts/C01.md',self.root/'wiki/concepts/C01.md')
        with (self.root/'wiki/concepts/C01.md').open('a') as f: f.write('\n[[concepts/missing]]\n')
        with self.assertRaises(coach.Stop): coach.run(args('start',mode='C01'))

    def test_missing_source_stops_on_resume(self):
        self.start(); coach.run(args('pause',text=''))
        (self.parent/'references/sources.md').unlink()
        with self.assertRaises(coach.Stop): coach.run(args('resume'))

    def test_children_isolated_and_parent_feedback_preserved(self):
        self.start('synthetic-a'); self.attempt('答案甲','correct','valid','synthetic-a')
        self.start('synthetic-b'); self.attempt('答案乙','incorrect','invalid','synthetic-b')
        coach.run(args('feedback','synthetic-a',text='家长观察：愿意画图'))
        result=coach.run(args('end','synthetic-a',text='结束'))
        self.assertEqual(result['summary']['parent_feedback'],['家长观察：愿意画图'])
        a=(self.root/'records/synthetic-a/events.jsonl').read_text(); b=(self.root/'records/synthetic-b/events.jsonl').read_text()
        self.assertNotIn('答案乙',a); self.assertNotIn('答案甲',b)
        self.assertEqual(coach.run(args('progress','synthetic-b'))['status'],'active')

    def test_diagnosis_one_question_at_a_time_and_skip(self):
        out=self.start(mode='diagnosis'); self.assertEqual(out['id'],'PILOT-DIAG-C01')
        coach.run(args('skip'))
        with patch.object(coach, 'authorize_c02_locked'):
            out=coach.run(args('show')); self.assertEqual(out['id'],'PILOT-DIAG-C02')
            self.attempt('圆形一样，颜色不同','correct','valid'); coach.run(args('complete'))
        self.assertIsNone(coach.run(args('progress'))['current'])

    def test_skip_final_completed_and_idempotent(self):
        self.start(); result=coach.run(args('skip')); self.assertEqual(result['status'],'completed')
        self.assertEqual(coach.run(args('progress'))['status'],'completed')
        count=len(coach.load_events(coach.learner_dir('synthetic-a')))
        self.assertEqual(coach.run(args('skip'))['status'],'completed')
        self.assertEqual(len(coach.load_events(coach.learner_dir('synthetic-a'))),count)

    def test_correct_and_explained_final_answer_completes(self):
        self.start()
        out=self.attempt('B，题目没有展示发生的过程','correct','valid')
        self.assertEqual(out['status'],'completed')
        self.assertEqual(coach.run(args('progress'))['status'],'completed')
        self.assertEqual(out['summary']['completed'],1)

    def test_complete_final_completed_and_idempotent(self):
        self.start(); self.attempt('B', 'correct','invalid')
        self.assertEqual(coach.run(args('complete'))['status'],'completed')
        events=coach.load_events(coach.learner_dir('synthetic-a'))
        self.assertEqual(coach.run(args('complete'))['status'],'completed')
        self.assertEqual(coach.load_events(coach.learner_dir('synthetic-a')),events)
        self.assertNotIn('mastered',json.dumps(events))

    def test_failed_persistence_never_returns_completed(self):
        self.start()
        with patch.object(coach,'append',side_effect=OSError('disk failure')):
            with self.assertRaises(OSError): coach.run(args('skip'))
        self.assertEqual(coach.run(args('progress'))['status'],'active')

    def test_new_version_cannot_reuse_old_approval(self):
        p=self.root/'reviews/ST-C01-01@1.0.0.json'
        p.write_text(json.dumps({'card_id':'ST-C01-01','version':'1.0.0','content_sha256':'old','transitions':[]}))
        with self.assertRaises(coach.Stop): coach.run(args('start',mode='C01'))

    def test_explanation_requires_consent_and_sufficient_attempts_and_records_support(self):
        self.start(); self.attempt()
        with self.assertRaises(coach.Stop): coach.run(args('explain',consent=True))
        self.attempt('不确定','unknown','none')
        with self.assertRaises(coach.Stop): coach.run(args('explain',consent=False))
        out=coach.run(args('explain',consent=True)); self.assertEqual(out['support'],'full_explanation')
        self.assertEqual(coach.load_events(coach.learner_dir('synthetic-a'))[-1]['type'],'final_explanation')

    def test_direct_answer_request_policy_exists_but_is_not_runtime_behavior(self):
        skill=(self.root/'skills/child-thinking-coach/SKILL.md').read_text()
        self.assertIn('孩子明确要答案时，不公布当题答案',skill)

if __name__ == '__main__': unittest.main(verbosity=2)
