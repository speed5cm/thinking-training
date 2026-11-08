#!/usr/bin/env python3
"""Durable, gated state for an AI-led tutor. This program does not generate teaching content."""
import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile

import learning_evidence as evidence
import validate_personal_roadmap as planner

coach = evidence.coach
ACTIONS = {'diagnose', 'clarify', 'probe', 'simplify', 'hint', 'parallel', 'counterexample', 'transfer', 'review'}
FIELDS = {'understanding', 'answer_reason', 'reasoning', 'alternatives_verification', 'support_dependency', 'misconception', 'next_step', 'evidence_quote'}

class Stop(ValueError):
    pass

def save(path, obj):
    fd, name = tempfile.mkstemp(dir=path.parent, prefix='.tutor-', suffix='.tmp')
    try:
        os.fchmod(fd, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(obj, f, ensure_ascii=False, indent=2)
            f.write('\n'); f.flush(); os.fsync(f.fileno())
        os.replace(name, path)
        d = os.open(path.parent, os.O_RDONLY)
        try: os.fsync(d)
        finally: os.close(d)
    finally:
        if os.path.exists(name): os.unlink(name)

def read_state(path):
    s = json.loads(path.read_text(encoding='utf-8'))
    if not isinstance(s, dict) or s.get('schema_version') != 1 or s.get('status') not in ('active', 'paused', 'ended') or not isinstance(s.get('turns'), list):
        raise Stop('导师状态损坏，停止恢复')
    return s

def gate(learner, concept):
    ctx = planner.context(learner)
    rec = ctx['current_recommendation']
    if rec['concept'] != concept or rec['action'] not in ('collect_or_reinforce', 'consider_next'):
        raise Stop('当前证据和先修门禁不允许此概念：' + rec['reason'])
    c = next(c for c in ctx['curriculum']['concepts'] if c['id'] == concept)
    if not c['formal_teaching_available']:
        raise Stop('教学内容未发布')
    reads = coach.gate(concept)
    card, sha = coach.load_card(coach.MODES[concept][0], concept)
    return ctx, c, reads, {'id': card['id'], 'version': card['version'], 'sha256': sha}

def text_field(obj, key, empty=False):
    value = obj.get(key)
    if not isinstance(value, str) or (not empty and not value.strip()):
        raise Stop('字段无效：' + key)
    return value

def roadmap_info(folder, ctx, learner):
    path = folder / 'personal-roadmap.json'
    if not path.exists(): return {'version': None, 'status': 'missing'}
    content = path.read_bytes()
    try:
        planner.validate(json.loads(content), ctx, learner)
        status = 'current'
    except (ValueError, KeyError, TypeError): status = 'stale'
    return {'version': hashlib.sha256(content).hexdigest(), 'status': status}

def run(action, learner, payload):
    folder = coach.learner_dir(learner)
    if action == 'start': folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    if not folder.is_dir(): raise Stop('没有学习记录，请先开始学习')
    path = folder / 'tutor-state.json'
    with (folder / '.tutor-lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not path.exists():
            if action != 'start': raise Stop('没有导师会话，请先开始学习')
            ctx = planner.context(learner)
            concept = ctx['current_recommendation']['concept']
            if not concept: raise Stop(ctx['current_recommendation']['reason'])
            ctx, c, reads, card = gate(learner, concept)
            s = {'schema_version': 1, 'status': 'active', 'concept': concept, 'goal': c['teaching_goal'], 'phase': 'diagnosis' if not coach.load_events(folder) and not evidence.load_evidence(folder) else 'learning', 'turns': [], 'created_at': coach.stamp(), 'updates': []}
            save(path, s)
            return {'state': s, 'roadmap': roadmap_info(folder, planner.context(learner), learner), 'wiki_reads': reads, 'card': card}
        s = read_state(path)
        if action == 'start': action = 'context'
        if action in ('context', 'resume', 'question', 'answer'):
            ctx, c, reads, card = gate(learner, s['concept'])
            if s['goal'] != c['teaching_goal']: raise Stop('教学目标已变更，须人工核查后恢复')
        if action == 'context':
            return {'state': s, 'roadmap': roadmap_info(folder, ctx, learner), 'recommendation': ctx['current_recommendation'], 'wiki_page': c['wiki_page'], 'wiki_reads': reads, 'card': card}
        if action == 'resume':
            if s['status'] != 'paused': raise Stop('当前会话未暂停')
            s['status'] = 'active'; s['updates'].append({'at': coach.stamp(), 'event': 'resume'})
        elif action in ('pause', 'end'):
            if s['status'] == 'ended': raise Stop('会话已结束')
            s['status'] = 'paused' if action == 'pause' else 'ended'
            s['updates'].append({'at': coach.stamp(), 'event': action, 'reason': text_field(payload, 'reason', True)})
        elif action == 'question':
            if s['status'] != 'active' or (s['turns'] and s['turns'][-1]['response'] is None): raise Stop('未处于可提问状态；保留未答问题')
            if payload.get('action') not in ACTIONS: raise Stop('教学动作无效')
            question = text_field(payload, 'question')
            if len(question) > 200 or question.count('？') + question.count('?') > 1: raise Stop('每轮只允许简短的一个问题')
            s['turns'].append({'at': coach.stamp(), 'concept': s['concept'], 'goal': s['goal'], 'action': payload['action'], 'reason': text_field(payload, 'reason'), 'question': question, 'response': None, 'analysis': None, 'parent_observation': '', 'roadmap': roadmap_info(folder, ctx, learner), 'wiki_reads': reads, 'card': card})
        elif action == 'answer':
            if s['status'] != 'active' or not s['turns'] or s['turns'][-1]['response'] is not None: raise Stop('没有等待回答的问题')
            response = text_field(payload, 'response')
            analysis = payload.get('analysis')
            if not isinstance(analysis, dict) or set(analysis) != FIELDS or any(not isinstance(v, str) or not v.strip() for v in analysis.values()): raise Stop('分析字段不完整；无证据填 unknown')
            quote = analysis['evidence_quote']
            if quote != 'unknown' and quote not in response: raise Stop('证据引用必须来自孩子原话')
            t = s['turns'][-1]; t['response'] = response; t['analysis'] = analysis
            t['parent_observation'] = text_field(payload, 'parent_observation', True); t['answered_at'] = coach.stamp()
            s['phase'] = 'learning'
        else: raise Stop('未知操作')
        save(path, s)
        return {'state': s, 'message': '已保存；动态教学记录不构成正式测评或掌握。'}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['start', 'context', 'resume', 'question', 'answer', 'pause', 'end'])
    p.add_argument('--learner', required=True)
    args = p.parse_args()
    try:
        payload = json.load(sys.stdin) if args.action in ('question', 'answer', 'pause', 'end') else {}
        print(json.dumps(run(args.action, args.learner, payload), ensure_ascii=False, indent=2))
    except (Stop, coach.Stop, evidence.EvidenceError, planner.Invalid, evidence.roadmap.Invalid, OSError, ValueError, KeyError, TypeError, StopIteration) as exc:
        print('停止：' + str(exc), file=sys.stderr); return 1
    return 0

if __name__ == '__main__': sys.exit(main())
