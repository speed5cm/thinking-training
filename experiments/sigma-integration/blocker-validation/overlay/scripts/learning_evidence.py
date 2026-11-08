#!/usr/bin/env python3
"""Capture pilot observations and make conservative, non-executing recommendations."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('coach_for_evidence', ROOT / 'pilot-c01-c02/scripts/coach.py')
coach = importlib.util.module_from_spec(spec)
spec.loader.exec_module(coach)
rspec = importlib.util.spec_from_file_location('roadmap_for_evidence', ROOT / 'scripts/generate_roadmap.py')
roadmap = importlib.util.module_from_spec(rspec)
rspec.loader.exec_module(roadmap)

class EvidenceError(ValueError):
    pass

def get_folder(learner):
    folder = coach.learner_dir(learner)
    if not folder.is_dir():
        raise EvidenceError('学习者记录不存在')
    return folder

def load_evidence(folder):
    path = folder / 'evidence.jsonl'
    if not path.exists():
        return []
    try:
        records = [json.loads(line) for line in path.read_text(encoding='utf-8').splitlines()]
        if any(not isinstance(x, dict) for x in records):
            raise ValueError('证据不是对象')
        return records
    except (ValueError, UnicodeError) as exc:
        raise EvidenceError('证据文件损坏，停止处理') from exc

def current_card(concept, ref):
    if concept not in ('C01', 'C02') or ref['id'] not in coach.MODES[concept]:
        raise EvidenceError('不属于已发布训练范围')
    coach.gate(concept)
    card, sha = coach.load_card(ref['id'], concept)
    if ref['version'] != card['version'] or ref['sha256'] != sha:
        raise EvidenceError('历史题卡版本与当前发布不一致')

def capture(learner, session_id, extra):
    if not isinstance(extra, dict) or set(extra) != {'reason_quote', 'transfer', 'parent_feedback'}:
        raise EvidenceError('补充字段须为 reason_quote、transfer、parent_feedback')
    transfer = extra['transfer']
    if (not isinstance(extra['reason_quote'], str) or not isinstance(extra['parent_feedback'], str)
        or not isinstance(transfer, dict) or set(transfer) != {'status', 'observation', 'parent_verified_novel'}
        or transfer['status'] not in ('unknown', 'no', 'yes') or not isinstance(transfer['observation'], str)
        or type(transfer['parent_verified_novel']) is not bool
        or (transfer['parent_verified_novel'] and (transfer['status'] != 'yes' or not transfer['observation'].strip()))):
        raise EvidenceError('补充字段格式无效')
    folder = get_folder(learner)
    with (coach.ROOT / '.publication.lock').open('a') as publication, (folder / '.lock').open('a') as lock:
        fcntl.flock(publication, fcntl.LOCK_SH)
        fcntl.flock(lock, fcntl.LOCK_EX)
        events = coach.load_events(folder)
        starts = [x for x in events if x.get('type') == 'start' and x.get('session_id') == session_id]
        if len(starts) != 1 or starts[0].get('mode') not in ('C01', 'C02'):
            raise EvidenceError('会话不存在或不是正式 C01/C02 训练')
        start = starts[0]
        concept = start['mode']
        questions = start['questions']
        if len(questions) != 1 or questions[0]['concept'] != concept:
            raise EvidenceError('会话题卡不符合试点范围')
        ref = questions[0]
        current_card(concept, ref)
        session_events = [x for x in events if x.get('session_id') == session_id]
        attempts = [i for i, e in enumerate(session_events) if e.get('type') == 'attempt' and e.get('question') == ref['id']]
        if not attempts:
            raise EvidenceError('会话尚无作答')
        if coach.status(session_events) != 'completed':
            raise EvidenceError('会话尚未结束；结束后采集最后一次作答')
        i = attempts[-1]
        attempt = session_events[i]
        previous = [x for x in session_events[:i] if x.get('question') == ref['id']]
        hints = [x['level'] for x in previous if x.get('type') == 'hint']
        support = [x['type'] for x in previous if x.get('type') in ('demo', 'final_explanation')]
        records = load_evidence(folder)
        if any(r.get('session_id') == session_id and r.get('card', {}).get('id') == ref['id'] for r in records):
            raise EvidenceError('该会话题卡已经采集')
        ai = attempt['ai_assessment']
        record = {'schema_version': 1, 'captured_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'session_id': session_id, 'concept': concept,
                  'card': {k: ref[k] for k in ('id', 'version', 'sha256')},
                  'raw_response': attempt['raw_response'], 'reason_quote': extra['reason_quote'],
                  'ai_temporary_correctness': ai['correctness'], 'explanation_quality': ai['explanation'],
                  'hint_level': max(hints, default=0), 'prior_attempts': len(attempts) - 1, 'prior_support': support,
                  'transfer': transfer, 'coach_parent_feedback': [x['text'] for x in session_events if x.get('type') == 'parent_feedback'],
                  'parent_feedback': extra['parent_feedback']}
        fd = os.open(folder / 'evidence.jsonl', os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, 'a', encoding='utf-8') as f:
            f.write(json.dumps(record, ensure_ascii=False, separators=(',', ':')) + '\n')
            f.flush()
            os.fsync(f.fileno())
        return {'captured': True, 'session_id': session_id, 'concept': concept, 'note': '采集不代表掌握'}

def evaluate(records, concept):
    selected = [x for x in records if x['concept'] == concept]
    eligible = [x for x in selected if x['ai_temporary_correctness'] == 'correct'
                and x['explanation_quality'] == 'valid' and x['reason_quote'].strip()
                and x['reason_quote'] in x['raw_response'] and x['hint_level'] in (0, 1)
                and x['prior_attempts'] <= 1 and not x['prior_support']]
    unique_sessions = {x['session_id'] for x in eligible}
    unique_cards = {x['card']['id'] for x in eligible}
    transfer = any(x['transfer']['status'] == 'yes' and x['transfer']['parent_verified_novel'] and x['transfer']['observation'].strip() for x in eligible)
    ready = len(unique_sessions) >= 2 and len(unique_cards) >= 2 and transfer
    unclear = sum(x['explanation_quality'] in ('invalid', 'unclear', 'none') for x in selected)
    difficult = sum(x['ai_temporary_correctness'] in ('incorrect', 'unknown') or x['hint_level'] >= 2 for x in selected)
    return {'concept': concept, 'learning_progress': {'evidence_opportunities': len(selected)},
            'mastery': 'mastered_candidate' if ready else 'pending_confirmation',
            'eligible_sessions': len(unique_sessions), 'eligible_distinct_cards': len(unique_cards),
            'novel_transfer_observed': bool(transfer), 'unclear_explanations': unclear,
            'difficulty_observations': difficult, 'note': '候选须家长复核；训练完成、进度和掌握相互独立。'}

def evidence_digest(records):
    return hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()

def assess(learner, already_locked=False):
    folder = get_folder(learner)
    with contextlib.ExitStack() as stack:
        if not already_locked:
            publication = stack.enter_context((coach.ROOT / '.publication.lock').open('a'))
            lock = stack.enter_context((folder / '.lock').open('a'))
            fcntl.flock(publication, fcntl.LOCK_SH)
            fcntl.flock(lock, fcntl.LOCK_SH)
        records = load_evidence(folder)
        seen = set()
        for record in records:
            key = (record['session_id'], record['card']['id'])
            if key in seen:
                raise EvidenceError('重复证据，停止评估')
            seen.add(key)
            current_card(record['concept'], record['card'])
        return {'assessments': [evaluate(records, c) for c in ('C01', 'C02')],
                'evidence_digest': evidence_digest(records),
                'training_status': coach.status(coach.session(coach.load_events(folder)))}

def confirm_c01(learner):
    """Explicit parent confirmation, valid only for the exact current evidence."""
    folder = get_folder(learner)
    with (coach.ROOT / '.publication.lock').open('a') as publication, (folder / '.lock').open('a') as lock:
        fcntl.flock(publication, fcntl.LOCK_SH)
        fcntl.flock(lock, fcntl.LOCK_EX)
        records = load_evidence(folder)
        seen = set()
        for record in records:
            key = (record['session_id'], record['card']['id'])
            if key in seen:
                raise EvidenceError('重复证据，停止确认')
            seen.add(key)
            current_card(record['concept'], record['card'])
        if evaluate(records, 'C01')['mastery'] != 'mastered_candidate':
            raise EvidenceError('C01 证据不足，不能确认掌握')
        record = {'concept': 'C01', 'evidence_digest': evidence_digest(records),
                  'confirmed_at': dt.datetime.now(dt.timezone.utc).isoformat(),
                  'confirmation': 'parent'}
        path = folder / 'mastery-confirmation.json'
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            json.dump(record, f, ensure_ascii=False)
            f.write('\n')
            f.flush()
            os.fsync(f.fileno())
        return {'confirmed': 'C01', 'note': '证据发生变化后需重新评估和确认。'}

def recommend(learner, already_locked=False):
    assessment = assess(learner, already_locked=already_locked)
    data = roadmap.build(ROOT)
    items = {c['id']: c for c in data['concepts']}
    first = assessment['assessments'][0]
    if not items['C01']['formal_teaching_available']:
        return {'action': 'blocked', 'concept': None, 'reason': 'C01 发布或 Wiki 门禁未通过', 'assessment': assessment}
    if first['mastery'] == 'mastered_candidate':
        path = get_folder(learner) / 'mastery-confirmation.json'
        try:
            confirmation = json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
        except (ValueError, UnicodeError):
            confirmation = {}
        if (confirmation.get('confirmation') != 'parent' or confirmation.get('concept') != 'C01'
            or confirmation.get('evidence_digest') != assessment['evidence_digest']):
            return {'action': 'parent_review', 'concept': None, 'reason': 'C01 候选须家长复核确认', 'assessment': assessment}
        second = items['C02']
        if second['hard_prerequisites'] != ['C01'] or not second['formal_teaching_available']:
            return {'action': 'blocked', 'concept': None, 'reason': 'C02 先修关系或发布门禁不满足', 'assessment': assessment}
        return {'action': 'consider_next', 'concept': 'C02', 'reason': 'C01 已经家长确认；C02 发布门禁当前通过，进入前仍须现场复核。', 'assessment': assessment}
    if first['difficulty_observations'] >= 2:
        reason = '多次困难；家长可暂停或在已发布材料内降低支持负担。'
    elif first['unclear_explanations']:
        reason = '解释尚不清楚；可用已发布材料巩固，陌生情境须另有已发布材料。'
    else:
        reason = '证据不足；可继续采集已发布训练的观察，重复同题不能证明迁移。'
    return {'action': 'collect_or_reinforce', 'concept': 'C01', 'reason': reason, 'assessment': assessment}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capture', 'assess', 'confirm-c01', 'recommend'))
    parser.add_argument('--learner', required=True)
    parser.add_argument('--session')
    args = parser.parse_args()
    try:
        if args.action == 'capture':
            if not args.session:
                raise EvidenceError('capture 需要 --session 和标准输入 JSON')
            result = capture(args.learner, args.session, json.load(sys.stdin))
        elif args.action == 'assess':
            result = assess(args.learner)
        elif args.action == 'confirm-c01':
            result = confirm_c01(args.learner)
        else:
            result = recommend(args.learner)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (EvidenceError, coach.Stop, roadmap.Invalid, OSError, ValueError, KeyError, TypeError) as exc:
        print('停止：' + str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
