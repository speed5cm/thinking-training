import copy
import hashlib
import time
import datetime as dt
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import sigma_plan_store as plans
import validate_personal_roadmap as planner

class GateIntegration(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.root=Path(self.tmp.name)/'project'
        shutil.copytree(ROOT,self.root,ignore=shutil.ignore_patterns('records','__pycache__','.git','experiments'))
        self.script=self.root/'pilot-c01-c02/scripts/coach.py'
    def call(self,*args):
        return subprocess.run([sys.executable,str(self.script),*args],text=True,capture_output=True)
    def test_direct_c02_is_blocked_but_diagnosis_is_separate(self):
        result=self.call('start','--learner','synthetic','--mode','C02')
        self.assertNotEqual(result.returncode,0);self.assertIn('证据不足',result.stderr)
        self.assertFalse((self.root/'pilot-c01-c02/records/synthetic/events.jsonl').exists())
        self.assertEqual(self.call('start','--learner','synthetic','--mode','diagnosis').returncode,0)
    def test_synthetic_valid_confirmation_and_stale_confirmation(self):
        # Synthetic, isolated second C01 card and simulated parent confirmation only.
        src=self.script.read_text().replace("'C01': ['ST-C01-01']", "'C01': ['ST-C01-01', 'SYN-C01-02']")
        self.script.write_text(src)
        pilot=self.root/'pilot-c01-c02'; cards=pilot/'cards'
        card=json.loads((cards/'ST-C01-01.json').read_text());card['id']='SYN-C01-02'
        path=cards/'SYN-C01-02.json';path.write_text(json.dumps(card,ensure_ascii=False,indent=2)+'\n')
        digest=hashlib.sha256(path.read_bytes()).hexdigest()
        registry=json.loads((cards/'versions.json').read_text());registry['SYN-C01-02']={card['version']:digest};(cards/'versions.json').write_text(json.dumps(registry))
        archive=cards/'archive/SYN-C01-02';archive.mkdir();shutil.copy(path,archive/(card['version']+'.json'))
        review=json.loads((pilot/'reviews/ST-C01-01@1.1.0.json').read_text());review.update(card_id='SYN-C01-02',content_sha256=digest)
        for t in review['transitions']: t['actor']='SYNTHETIC_TEST_ONLY'
        (pilot/'reviews/SYN-C01-02@1.1.0.json').write_text(json.dumps(review))
        folder=pilot/'records/synthetic';folder.mkdir(parents=True)
        def record(sid,q,sha):
            return {'concept':'C01','session_id':sid,'card':{'id':q,'version':'1.1.0','sha256':sha},'ai_temporary_correctness':'correct','explanation_quality':'valid','raw_response':'因为有证据','reason_quote':'因为有证据','hint_level':0,'prior_attempts':0,'prior_support':[],'transfer':{'status':'yes','parent_verified_novel':True,'observation':'SYNTHETIC'}}
        sha1=hashlib.sha256((cards/'ST-C01-01.json').read_bytes()).hexdigest()
        records=[record('fake-1','ST-C01-01',sha1),record('fake-2','SYN-C01-02',digest)]
        (folder/'evidence.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False)+'\n' for r in records))
        evidence_sha=hashlib.sha256(json.dumps(records,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()
        confirmation={'concept':'C01','confirmation':'parent','evidence_digest':evidence_sha,'fixture':'SIMULATED ONLY'}
        (folder/'mastery-confirmation.json').write_text(json.dumps(confirmation))
        result=self.call('start','--learner','synthetic','--mode','C02')
        self.assertEqual(result.returncode,0,result.stderr)
        confirmation['evidence_digest']='stale';(folder/'mastery-confirmation.json').write_text(json.dumps(confirmation))
        self.assertNotEqual(self.call('show','--learner','synthetic').returncode,0)

    def test_release_lock_serializes_revoke_and_start(self):
        pilot=self.root/'pilot-c01-c02';ready=pilot/'fixture-ready';release=pilot/'fixture-release'
        program="import fcntl,pathlib,time; p=pathlib.Path(%r); f=(p/'.publication.lock').open('a'); fcntl.flock(f,fcntl.LOCK_EX); (p/'fixture-ready').touch();\nwhile not (p/'fixture-release').exists(): time.sleep(.01)\n(p/'reviews/ST-C01-01@1.1.0.json').unlink()" % str(pilot)
        writer=subprocess.Popen([sys.executable,'-c',program]);self.addCleanup(lambda: writer.kill() if writer.poll() is None else None)
        deadline=time.monotonic()+5
        while not ready.exists() and time.monotonic()<deadline: time.sleep(.01)
        self.assertTrue(ready.exists())
        proc=subprocess.Popen([sys.executable,str(self.script),'start','--learner','synthetic','--mode','C01'],stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True)
        time.sleep(.15);self.assertIsNone(proc.poll())
        release.touch();writer.wait(timeout=5);out,err=proc.communicate(timeout=5)
        self.assertNotEqual(proc.returncode,0,(out,err))

    def test_wiki_change_stales_real_stored_plan(self):
        folder=self.root/'pilot-c01-c02/records/fiction-demo';folder.mkdir(parents=True)
        script=self.root/'scripts/validate_personal_roadmap.py'
        output=subprocess.run([sys.executable,str(script),'context','--learner','fiction-demo'],text=True,capture_output=True,check=True)
        ctx=json.loads(output.stdout); plan=json.loads((self.root/'examples/ai-roadmap/fiction-plan.json').read_text())
        for key in ('curriculum_digest','evidence_digest','learner_digest'): plan[key]=ctx[key]
        candidate=folder/'candidate.json';candidate.write_text(json.dumps(plan,ensure_ascii=False))
        store=self.root/'scripts/sigma_plan_store.py'
        command=[sys.executable,str(store),'publish','--learner','fiction-demo','--plan',str(candidate)]
        self.assertEqual(subprocess.run(command,text=True,capture_output=True).returncode,0)
        page=self.root/'wiki/concepts/observation-vs-inference.md'
        with page.open('a') as f: f.write('\n<!-- SYNTHETIC revision -->\n')
        output=subprocess.run([sys.executable,str(store),'status','--learner','fiction-demo'],capture_output=True,text=True,check=True)
        self.assertEqual(json.loads(output.stdout)['status'],'stale')

    def test_duplicate_start_and_live_release_revocation(self):
        self.assertEqual(self.call('start','--learner','synthetic','--mode','C01').returncode,0)
        self.assertNotEqual(self.call('start','--learner','synthetic','--mode','C01').returncode,0)
        (self.root/'pilot-c01-c02/reviews/ST-C01-01@1.1.0.json').unlink()
        self.assertNotEqual(self.call('show','--learner','synthetic').returncode,0)

class PlanHistory(unittest.TestCase):
    def test_version_staleness_and_due_queue(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder=Path(tmp); plan=json.loads((ROOT/'examples/ai-roadmap/fiction-plan.json').read_text())
            ctx={'curriculum':planner.base.build(), 'curriculum_digest':plan['curriculum_digest'], 'evidence_digest':plan['evidence_digest'], 'learner_digest':plan['learner_digest'], 'current_recommendation':{}}
            candidate=folder/'proposal.json';candidate.write_text(json.dumps(plan))
            records=[{'concept':'C01','session_id':'fictional-1','captured_at':(dt.datetime.now(dt.timezone.utc)-dt.timedelta(days=2)).isoformat()}]
            with mock.patch.object(plans.evidence,'get_folder',return_value=folder), mock.patch.object(plans.evidence,'load_evidence',return_value=records), mock.patch.object(plans.planner,'context',return_value=ctx):
                a=plans.operate('publish','fiction-demo',candidate)
                b=plans.operate('publish','fiction-demo',candidate)
                self.assertEqual((a['version'],b['version']),(1,2));self.assertTrue(b['review_queue'][0]['due'])
                self.assertEqual(plans.operate('status','fiction-demo')['review_queue'][0]['evidence_session'],'fictional-1')
                with mock.patch.object(plans.planner,'context',return_value={**ctx,'evidence_digest':'changed'}):
                    self.assertEqual(plans.operate('status','fiction-demo')['status'],'stale')
                second={'concept':'C01','session_id':'fictional-2','captured_at':dt.datetime.now(dt.timezone.utc).isoformat()}
                with mock.patch.object(plans.evidence,'load_evidence',return_value=records+[second]):
                    out=plans.operate('complete-review','fiction-demo',session='fictional-2')
                    self.assertEqual(out['review_queue'][0]['status'],'completed')
                    with self.assertRaises(plans.Invalid): plans.operate('complete-review','fiction-demo',session='fictional-2')
