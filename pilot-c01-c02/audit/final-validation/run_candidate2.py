import pathlib,json,subprocess,sys
base=pathlib.Path(__file__).resolve().parent;d=pathlib.Path('/tmp/child-candidate-2');o=base/'candidate-2-dialogue';o.mkdir(exist_ok=True)
prompts=['这是仅有虚构审核记录的成人模拟，不是家长批准。工作目录 /tmp/child-candidate-2，请读取该目录的 pilot-c01-c02/skills/child-thinking-coach/SKILL.md，化名 diag_fix 开始诊断。','我不知道。','跳过这题。','继续下一道诊断题。']
thread=None
for n,prompt in enumerate(prompts,1):
 cmd=['codex','exec','--json','--skip-git-repo-check','-s','workspace-write','-C',str(d),prompt] if n==1 else ['codex','exec','resume','--json','--skip-git-repo-check',thread,prompt]
 r=subprocess.run(cmd,cwd=d,text=True,capture_output=True,timeout=180);(o/f'{n:02}.jsonl').write_text(r.stdout);(o/f'{n:02}.input.txt').write_text(prompt);(o/f'{n:02}.stderr').write_text(r.stderr)
 es=[json.loads(x) for x in r.stdout.splitlines() if x.strip()];thread=thread or next((x['thread_id'] for x in es if x.get('type')=='thread.started'),None)
 p=d/'pilot-c01-c02/records/diag_fix/events.jsonl';(o/f'{n:02}.state.json').write_text(p.read_text() if p.exists() else '')
 print(n,r.returncode,flush=True)
 if r.returncode or not thread:break
