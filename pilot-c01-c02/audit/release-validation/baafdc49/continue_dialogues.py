import json, pathlib, subprocess, sys, concurrent.futures
base=pathlib.Path(__file__).resolve().parent/'dialogues'
d=pathlib.Path('/tmp/thinking-release-baafdc49')
def run(mode):
 dest=base/mode
 thread=next(json.loads(x)['thread_id'] for x in (dest/'01.jsonl').read_text().splitlines() if json.loads(x).get('type')=='thread.started')
 prompts=[f'切换回化名 diag_{mode} 的诊断会话，回答当前题：形状都是圆形，颜色一个红色一个蓝色。',f'使用新化名 end_{mode} 开始 {mode}。','我想现在结束会话。']
 for n,prompt in enumerate(prompts,22):
  r=subprocess.run(['codex','exec','resume','--json','--skip-git-repo-check',thread,prompt],cwd=d,text=True,capture_output=True,timeout=180)
  (dest/f'{n:02}.input.txt').write_text(prompt);(dest/f'{n:02}.jsonl').write_text(r.stdout);(dest/f'{n:02}.stderr').write_text(r.stderr)
  state={}
  for alias in [f'diag_{mode}',f'teach_{mode}',f'wrong_{mode}',f'right_{mode}',f'end_{mode}']:
   p=d/'pilot-c01-c02/records'/alias/'events.jsonl'
   if p.exists():
    v=subprocess.run([sys.executable,'pilot-c01-c02/scripts/coach.py','progress','--learner',alias],cwd=d,text=True,capture_output=True)
    state[alias]={'events':[json.loads(x) for x in p.read_text().splitlines()],'progress':json.loads(v.stdout) if v.returncode==0 else {'error':v.stderr}}
  (dest/f'{n:02}.state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
  print(mode,n,'exit',r.returncode,flush=True)
  if r.returncode:break
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,['C01','C02']))
