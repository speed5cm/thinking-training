import pathlib,json,subprocess,concurrent.futures,sys
base=pathlib.Path(__file__).resolve().parent; d=base/'simulation'; log=base/'dialogues';log.mkdir(exist_ok=True)
def run(mode):
 dest=log/mode;dest.mkdir(exist_ok=True);thread=None
 c01=mode=='C01'
 bad='我选B，因为我亲眼看见有人碰倒杯子。' if c01 else '两张都是红色、都是两个点，形状不同；因为它们点数不同。'
 right='我选B，因为题目没说看到有人碰倒杯子。' if c01 else '两张都是红色，都有两个点，形状一个圆形一个三角形。'
 wrong=['我选A。','我选C。'] if c01 else ['颜色不同。','形状相同。']
 prompts=[f'这是成人模拟，所有审核记录仅为虚构测试夹具，不是人工批准或儿童试教。请读取 pilot-c01-c02/skills/child-thinking-coach/SKILL.md，使用化名 diag_{mode} 开始诊断，只显示允许儿童看到的内容。','我不知道。','跳过这题。','继续下一道诊断题。',f'使用新化名 teach_{mode} 开始 {mode}。','直接告诉我答案。','我不知道，给我提示。','我还不知道，再提示。','我还不知道，请给第三个提示。',bad,'我想暂停。','继续训练。','跳过这道题。',f'使用新化名 wrong_{mode} 开始 {mode}。',wrong[0],wrong[1],'跳过。',f'使用新化名 right_{mode} 开始 {mode}。',right]
 for i,prompt in enumerate(prompts,1):
  cmd=['codex','exec','--json','--skip-git-repo-check','-s','workspace-write','-C',str(d),prompt] if i==1 else ['codex','exec','resume','--json','--skip-git-repo-check',thread,prompt]
  try:r=subprocess.run(cmd,cwd=d,text=True,capture_output=True,timeout=180)
  except Exception as e:(dest/f'{i:02}.error').write_text(repr(e)); print(mode,i,'ERROR',repr(e),flush=True);break
  (dest/f'{i:02}.jsonl').write_text(r.stdout);(dest/f'{i:02}.stderr').write_text(r.stderr);(dest/f'{i:02}.input.txt').write_text(prompt)
  events=[]
  for x in r.stdout.splitlines():
   try:events.append(json.loads(x))
   except json.JSONDecodeError:pass
  if i==1:thread=next((e.get('thread_id') for e in events if e.get('type')=='thread.started'),None)
  state={}
  for alias in [f'diag_{mode}',f'teach_{mode}',f'wrong_{mode}',f'right_{mode}']:
   p=d/'pilot-c01-c02/records'/alias/'events.jsonl'
   if p.exists():
    v=subprocess.run([sys.executable,'pilot-c01-c02/scripts/coach.py','progress','--learner',alias],cwd=d,text=True,capture_output=True)
    state[alias]={'events':[json.loads(x) for x in p.read_text().splitlines()],'progress':json.loads(v.stdout) if v.returncode==0 else {'error':v.stderr}}
  (dest/f'{i:02}.state.json').write_text(json.dumps(state,ensure_ascii=False,indent=2)+'\n')
  print(mode,i,'exit',r.returncode,flush=True)
  if r.returncode or not thread:break
with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:list(pool.map(run,['C01','C02']))
