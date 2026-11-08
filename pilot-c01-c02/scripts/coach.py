#!/usr/bin/env python3
"""File-based, parent-supervised C01/C02 prototype. Never approves cards."""
import argparse
import datetime as dt
import fcntl
import hashlib
import importlib.util
import types
import json
import os
from pathlib import Path
import re
import sys
import uuid

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

def after_last_question(ev):
    i = max((i for i,e in enumerate(ev) if e['type'] in ('start','complete','skip')), default=0)
    return ev[i+1:]

def save_summary(folder, ev):
    summary={'session_id':ev[0]['session_id'],'mode':ev[0]['mode'],'completed':sum(x['type']=='complete' or (x['type']=='attempt' and x.get('session_completed') is True) for x in ev),'skipped':sum(x['type']=='skip' for x in ev),'attempts':sum(x['type']=='attempt' for x in ev),'parent_feedback':[x['text'] for x in ev if x['type']=='parent_feedback'],'question_versions':ev[0]['questions'],'note':'仅为观察记录，不代表掌握或教育效果。'}
    (folder / ('summary-' + ev[0]['session_id'] + '.json')).write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    return summary

def authorize_c02_locked(folder):
    """Caller holds the learner lock and publication read lock; no nested locks."""
    path = ROOT.parent / 'scripts' / 'learning_evidence.py'
    if not path.is_file():
        raise Stop('证据模块不可用，C02 不可授权')
    spec = importlib.util.spec_from_file_location('coach_authorization_evidence', path)
    evidence = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(evidence)
    evidence.coach = types.SimpleNamespace(MODES=MODES, gate=gate, load_card=load_card)
    try:
        records = evidence.load_evidence(folder)
        seen = set()
        eligible_records = []
        for record in records:
            key = (record['session_id'], record['card']['id'])
            if key in seen: raise Stop('重复证据')
            seen.add(key)
            if evidence.current_card(record['concept'], record['card']): eligible_records.append(record)
        if evidence.evaluate(eligible_records, 'C01')['mastery'] != 'mastered_candidate':
            raise Stop('C01 掌握证据不足，C02 不可授权')
        confirmation = json_read(folder / 'mastery-confirmation.json')
        if not evidence.confirmation_valid(confirmation, evidence.c01_digest(records), evidence.evidence_digest(records)):
            raise Stop('C01 家长确认缺失或已过期')
        curriculum = evidence.roadmap.build(ROOT.parent)
        c02 = next(x for x in curriculum['concepts'] if x['id'] == 'C02')
        if c02['hard_prerequisites'] != ['C01'] or not c02['formal_teaching_available']:
            raise Stop('C02 先修或发布状态不满足')
    except (evidence.EvidenceError, OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        raise Stop('C02 授权失败：' + str(exc)) from exc

def run(args):
    folder=learner_dir(args.learner)
    folder.mkdir(mode=0o700, parents=True, exist_ok=True)
    # Release writers MUST hold .publication.lock exclusively throughout changes.
    with (ROOT / '.publication.lock').open('a') as publication, (folder / '.lock').open('a') as lock:
        fcntl.flock(publication, fcntl.LOCK_SH)
        fcntl.flock(lock, fcntl.LOCK_EX)
        events=load_events(folder); ev=session(events); st=status(ev)
        if args.action == 'start':
            if st in ('active','paused'): raise Stop('已有未结束训练，请继续或结束')
            if args.mode == 'C02': authorize_c02_locked(folder)
            qs=[]; reads=[]
            for qid in MODES[args.mode]:
                concept='C01' if 'C01' in qid else 'C02'
                reads.extend(gate(concept)); card,sha=load_card(qid,concept)
                qs.append({'id':qid,'version':card['version'],'sha256':sha,'concept':concept,'source':card['source']})
            append(folder, {'type':'start','session_id':str(uuid.uuid4()),'mode':args.mode,'questions':qs,'gate_reads':reads})
            return {'status':'active','message':'训练已开始；使用 show 展示第一题。'}
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
        if args.action == 'resume':
            if st != 'paused': raise Stop('训练未暂停')
        elif st != 'active': raise Stop('训练已暂停，请先继续')
        if ev[0]['mode'] == 'C02': authorize_c02_locked(folder)
        q=current(ev)
        if q is None:
            if args.action == 'resume':
                append(folder, {'type':'resume','session_id':ev[0]['session_id']})
                return {'message':'全部题已处理，可结束训练。'}
            raise Stop('题目已处理完，请结束训练')
        reads=gate(q['concept']); card,sha=load_card(q['id'],q['concept'])
        if sha != q['sha256'] or card['version'] != q['version'] or card['source'] != q['source']:
            raise Stop('题卡或来源版本与会话不一致，停止训练')
        if args.action == 'resume':
            append(folder, {'type':'resume','session_id':ev[0]['session_id'],'gate_reads':reads})
            return {'status':'active','current_question':q['id'],'message':'已从检查点恢复；使用 show 查看当前题。'}
        if args.action == 'show':
            append(folder, {'type':'show','session_id':ev[0]['session_id'],'question':q['id'],'gate_reads':reads})
            return {'id':q['id'],'version':q['version'],'stem':card['stem']}
        recent=after_last_question(ev)
        if not any(x['type']=='show' for x in recent): raise Stop('请先展示当前题')
        if args.action == 'attempt':
            if [x['ai_assessment']['correctness'] for x in recent if x['type']=='attempt'][-2:] == ['incorrect', 'incorrect']:
                raise Stop('已连续受挫，请选择示范、跳过或暂停')
            last = sum(x['type'] in ('skip','complete') for x in ev) + 1 == len(ev[0]['questions'])
            accepted = last and args.correctness == 'correct' and args.explanation == 'valid'
            append(folder, {'type':'attempt','session_id':ev[0]['session_id'],'question':q['id'],'raw_response':args.response,'ai_assessment':{'correctness':args.correctness,'explanation':args.explanation},'session_completed':accepted})
            if accepted:
                summary=save_summary(folder,session(load_events(folder)))
                return {'status':'completed','message':'训练已结束；一次答对不代表掌握。','summary':summary}
            message='答案与理由已分别记录；尚不能据此认定掌握。'
            prior=[x['ai_assessment']['correctness'] for x in recent if x['type']=='attempt']
            if (prior + [args.correctness])[-2:] == ['incorrect', 'incorrect']: message='可以暂停、跳过或查看独立平行示范，不必继续追问。'
            return {'message':message}
        if args.action == 'hint':
            if not any(x['type']=='attempt' for x in recent): raise Stop('请先让孩子尝试；不知道也可记录为尝试')
            level=sum(x['type']=='hint' for x in recent)+1
            if level > 3: raise Stop('提示已用完，请选择示范、跳过或暂停')
            append(folder, {'type':'hint','session_id':ev[0]['session_id'],'question':q['id'],'level':level})
            if level == 3:
                return {'level': level, 'hint': card['hints'][2], 'parallel_demo': card['parallel_demo'], 'support': 'parallel_demo'}
            return {'level':level,'hint':card['hints'][level-1]}
        if args.action == 'demo':
            if not any(x['type']=='attempt' for x in recent): raise Stop('请先让孩子尝试')
            append(folder, {'type':'demo','session_id':ev[0]['session_id'],'question':q['id'],'kind':'parallel'})
            return {'parallel_demo':card['parallel_demo']}
        if args.action == 'explain':
            attempts = sum(x['type']=='attempt' for x in recent)
            hints = sum(x['type']=='hint' for x in recent)
            if not args.consent or (attempts < 2 and hints < 3):
                raise Stop('完整讲解需要孩子明确同意，且至少尝试两次或使用三级提示')
            append(folder, {'type':'final_explanation','session_id':ev[0]['session_id'],'question':q['id'],'support':'full_explanation','consent':True})
            return {'answer':card['answer'],'explanation':card['explanation'],'support':'full_explanation'}
        if args.action in ('skip','complete'):
            if args.action=='complete' and not any(x['type']=='attempt' for x in recent): raise Stop('尚无作答')
            last = len([x for x in ev if x['type'] in ('skip','complete')]) + 1 == len(ev[0]['questions'])
            append(folder, {'type':args.action,'session_id':ev[0]['session_id'],'question':q['id'],'session_completed':last})
            if last:
                summary=save_summary(folder,session(load_events(folder)))
                return {'status':'completed','message':'训练已结束。','summary':summary}
            return {'status':'active','message':'已记录；如有下一题请使用 show。'}
        raise Stop('未知操作')

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
