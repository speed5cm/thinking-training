#!/usr/bin/env python3
"""File-based, parent-supervised C01/C02 prototype. Never approves cards."""
import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import sys

ROOT = Path(__file__).resolve().parents[1]
MODES = {'diagnosis': ['PILOT-DIAG-C01', 'PILOT-DIAG-C02'], 'C01': ['ST-C01-01'], 'C02': ['ST-C02-01']}
PATTERN = re.compile(r'^[A-Za-z0-9_-]{1,40}$')

class Stop(Exception):
    pass

def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read_text(path):
    try:
        if not path.is_file():
            raise Stop(f'必需文件缺失: {path}')
        return path.read_text(encoding='utf-8')
    except (OSError, UnicodeError) as exc:
        raise Stop(f'无法读取: {path}: {exc}') from exc

def json_read(path):
    try:
        return json.loads(read_text(path))
    except (json.JSONDecodeError, ValueError) as exc:
        raise Stop(f'JSON 无效: {path}') from exc

def stamp():
    return dt.datetime.now(dt.timezone.utc).isoformat()

def card_path(qid):
    if not PATTERN.fullmatch(qid):
        raise Stop('题目 ID 无效')
    return ROOT / 'cards' / (qid + '.json')

def gate(concept):
    """Read survey, concept and source in full; check all declared wiki links."""
    if concept not in ('C01', 'C02'):
        raise Stop('概念不在试点范围')
    wiki = ROOT / 'wiki'
    overview, index = read_text(wiki / 'overview.md'), read_text(wiki / 'index.md')
    for c in ('C01', 'C02'):
        if f'concepts/{c}.md' not in index or '(Teaching Concept)' not in index:
            raise Stop(f'索引缺少教学概念 {c}')
    required = [wiki / 'overview.md', wiki / 'index.md', wiki / 'concepts' / (concept + '.md'), wiki / 'sources' / 'project-research.md']
    for page in required:
        content = read_text(page)
        for link in re.findall(r'\[\[([^\]|#]+)', content):
            target = (wiki / (link + '.md')).resolve()
            if not target.is_relative_to(wiki.resolve()):
                raise Stop('Wiki 链接越界')
            read_text(target)
        for link in re.findall(r'\]\(([^)#]+\.md)\)', content):
            target = (page.parent / link).resolve()
            if not target.is_relative_to(wiki.resolve()):
                raise Stop('Wiki 链接越界')
            read_text(target)
    source = required[-1]
    for link in re.findall(r'`([^`]+\.md)`', read_text(source)):
        target = (source.parent / link).resolve()
        if not target.is_relative_to(ROOT.parent.resolve()):
            raise Stop('来源越界')
        read_text(target)
    return [{'path': str(p.relative_to(ROOT)), 'sha256': digest(p)} for p in required]

def load_card(qid, concept=None, version=None):
    path = card_path(qid)
    if version is not None:
        if not isinstance(version, str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', version) or '..' in version:
            raise Stop('题卡版本无效')
        path = ROOT / 'cards' / 'archive' / qid / (version + '.json')
    card = json_read(path)
    required = ('id','version','concept','lesson','age','difficulty','stem','answer','explanation','hints','common_errors','source','parallel_demo','status')
    if any(k not in card for k in required) or card['id'] != qid or card['status'] != 'draft':
        raise Stop('题卡格式不完整')
    if card['concept'] not in ('C01','C02') or (concept and card['concept'] != concept):
        raise Stop('概念不匹配')
    if version is not None and card['version'] != version:
        raise Stop('归档题卡版本不匹配')
    if not isinstance(card['hints'], list) or len(card['hints']) != 3 or any(not isinstance(x,str) or not x.strip() for x in card['hints']):
        raise Stop('题卡必须有三个提示')
    if card['source'] != 'wiki/sources/project-research.md':
        raise Stop('未知来源引用')
    if not isinstance(card['parallel_demo'], dict) or not card['parallel_demo'].get('stem') or not card['parallel_demo'].get('explanation'):
        raise Stop('缺少独立示范')
    sha = digest(path)
    registry = json_read(ROOT / 'cards' / 'versions.json')
    if registry.get(qid, {}).get(card['version']) != sha:
        raise Stop('题目版本内容不匹配：禁止沿用版本，须新版本并重新审核')
    archive = ROOT / 'cards' / 'archive' / qid / (card['version'] + '.json')
    if not archive.is_file() or digest(archive) != sha:
        raise Stop('缺少对应版本的不可变题卡快照')
    review = json_read(ROOT / 'reviews' / (qid + '@' + card['version'] + '.json'))
    if review.get('card_id') != qid or review.get('version') != card['version'] or review.get('content_sha256') != sha:
        raise Stop('审核记录不匹配')
    transitions = review.get('transitions', [])
    if not isinstance(transitions, list) or [x.get('state') for x in transitions] != ['verified','approved','published']:
        raise Stop('题目未完成 verified → approved → published')
    dates = []
    for x in transitions:
        if x.get('actor_type') not in ('human','ai') or not all(isinstance(x.get(k),str) and x[k].strip() for k in ('actor','time','note')):
            raise Stop('审核记录不完整')
        try:
            value = dt.datetime.fromisoformat(x['time'])
            if value.tzinfo is None:
                raise ValueError()
            dates.append(value)
        except ValueError:
            raise Stop('审核时间无效，须带时区')
    if dates != sorted(dates):
        raise Stop('审核阶段时间顺序无效')
    if any(x['actor_type'] != 'human' for x in transitions[1:]):
        raise Stop('批准及发布须由成人审核')
    return card, sha

def learner_dir(learner):
    if not PATTERN.fullmatch(learner):
        raise Stop('化名仅允许字母、数字、下划线及短横线')
    return ROOT / 'records' / learner

def load_events(folder):
    path = folder / 'events.jsonl'
    if not path.exists():
        return []
    events = []
    for line in read_text(path).splitlines():
        try:
            events.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise Stop('事件日志损坏，停止恢复') from exc
    return events

def append(folder, event):
    event = {'time': stamp(), **event}
    with (folder / 'events.jsonl').open('a', encoding='utf-8') as f:
        f.write(json.dumps(event, ensure_ascii=False, separators=(',', ':')) + '\n')
        f.flush()
        os.fsync(f.fileno())
    return event

def session(events):
    starts = [i for i,e in enumerate(events) if e.get('type') == 'start']
    return events[starts[-1]:] if starts else []

def status(ev):
    if not ev:
        return 'none'
    s='active'
    for e in ev:
        if e['type'] == 'pause': s='paused'
        elif e['type'] == 'resume': s='active'
        elif e['type'] == 'end' or e.get('session_completed') is True: s='completed'
    return s

def current(ev):
    """One question at a time, move only after complete or skip."""
    start=ev[0]
    i=sum(e['type'] in ('complete','skip') for e in ev)
    return start['questions'][i] if i < len(start['questions']) else None

def save_summary(folder, ev):
    summary={'session_id':ev[0]['session_id'],'mode':ev[0]['mode'],'completed':sum(x['type']=='complete' or (x['type']=='attempt' and x.get('session_completed') is True) for x in ev),'skipped':sum(x['type']=='skip' for x in ev),'attempts':sum(x['type']=='attempt' for x in ev),'parent_feedback':[x['text'] for x in ev if x['type']=='parent_feedback'],'question_versions':ev[0]['questions'],'note':'仅为观察记录，不代表掌握或教育效果。'}
    (folder / ('summary-' + ev[0]['session_id'] + '.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return summary

def run(args):
    if not re.fullmatch(r'synthetic(?:[-_][A-Za-z0-9_-]+)?', args.learner):
        raise Stop('仅允许隔离合成学习者；真实儿童入口关闭')
    # Historical records remain readable and an existing session can be closed,
    # but fixed cards are no longer an entry point for dynamic Sigma teaching.
    if args.action not in ('progress', 'pause', 'end', 'feedback'):
        raise Stop('固定题卡训练入口已关闭；隔离验证使用 Sigma 动态会话与实时门禁')
    folder=learner_dir(args.learner)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Release writers MUST hold .publication.lock exclusively throughout changes.
    with (ROOT / '.publication.lock').open('a') as publication, (folder / '.lock').open('a') as lock:
        fcntl.flock(publication, fcntl.LOCK_SH)
        fcntl.flock(lock, fcntl.LOCK_EX)
        events=load_events(folder); ev=session(events); st=status(ev)
        if args.action == 'progress':
            return {'status':st,'session_id':ev[0]['session_id'] if ev else None,'mode':ev[0]['mode'] if ev else None,'current':current(ev) if ev and st != 'completed' else None,'events':len(ev)}
        if not ev: raise Stop('没有可操作的训练')
        if st == 'completed':
            if args.action in ('end', 'skip', 'complete'):
                summary=save_summary(folder, ev)
                return {'status': 'completed', 'message': '训练已结束。', 'summary':summary}
            if args.action != 'feedback': raise Stop('训练已结束')
        if args.action == 'feedback':
            append(folder, {'type':'parent_feedback','session_id':ev[0]['session_id'],'text':args.text})
            return {'message':'家长反馈已保存'}
        if args.action == 'end':
            append(folder, {'type':'end','session_id':ev[0]['session_id'],'reason':args.text or '结束训练'})
            ev=session(load_events(folder))
            summary=save_summary(folder, ev)
            return {'status':'completed','summary':summary}
        if args.action == 'pause':
            if st != 'active': raise Stop('训练已暂停')
            append(folder, {'type':'pause','session_id':ev[0]['session_id'],'reason':args.text or '暂停'})
            return {'status':'paused'}

def main():
    parser=argparse.ArgumentParser(description='儿童思维训练：仅已发布的试点题卡')
    sub=parser.add_subparsers(dest='action',required=True)
    p=sub.add_parser('hash'); p.add_argument('question')
    for action in ('start','show','attempt','hint','demo','explain','skip','complete','pause','resume','end','feedback','progress'):
        p=sub.add_parser(action); p.add_argument('--learner',required=True,help='不含真实姓名的化名')
        if action=='start': p.add_argument('--mode',required=True,choices=list(MODES))
        if action=='attempt':
            p.add_argument('--response',required=True); p.add_argument('--correctness',required=True,choices=['correct','partial','incorrect','unknown']); p.add_argument('--explanation',required=True,choices=['valid','invalid','unclear','none'])
        if action=='explain': p.add_argument('--consent',action='store_true')
        if action in ('pause','end'): p.add_argument('--text',default='')
        if action=='feedback': p.add_argument('--text',required=True)
    args=parser.parse_args()
    try:
        out={'sha256':digest(card_path(args.question))} if args.action=='hash' else run(args)
        print(json.dumps(out,ensure_ascii=False,indent=2))
    except (Stop,OSError,ValueError,KeyError,TypeError) as exc:
        print(json.dumps({'error':str(exc)},ensure_ascii=False),file=sys.stderr); return 1
    return 0
if __name__ == '__main__':
    sys.exit(main())
