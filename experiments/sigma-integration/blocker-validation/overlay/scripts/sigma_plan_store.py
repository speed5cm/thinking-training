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
import learning_evidence as evidence
import validate_personal_roadmap as planner

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

def queue(records):
    latest={}
    for r in records:
        when=parse_date(r['captured_at'])
        if r['concept'] not in latest or when > latest[r['concept']][0]: latest[r['concept']]=(when,r)
    return [{'concept':cid,'evidence_session':r['session_id'], 'evidence_at':when.isoformat(),
             'due_at':(when+dt.timedelta(days=1)).isoformat(), 'status':'pending',
             'reason':'已有正式训练观察；一天后复习为实验安排，不表示掌握'}
            for cid,(when,r) in sorted(latest.items())]

def operate(action, learner, candidate=None, session=None):
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
            records=evidence.load_evidence(folder)
            # Recheck Wiki and snapshots while holding the shared authorization locks.
            if planner.context(learner, already_locked=True) != ctx: raise Invalid('规划输入发生变化，请重试')
            item={'version':len(store['history'])+1,'plan_sha256':sha(plan),'created_at':dt.datetime.now(dt.timezone.utc).isoformat(),
                  'inputs':{k:ctx[k] for k in ('curriculum_digest','learner_digest','evidence_digest')},'plan':plan,'review_queue':queue(records)}
            store['history'].append(item);write(path,store)
        if not store['history']: return {'status':'missing','review_queue':[]}
        item=store['history'][-1]
        if action == 'complete-review':
            records=evidence.load_evidence(folder)
            matching=[r for r in records if r['session_id'] == session]
            if len(matching) != 1: raise Invalid('须引用唯一已采集正式证据')
            record=matching[0]
            pending=[q for q in item['review_queue'] if q['concept']==record['concept'] and q['evidence_session'] != session and parse_date(record['captured_at']) > parse_date(q['evidence_at'])]
            events=store.setdefault('review_events',[])
            if len(pending) != 1 or any(e['plan_version']==item['version'] and e['concept']==record['concept'] for e in events):
                raise Invalid('没有可由此证据完成的复习')
            events.append({'plan_version':item['version'], 'concept':record['concept'], 'session_id':session,'evidence_at':record['captured_at']})
            write(path,store)
        if item['plan_sha256'] != sha(item['plan']): raise Invalid('规划内容摘要不匹配')
        stale=any(item['inputs'][k] != ctx[k] for k in item['inputs'])
        now=dt.datetime.now(dt.timezone.utc)
        reviews=[{**q,'due':parse_date(q['due_at']) <= now, 'status':'completed' if any(e['plan_version']==item['version'] and e['concept']==q['concept'] for e in store.get('review_events',[])) else 'pending'} for q in item['review_queue']]
        return {'status':'stale' if stale else 'current','version':item['version'],'plan_sha256':item['plan_sha256'], 'inputs':item['inputs'],'review_queue':reviews,'notice':'复习安排非掌握判定或教学授权；须重新检查实时门禁。'}

def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('action',choices=['publish','status','complete-review']);p.add_argument('--learner',required=True);p.add_argument('--plan');p.add_argument('--session');a=p.parse_args()
    try:
        if a.action=='publish' and not a.plan: raise Invalid('publish 需要 --plan')
        if a.action=='complete-review' and not a.session: raise Invalid('complete-review 需要 --session')
        print(json.dumps(operate(a.action,a.learner,a.plan,a.session),ensure_ascii=False,indent=2))
    except (Invalid, planner.Invalid, evidence.EvidenceError, evidence.coach.Stop, evidence.roadmap.Invalid, OSError, ValueError, KeyError, TypeError) as exc:
        print('停止：'+str(exc),file=sys.stderr); return 1
    return 0
if __name__=='__main__': sys.exit(main())
