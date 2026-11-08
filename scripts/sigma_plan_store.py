#!/usr/bin/env python3
"""Experimental validated Sigma plan snapshots and evidence-derived review queue."""
import argparse
import datetime as dt
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import uuid
import learning_evidence as evidence
import validate_personal_roadmap as planner
import sigma_session_store as sessions

class Invalid(ValueError): pass

def sha(obj):
    return hashlib.sha256(json.dumps(obj,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()).hexdigest()

def read(path):
    return json.loads(path.read_text(encoding='utf-8')) if path.exists() else {'schema_version': 1, 'history': []}

def write(path, data):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.plan-')
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f,ensure_ascii=False,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
        os.replace(name,path)
        fd = os.open(path.parent,os.O_RDONLY)
        try: os.fsync(fd)
        finally: os.close(fd)
    finally:
        if os.path.exists(name): os.unlink(name)

def parse_date(value):
    date=dt.datetime.fromisoformat(value)
    if date.tzinfo is None: raise Invalid('证据时间必须带时区')
    return date.astimezone(dt.timezone.utc)

def task_id(item):
    return sha([item['concept'], item['evidence_session'], item['evidence_at']])

def event_task_id(event, history):
    if 'task_id' in event:
        return event['task_id']
    # Existing experimental records bind completions to a plan and concept.
    for item in history:
        if item['version'] == event.get('plan_version'):
            matches = [q for q in item['review_queue'] if q['concept'] == event.get('concept')]
            if len(matches) == 1:
                return task_id(matches[0])
    raise Invalid('历史复习事件无法定位任务，停止处理')

def queue(records, history, events):
    latest={}
    for r in records:
        when=parse_date(r['captured_at'])
        if r['concept'] not in latest or when > latest[r['concept']][0]: latest[r['concept']]=(when,r)
    result = [dict(q) for q in history[-1]['review_queue']] if history else []
    for item in result:
        item['task_id'] = task_id(item)
    completed_sessions = {event['session_id'] for event in events}
    for cid,(when,r) in sorted(latest.items()):
        old = [q for q in result if q['concept'] == cid]
        if r['session_id'] in completed_sessions or any(q['evidence_session'] == r['session_id'] for q in old):
            continue
        item = {'concept':cid,'evidence_session':r['session_id'], 'evidence_at':when.isoformat(),
                'due_at':(when+dt.timedelta(days=1)).isoformat(), 'status':'pending',
                'reason':'已有正式训练观察；一天后复习为实验安排，不表示掌握'}
        item['task_id'] = task_id(item)
        result.append(item)
    return result

def dynamic_answer(snapshot, question_id, task=None):
    turns = snapshot['turns']
    found = {kind: [e for e in turns if e.get('type') == kind and e.get('question_id') == question_id]
             for kind in ('question', 'answer', 'analysis')}
    if any(len(found[k]) != 1 for k in found):
        raise Invalid('动态复习须引用已保存的唯一问题、原答和分析')
    if task is not None and found['question'][0].get('review_task_id') != task:
        raise Invalid('复习问题未关联该任务')
    if not isinstance(found['analysis'][0].get('analysis'), dict) or not found['analysis'][0]['analysis']:
        raise Invalid('动态复习分析缺失')
    return found

def operate(action, learner, candidate=None, session=None, payload=None):
    folder=evidence.get_folder(learner); dest=folder/'sigma';dest.mkdir(mode=0o700,exist_ok=True)
    path=dest/'plan-history.json'
    # Lock order is publication, learner, plan, shared with coach/evidence.
    with (evidence.coach.ROOT/'.publication.lock').open('a') as pub, (folder/'.lock').open('a') as learner_lock, (dest/'.plan-lock').open('a') as lock:
        fcntl.flock(pub,fcntl.LOCK_SH); fcntl.flock(learner_lock,fcntl.LOCK_EX); fcntl.flock(lock,fcntl.LOCK_EX)
        store=read(path)
        if store.get('schema_version') != 1 or not isinstance(store.get('history'),list): raise Invalid('规划历史损坏')
        ctx=planner.context(learner, already_locked=True)
        if action == 'publish':
            plan=json.loads(Path(candidate).read_text(encoding='utf-8'))
            planner.validate(plan,ctx,learner)
            records=[r for r in evidence.load_evidence(folder) if evidence.current_card(r['concept'], r['card'])]
            # Recheck Wiki and snapshots while holding the shared authorization locks.
            if planner.context(learner, already_locked=True) != ctx: raise Invalid('规划输入发生变化，请重试')
            item={'version':len(store['history'])+1,'plan_sha256':sha(plan),'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                  'inputs':{k:ctx[k] for k in ('curriculum_digest','learner_digest','evidence_digest')},'plan':plan,'review_queue':queue(records,store['history'],store.get('review_events',[]))}
            store['history'].append(item);write(path,store)
        if not store['history']:
            if action in ('schedule-dynamic', 'complete-dynamic'): raise Invalid('请先建立路线，再安排动态复习')
            return {'status':'missing','review_queue':[], 'dynamic_reviews':[]}
        item=store['history'][-1]
        if item['plan_sha256'] != sha(item['plan']): raise Invalid('规划内容摘要不匹配')
        stale=any(item['inputs'][k] != ctx[k] for k in item['inputs'])
        if action in ('schedule-dynamic', 'complete-dynamic'):
            if stale: raise Invalid('路线已过期，请先重新检查教学范围并更新路线，再推进动态复习')
            if not isinstance(payload, dict): raise Invalid('动态复习需要 JSON 对象')
            tasks = store.setdefault('dynamic_reviews', [])
            snapshot = sessions.read_folder(folder)
            now = dt.datetime.now(dt.timezone.utc)
            if action == 'schedule-dynamic':
                if set(payload) != {'concept', 'question_id', 'reason', 'interval_days'}:
                    raise Invalid('安排复习字段无效')
                concept, qid, reason, days = (payload[k] for k in ('concept','question_id','reason','interval_days'))
                if not isinstance(concept, str) or concept not in {c['id'] for c in ctx['curriculum']['concepts']}:
                    raise Invalid('未知概念')
                if not isinstance(qid, str) or not qid or not isinstance(reason, str) or not reason.strip():
                    raise Invalid('须提供问题 ID 和复习依据')
                if type(days) is not int or not 1 <= days <= 32: raise Invalid('复习间隔须为 1 至 32 天')
                dynamic_answer(snapshot, qid)
                if any(t['concept'] == concept and t['status'] == 'pending' for t in tasks):
                    raise Invalid('该概念已有待完成的动态复习')
                tasks.append({'task_id':str(uuid.uuid4()), 'concept':concept, 'source_question_id':qid,
                              'reason':reason, 'interval_days':days, 'scheduled_at':now.isoformat(),
                              'due_at':(now + dt.timedelta(days=days)).isoformat(), 'status':'pending'})
            else:
                if set(payload) != {'task_id', 'question_id', 'result', 'next_interval_days'}:
                    raise Invalid('完成复习字段无效')
                task_id_value, qid, result, days = (payload[k] for k in ('task_id','question_id','result','next_interval_days'))
                matches = [t for t in tasks if t['task_id'] == task_id_value]
                if len(matches) != 1 or matches[0]['status'] != 'pending': raise Invalid('复习任务不存在或已完成')
                task = matches[0]
                if parse_date(task['due_at']) > now: raise Invalid('复习任务尚未到期')
                if not isinstance(qid, str) or not qid: raise Invalid('复习问题 ID 无效')
                if result not in ('correct', 'partial', 'incorrect'): raise Invalid('复习结果无效')
                if type(days) is not int or not 1 <= days <= 32: raise Invalid('复习间隔须为 1 至 32 天')
                dynamic_answer(snapshot, qid, task_id_value)
                if any(t.get('review_question_id') == qid for t in tasks): raise Invalid('复习回答已使用')
                next_task = {'task_id':str(uuid.uuid4()), 'concept':task['concept'], 'source_question_id':qid,
                             'reason':'上次动态复习后的跟进；不代表正式掌握', 'interval_days':days,
                             'scheduled_at':now.isoformat(), 'due_at':(now + dt.timedelta(days=days)).isoformat(),
                             'status':'pending', 'previous_task_id':task_id_value}
                task.update({'status':'completed', 'review_question_id':qid, 'result':result,
                             'completed_at':now.isoformat(), 'next_task_id':next_task['task_id']})
                tasks.append(next_task)
            write(path, store)
        if action == 'complete-review':
            records=evidence.load_evidence(folder)
            matching=[r for r in records if r['session_id'] == session]
            if len(matching) != 1: raise Invalid('须引用唯一已采集正式证据')
            record=matching[0]
            if not evidence.current_card(record['concept'], record['card']):
                raise Invalid('历史题卡证据不能完成复习')
            events=store.setdefault('review_events',[])
            completed = {event_task_id(e, store['history']) for e in events}
            pending=[q for q in item['review_queue'] if q['concept']==record['concept'] and q['evidence_session'] != session and task_id(q) not in completed and parse_date(record['captured_at']) > parse_date(q['evidence_at'])]
            if len(pending) != 1 or any(e['session_id'] == session for e in events):
                raise Invalid('没有可由此证据完成的复习')
            events.append({'task_id':task_id(pending[0]), 'plan_version':item['version'], 'concept':record['concept'], 'session_id':session,'evidence_at':record['captured_at']})
            write(path,store)
        now=dt.datetime.now(dt.timezone.utc)
        completed = {event_task_id(e, store['history']) for e in store.get('review_events',[])}
        reviews=[{**q,'task_id':task_id(q),'due':parse_date(q['due_at']) <= now, 'status':'completed' if task_id(q) in completed else 'pending'} for q in item['review_queue']]
        dynamic = [{**t, 'due': t['status'] == 'pending' and parse_date(t['due_at']) <= now} for t in store.get('dynamic_reviews', [])]
        return {'status':'stale' if stale else 'current','version':item['version'],'plan_sha256':item['plan_sha256'], 'inputs':item['inputs'],'review_queue':reviews, 'dynamic_reviews':dynamic, 'notice':'复习安排非掌握判定或教学授权；须重新检查实时门禁。'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['publish','status','complete-review','schedule-dynamic','complete-dynamic']);p.add_argument('--learner',required=True);p.add_argument('--plan');p.add_argument('--session');a=p.parse_args()
    try:
        if a.action=='publish' and not a.plan: raise Invalid('publish 需要 --plan')
        if a.action=='complete-review' and not a.session: raise Invalid('complete-review 需要 --session')
        payload=json.load(sys.stdin) if a.action in ('schedule-dynamic','complete-dynamic') else None
        print(json.dumps(operate(a.action,a.learner,a.plan,a.session,payload),ensure_ascii=False,indent=2))
    except (Invalid, planner.Invalid, evidence.EvidenceError, evidence.coach.Stop, evidence.roadmap.Invalid, OSError, ValueError, KeyError, TypeError) as exc:
        print('停止：'+str(exc),file=sys.stderr); return 1
    return 0
if __name__=='__main__': sys.exit(main())
