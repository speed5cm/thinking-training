import pathlib,json,subprocess,sys,concurrent.futures
base=pathlib.Path(__file__).resolve().parent;d=pathlib.Path('/tmp/child-candidate-2');out=base/'dialogues-v3-continuation'
def run(mode):
 p=base/'dialogues-v3'/mode/'01.jsonl';thread=next(x['thread_id'] for x in map(json.loads,p.read_text().splitlines()) if x.get('type')=='thread.started')
 prompt=f'请切换回先前尚未结束的诊断会话 diag_{mode}：两张都是圆形，颜色不一样，甲红乙蓝。'
 r=subprocess.run(['codex','exec','resume','--json','--skip-git-repo-check',thread,prompt],cwd=d,text=True,capture_output=True,timeout=180)
 folder=out/mode;(folder/'20.jsonl').write_text(r.stdout);(folder/'20.input.txt').write_text(prompt);(folder/'20.stderr').write_text(r.stderr)
 states={}
 for alias in [f'diag_{mode}',f'teach_{mode}',f'wrong_{mode}',f'right_{mode}']:
  path=d/'pilot-c01-c02/records'/alias/'events.jsonl'
  if path.exists():
   v=subprocess.run([sys.executable,'pilot-c01-c02/scripts/coach.py','progress','--learner',alias],cwd=d,text=True,capture_output=True);states[alias]={'events':[json.loads(x) for x in path.read_text().splitlines()],'progress':json.loads(v.stdout) if not v.returncode else {'error':v.stderr}}
 (folder/'20.state.json').write_text(json.dumps(states,ensure_ascii=False,indent=2)+'\n');print(mode,r.returncode,flush=True)
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as p:list(p.map(run,['C01','C02']))
