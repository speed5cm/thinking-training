"""End-to-end transition tests in disposable, explicitly synthetic project copies."""
import fcntl
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time
import unittest

import test_dynamic_candidate as dynamic_fixture
from concept_authorization_fixture import write_c02_authorization

ROOT = Path(__file__).resolve().parents[1]

class DynamicTransition(unittest.TestCase):
    def setUp(self):
        self.fixture = dynamic_fixture.DynamicCandidate('test_ready_and_recomputed_correction_invalidation')
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        self.folder = self.fixture.folder
        target = self.root / 'experiments/sigma-integration/formal_gate.py'
        target.parent.mkdir(parents=True)
        shutil.copy(ROOT / 'experiments/sigma-integration/formal_gate.py', target)
        write_c02_authorization(self.root)
        self.fixture.build()
        self.assertTrue(self.fixture.result()['candidate'])

    def run_cli(self, path, *args, ok=True):
        result = subprocess.run([sys.executable, str(self.root / path), *args], cwd=self.root,
                                text=True, capture_output=True, timeout=20)
        if ok: self.assertEqual(result.returncode, 0, result.stderr)
        else: self.assertNotEqual(result.returncode, 0, result.stdout)
        return result

    def evidence(self, action, *args, ok=True):
        return self.run_cli('scripts/learning_evidence.py', action, '--learner', 'synthetic', *args, ok=ok)

    def coach(self, action, *args, ok=True):
        return self.run_cli('pilot-c01-c02/scripts/coach.py', action, '--learner', 'synthetic', *args, ok=ok)

    def gate(self, action='check', ok=True):
        return self.run_cli('experiments/sigma-integration/formal_gate.py', action, '--learner', 'synthetic', '--concept', 'C02', ok=ok)

    def confirm(self):
        return json.loads(self.evidence('confirm-c01', '--synthetic-confirmation').stdout)

    def plan(self):
        context = json.loads(self.run_cli('scripts/validate_personal_roadmap.py', 'context', '--learner', 'synthetic').stdout)
        plan = json.loads((self.root / 'examples/ai-roadmap/fiction-plan.json').read_text())
        plan['learner'] = 'synthetic'
        for key in ('curriculum_digest','learner_digest','evidence_digest'): plan[key] = context[key]
        path = self.folder / 'candidate.json'; path.write_text(json.dumps(plan, ensure_ascii=False))
        pending = json.loads(self.run_cli('scripts/sigma_plan_store.py', 'prepare', '--learner', 'synthetic', '--plan', str(path)).stdout)
        self.run_cli('scripts/sigma_plan_store.py', 'publish', '--learner', 'synthetic', '--plan', str(path), '--confirmed-sha', pending['plan_sha256'], ok=False)
        return json.loads(self.run_cli('scripts/sigma_plan_store.py', 'publish', '--learner', 'synthetic', '--plan', str(path), '--confirmed-sha', pending['plan_sha256'], '--synthetic-confirmation').stdout)

    def ready(self):
        self.confirm(); self.plan()

    def test_complete_chain_and_direct_use(self):
        self.evidence('confirm-c01', ok=False)
        self.gate(ok=False); self.coach('start','--mode','C02',ok=False)
        self.coach('start','--mode','diagnosis'); self.coach('show'); self.coach('skip')
        self.coach('show', ok=False)  # The C02 diagnosis card cannot bypass the gate.
        self.coach('end')
        (self.root/'pilot-c01-c02/cards/ST-C01-01.json').unlink()  # Dynamic C01 has no fixed-card prerequisite.
        result = self.confirm(); self.assertEqual(result['confirmation'], 'synthetic_simulation')
        self.coach('start','--mode','C02',ok=False)  # A valid candidate and confirmation still need a current plan.
        self.plan(); self.gate(); self.coach('start','--mode','C02'); self.coach('show')
        review = self.root / 'pilot-c01-c02/reviews/ST-C02-01@1.1.0.json'
        original = review.read_text(); review.unlink()
        self.coach('show', ok=False)
        review.write_text(original)
        self.coach('attempt','--response','合成回答','--correctness','correct','--explanation','valid')

    def test_replay_and_evidence_correction(self):
        self.ready()
        path = self.folder / 'mastery-confirmation.json'
        current = path.read_text()
        module = self.root / 'scripts/learning_evidence.py'
        source = module.read_text()
        module.write_text(source.replace("DYNAMIC_RULE_VERSION = 'C01-dynamic-candidate-v1'", "DYNAMIC_RULE_VERSION = 'C01-dynamic-candidate-v2'") + '\n# changed rule fixture\n')
        self.gate(ok=False); self.coach('start','--mode','C02',ok=False)
        module.write_text(source)
        path.write_text(json.dumps({'concept':'C01','confirmation':'parent','evidence_digest':self.fixture.result()['evidence_digest']}))
        self.gate(ok=False); self.coach('start','--mode','C02',ok=False)
        path.write_text(current)
        replacement = self.fixture.assessment('q3', novel='no', accuracy='not_supported')
        self.fixture.commit([self.fixture.ev('correction','q3',event_id='correction-1',reason='合成重新评价',replacement=replacement)])
        self.assertFalse(self.fixture.result()['candidate'])
        self.gate(ok=False); self.coach('start','--mode','C02',ok=False)
        self.assertEqual(json.loads(self.run_cli('scripts/sigma_plan_store.py','status','--learner','synthetic').stdout)['status'],'stale')

    def test_authorization_wiki_and_prerequisite_fail_closed(self):
        self.ready()
        auth = self.root / 'pilot-c01-c02/concept-authorizations/C02.json'
        original = auth.read_text()
        self.run_cli('scripts/concept_authorization.py', 'revoke', '--concept', 'C02')
        self.gate(ok=False); self.coach('start','--mode','C02',ok=False)
        self.assertEqual(json.loads(self.run_cli('scripts/sigma_plan_store.py','status','--learner','synthetic').stdout)['status'],'stale')
        auth.write_text(original)
        forged = json.loads(original); forged['review']['kind'] = 'human'; auth.write_text(json.dumps(forged))
        self.coach('start','--mode','C02',ok=False)
        auth.write_text(original)
        page = self.root / 'wiki/concepts/attribute-comparison.md'; old = page.read_text(); page.write_text(old+'\n<!-- changed -->\n')
        self.gate(ok=False); self.coach('start','--mode','C02',ok=False)
        page.write_text(old)
        # Contradict the hard prerequisite metadata; Wiki consistency validation must block.
        page.write_text(old.replace('"C01"', '"C03"'))
        write_c02_authorization(self.root, version='synthetic-c02-2')
        self.coach('start','--mode','C02',ok=False)

    def test_c01_revocation_and_real_learner_block(self):
        self.ready()
        self.run_cli('scripts/concept_authorization.py', 'revoke', '--concept', 'C01')
        self.coach('start','--mode','C02',ok=False); self.gate(ok=False)
        self.run_cli('pilot-c01-c02/scripts/coach.py','start','--learner','real-child','--mode','C02',ok=False)
        self.run_cli('pilot-c01-c02/scripts/coach.py','start','--learner','real-child','--mode','C01',ok=False)
        self.run_cli('scripts/learning_evidence.py','confirm-c01','--learner','real-child','--synthetic-confirmation',ok=False)

    def test_concurrent_valid_starts_are_serialized(self):
        self.ready()
        command = [sys.executable, str(self.root/'pilot-c01-c02/scripts/coach.py'), 'start', '--learner', 'synthetic', '--mode', 'C02']
        processes = [subprocess.Popen(command, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True) for _ in range(2)]
        output = [p.communicate(timeout=20) for p in processes]
        self.assertEqual(sorted(p.returncode for p in processes), [0,1], output)

    def test_concurrent_change_is_rechecked_inside_lock(self):
        self.ready()
        snapshot_path = self.folder / 'sigma/session-snapshot.json'
        command = [sys.executable, str(self.root/'pilot-c01-c02/scripts/coach.py'), 'start', '--learner', 'synthetic', '--mode', 'C02']
        with (self.folder / '.lock').open('a') as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            process = subprocess.Popen(command, cwd=self.root, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
            try:
                time.sleep(0.5)
                self.assertIsNone(process.poll(), '入口未等待学习者锁')
                # While start is blocked on the learner lock, append a valid invalidation.
                snapshot = json.loads(snapshot_path.read_text())
                q3 = next(e for e in snapshot['turns'] if e.get('question_id') == 'q3' and e['type'] == 'question')
                snapshot['turns'].append({'type':'invalidation','session_id':q3['session_id'], 'question_id':'q3',
                    'event_id':'concurrent-invalidation','reason':'合成并发更正','recorded_at':snapshot['turns'][-1]['recorded_at']})
                snapshot['revision'] += 1
                temp = snapshot_path.with_suffix('.tmp'); temp.write_text(json.dumps(snapshot,ensure_ascii=False)); os.replace(temp,snapshot_path)
            finally:
                fcntl.flock(lock, fcntl.LOCK_UN)
            out, err = process.communicate(timeout=20)
        self.assertNotEqual(process.returncode, 0, (out,err))
        self.assertFalse((self.folder/'events.jsonl').exists())

if __name__ == '__main__': unittest.main()
