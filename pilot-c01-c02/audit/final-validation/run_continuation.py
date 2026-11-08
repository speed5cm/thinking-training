import pathlib,json,subprocess,concurrent.futures,sys
base=pathlib.Path(__file__).resolve().parent;d=pathlib.Path('/tmp/child-candidate-2');log=base/'dialogues-v3-continuation';log.mkdir(exist_ok=True)
def run(mode):
 dest=log/mode;dest.mkdir(exist_ok=True);source=base/'dialogues-v3'/mode/'01.jsonl';thread=next(x['thread_id'] for x in map(json.loads,source.read_text().splitlines()) if x.get('type')=='thread.started')
 c01=mode=='C01'; wrong=['我选A。','我选C。'] if c01 else ['颜色不同。','形状相同。'];right='我选B，因为题目没说看到有人碰倒杯子。' if c01 else '两张都是红色，都有两个点，形状一个圆形一个三角形。'
 prompts=['继续训练。','跳过这道题。',f'使用新化名 wrong_{mode} 开始 {mode}。',wrong[0],wrong[1],'跳过。',f'使用新化名 right_{mode} 开始 {mode}。',right]
 for i,prompt in enumerate(prompts,12):
  cmd=['codex','exec','resume','--json','--skip-git-repo-check',thread,prompt]
  try:r=subprocess.run(cmd,cwd=d,text=True,capture_output=True,timeout=180)
  except Exception as e:(dest/f'{i:02}.error').write_text(repr(e));print(mode,i,'ERROR',repr(e),flush=True);break
  (dest/f'{i:02}.jsonl').write_text(r.stdout);(dest/f'{i:02}.stderr').write_text(r.stderr);(dest/f'{i:02}.input.txt').write_text(prompt)
  state={}
  for alias in [f'diag_{mode}',f'teach_{mode}',f'wrong_{mode}',f'right_{mode}']:
   p=d/'pilot-c01-c02/records'/alias/'events.jsonl'
   if p.exists():
    v=subprocess.run([sys.executable,'pilot-c01-c02/scripts/coach.py','progress','--learner',alias],cwd=d,text=True,capture_output=True);state[alias]={'events':[json.loads(x) for x in p.read_text().splitlines()],'progress':json.loads(v.stdout) if v.returncode==0 else {'error':v.stderr}}
  (dest/f'{i:02}.state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n');print(mode,i,'exit',r.returncode,flush=True)
  if r.returncode:break
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,['C01','C02']))
