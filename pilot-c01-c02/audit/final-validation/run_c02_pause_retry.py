import pathlib,json,subprocess,sys
b=pathlib.Path(__file__).resolve().parent;d=pathlib.Path('/tmp/child-candidate-2');p=b/'dialogues-v3-continuation/C02';f=b/'dialogues-v3/C02/01.jsonl';thread=next(x['thread_id'] for x in map(json.loads,f.read_text().splitlines()) if x.get('type')=='thread.started')
for n,prompt in enumerate(['使用新化名 pause_C02 开始 C02。','我想暂停。','继续训练。','跳过这道题。'],21):
 r=subprocess.run(['codex','exec','resume','--json','--skip-git-repo-check',thread,prompt],cwd=d,text=True,capture_output=True,timeout=180)
 (p/f'{n:02}.jsonl').write_text(r.stdout);(p/f'{n:02}.stderr').write_text(r.stderr);(p/f'{n:02}.input.txt').write_text(prompt)
 state={}
 for alias in ['diag_C02','teach_C02','wrong_C02','right_C02','pause_C02']:
  path=d/'pilot-c01-c02/records'/alias/'events.jsonl'
  if path.exists():
   v=subprocess.run([sys.executable,'pilot-c01-c02/scripts/coach.py','progress','--learner',alias],cwd=d,text=True,capture_output=True);state[alias]={'events':[json.loads(x) for x in path.read_text().splitlines()],'progress':json.loads(v.stdout) if not v.returncode else {'error':v.stderr}}
 (p/f'{n:02}.state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');print(n,r.returncode,flush=True)
 if r.returncode:break
