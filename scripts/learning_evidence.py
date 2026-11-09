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
import tempfile

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
    if concept not in ('C01', 'C02'):
        raise EvidenceError('不属于已发布训练范围')
    coach.gate(concept)
    if ref['id'] in coach.MODES[concept]:
        card, sha = coach.load_card(ref['id'], concept)
        if ref['version'] == card['version']:
            if ref['sha256'] != sha:
                raise EvidenceError('题卡摘要不匹配')
            return True
    card, sha = coach.load_card(ref['id'], concept, version=ref['version'])
    if ref['sha256'] != sha:
        raise EvidenceError('历史题卡归档摘要不匹配')
    # Authentic old records remain visible but require separate review before reuse.
    return False

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
        if not current_card(concept, ref):
            raise EvidenceError('只能采集当前已发布题卡的会话')
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

def evidence_digest(records):
    return hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()

def destination_basis(learner):
    """Read the C02 content authorization and curriculum under publication lock."""
    import concept_authorization as authorization
    try:
        auth = authorization.check('C02', learner)
    except (authorization.Invalid, authorization.evidence.coach.Stop, OSError, ValueError, KeyError, TypeError) as exc:
        raise EvidenceError('C02 授权不可用: ' + str(exc)) from exc
    data = roadmap.build(ROOT)
    c02 = next(c for c in data['concepts'] if c['id'] == 'C02')
    if c02['hard_prerequisites'] != ['C01'] or not c02['formal_teaching_available']:
        raise EvidenceError('C02 先修或发布状态不满足')
    # A confirmation is tied to the complete current root Wiki and C02 authorization.
    paths = [ROOT / 'wiki/index.md', ROOT / 'curriculum/12-week-plan.md',
             ROOT / 'references/sources.md', ROOT / 'references/pedagogy.md']
    paths += sorted((ROOT / 'wiki/concepts').glob('*.md'))
    wiki = {str(p.relative_to(ROOT)): coach.digest(p) for p in paths}
    return {'authorization': auth, 'wiki_digest': evidence_digest([wiki]), 'prerequisites': c02['hard_prerequisites']}


def confirmation_valid(confirmation, candidate, destination):
    return (isinstance(confirmation, dict) and confirmation.get('concept') == 'C01'
            and confirmation.get('confirmation') == 'synthetic_simulation'
            and confirmation.get('rule_version') == candidate.get('rule_version')
            and confirmation.get('evidence_digest') == candidate.get('evidence_digest')
            and confirmation.get('destination_digest') == evidence_digest([destination]))


def assess(learner, already_locked=False):
    folder = get_folder(learner)
    with contextlib.ExitStack() as stack:
        if not already_locked:
            publication = stack.enter_context((coach.ROOT / '.publication.lock').open('a'))
            lock = stack.enter_context((folder / '.lock').open('a'))
            fcntl.flock(publication, fcntl.LOCK_SH)
            fcntl.flock(lock, fcntl.LOCK_SH)
        dynamic = dynamic_candidate(learner, already_locked=True)
        records = load_evidence(folder)
        return {'assessments': [{'concept':'C01',
                  'mastery':'mastered_candidate' if dynamic['candidate'] else 'pending_confirmation',
                  'learning_progress':{'evidence_opportunities':len(dynamic['evidence'])},
                  'dynamic_candidate':dynamic}],
                'historical_evidence_pending_review':len(records),
                'evidence_digest':dynamic['evidence_digest'],
                'c01_evidence_digest':dynamic['evidence_digest'],
                'training_status':coach.status(coach.session(coach.load_events(folder)))}


def confirm_c01(learner, synthetic_confirmation=False):
    """Record an explicitly labeled synthetic simulation, never a real identity."""
    import concept_authorization as authorization
    if not synthetic_confirmation or not authorization.synthetic_learner(learner):
        raise EvidenceError('仅接受显式标记的合成模拟确认')
    folder = get_folder(learner)
    with (coach.ROOT / '.publication.lock').open('a') as publication, (folder / '.lock').open('a') as lock:
        fcntl.flock(publication, fcntl.LOCK_SH)
        fcntl.flock(lock, fcntl.LOCK_EX)
        candidate = dynamic_candidate(learner, already_locked=True)
        if not candidate['candidate']:
            raise EvidenceError('C01 动态证据不足，不能确认')
        destination = destination_basis(learner)
        record = {'concept':'C01', 'confirmation':'synthetic_simulation',
                  'rule_version':candidate['rule_version'], 'evidence_digest':candidate['evidence_digest'],
                  'destination_digest':evidence_digest([destination]),
                  'confirmed_at':dt.datetime.now(dt.timezone.utc).isoformat()}
        path = folder / 'mastery-confirmation.json'
        fd, temporary = tempfile.mkstemp(prefix='.confirmation-', dir=folder)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(record, f, ensure_ascii=False); f.write('\n'); f.flush(); os.fsync(f.fileno())
            os.replace(temporary, path)
            directory_fd = os.open(folder, os.O_RDONLY)
            try: os.fsync(directory_fd)
            finally: os.close(directory_fd)
        finally:
            if os.path.exists(temporary): os.unlink(temporary)
        return {'confirmed':'C01', 'confirmation':'synthetic_simulation',
                'rule_version':record['rule_version'], 'evidence_digest':record['evidence_digest'],
                'note':'仅为合成模拟，不验证真实家长身份。'}


def recommend(learner, already_locked=False):
    if not already_locked:
        folder = get_folder(learner)
        with (coach.ROOT / '.publication.lock').open('a') as publication, (folder / '.lock').open('a') as lock:
            fcntl.flock(publication, fcntl.LOCK_SH); fcntl.flock(lock, fcntl.LOCK_SH)
            return recommend(learner, already_locked=True)
    assessment = assess(learner, already_locked=True)
    candidate = assessment['assessments'][0]['dynamic_candidate']
    if not candidate['conditions']['authorization']['met']:
        return {'action':'blocked', 'concept':None, 'reason':'C01 授权不可用', 'assessment':assessment}
    if not candidate['conditions']['record_integrity']['met']:
        return {'action':'blocked', 'concept':None, 'reason':'动态会话记录不完整或冲突', 'assessment':assessment}
    if not candidate['candidate']:
        return {'action':'collect_or_reinforce', 'concept':'C01', 'reason':'C01 动态证据不足', 'assessment':assessment}
    try:
        destination = destination_basis(learner)
    except (OSError, ValueError, KeyError, TypeError, coach.Stop) as exc:
        return {'action':'blocked', 'concept':None, 'reason':'C02 授权、Wiki 或先修不可用: '+str(exc), 'assessment':assessment}
    path = get_folder(learner) / 'mastery-confirmation.json'
    try: confirmation = json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError): confirmation = {}
    if not confirmation_valid(confirmation, candidate, destination):
        return {'action':'parent_review', 'concept':None, 'reason':'C01 候选须明确的合成模拟确认', 'assessment':assessment}
    return {'action':'consider_next', 'concept':'C02', 'reason':'合成模拟确认有效；入口仍须复核规划、先修和授权', 'assessment':assessment}


def authorize_c02_locked(learner):
    """Caller holds publication and learner locks through the actual use point."""
    import validate_personal_roadmap as planner
    import sigma_plan_store as plans
    recommendation = recommend(learner, already_locked=True)
    if recommendation['action'] != 'consider_next' or recommendation['concept'] != 'C02':
        raise EvidenceError('C02 入口阻断: ' + recommendation['reason'])
    folder = get_folder(learner)
    history = plans.read(folder / 'sigma' / 'plan-history.json')
    if history.get('schema_version') != 1 or not isinstance(history.get('history'), list) or not history['history']:
        raise EvidenceError('缺少已确认的合成路线')
    item = history['history'][-1]
    if (item.get('confirmation_kind') != 'synthetic_simulation' or not item.get('confirmation_nonce')
            or item.get('plan_sha256') != plans.sha(item.get('plan'))):
        raise EvidenceError('路线确认无效')
    context = planner.context(learner, already_locked=True)
    keys = ('curriculum_digest','learner_digest','evidence_digest')
    if item.get('inputs') != {k:context[k] for k in keys}:
        raise EvidenceError('路线许可已过期，必须重新确认')
    planner.validate(item['plan'], context, learner)
    return {'allowed':'C02', 'confirmation':'synthetic_simulation',
            'rule_version':recommendation['assessment']['assessments'][0]['dynamic_candidate']['rule_version']}

DYNAMIC_RULE_VERSION = 'C01-dynamic-candidate-v1'


def dynamic_candidate(learner, already_locked=False):
    """Recompute an isolated candidate from the authoritative session snapshot; never authorize."""
    import concept_authorization as authorization
    import sigma_session_store as sessions

    if not authorization.synthetic_learner(learner):
        raise EvidenceError('动态聚合仅适用于隔离合成数据')
    folder = get_folder(learner)
    with contextlib.ExitStack() as stack:
        if not already_locked:
            publication = stack.enter_context((coach.ROOT / '.publication.lock').open('a'))
            lock = stack.enter_context((folder / '.lock').open('a'))
            fcntl.flock(publication, fcntl.LOCK_SH); fcntl.flock(lock, fcntl.LOCK_SH)
        snapshot = sessions.read_folder(folder)
        try:
            auth = authorization.check('C01', learner)
            auth_error = ''
        except (authorization.Invalid, authorization.evidence.coach.Stop, coach.Stop, OSError, ValueError, KeyError, TypeError) as exc:
            auth, auth_error = None, str(exc)
        return aggregate_dynamic(snapshot, auth, auth_error, sessions, authorization)


def aggregate_dynamic(snapshot, auth, auth_error, sessions, authorization):
    """Pure with respect to records; validates citations against current authorized files."""
    turns = snapshot['turns']
    digest = evidence_digest([{'rule_version': DYNAMIC_RULE_VERSION, 'snapshot': snapshot,
                               'authorization': auth, 'authorization_error': auth_error}])
    questions, answers, analyses, invalid, interrupted = {}, {}, {}, set(), set()
    errors, timeline, active, previous_end, starts = [], {}, None, None, set()
    prior_time = None

    def timestamp(event):
        try:
            value = dt.datetime.fromisoformat(event['recorded_at'])
            if value.utcoffset() != dt.timedelta(0):
                return None
            return value
        except (ValueError, KeyError, TypeError):
            return None

    for i, event in enumerate(turns):
        kind, qid, sid = event.get('type'), event.get('question_id'), event.get('session_id')
        when = timestamp(event)
        if when is None or (prior_time is not None and when < prior_time):
            errors.append('事件时间缺失、非 UTC 或倒退')
        if when is not None:
            prior_time = when
        if kind in ('session_start', 'session_resume'):
            valid = bool(when and sid and sid not in starts and active is None)
            if kind == 'session_start':
                valid = valid and not starts and previous_end is None
            else:
                valid = valid and previous_end is not None and event.get('previous_session_id') == previous_end
            if not valid:
                errors.append('会话开始或恢复边界不可靠')
            starts.add(sid); active = sid
            timeline[sid] = {'valid': valid, 'start': when, 'end': None, 'previous': previous_end if kind == 'session_resume' else None}
        elif kind == 'session_end':
            valid = sid == active and sid in timeline and when is not None
            if not valid:
                errors.append('会话结束边界不可靠')
            if sid in timeline:
                timeline[sid]['valid'] &= valid
                timeline[sid]['end'] = when
            previous_end, active = sid, None
        elif kind in ('question', 'answer', 'analysis', 'support'):
            if sid != active or sid not in timeline or not timeline[sid]['valid']:
                errors.append('题目或作答缺少可靠活动会话')
            if kind == 'question':
                if not qid or qid in questions:
                    errors.append('问题 ID 缺失或重复')
                else:
                    questions[qid] = (i, event)
            elif kind == 'answer':
                if qid in answers or qid not in questions or sid != questions[qid][1].get('session_id'):
                    errors.append('原答重复或归属不明')
                else:
                    answers[qid] = (i, event)
            elif kind == 'analysis':
                if qid in analyses or qid not in answers or sid != questions[qid][1].get('session_id'):
                    errors.append('评价重复或归属不明')
                else:
                    analyses[qid] = (i, event.get('analysis'), qid + ':analysis')
        elif kind in ('correction', 'invalidation', 'interruption'):
            if qid not in questions or sid != questions[qid][1].get('session_id'):
                errors.append('更正或中断归属不明')
                continue
            if kind == 'correction':
                if qid not in analyses or qid in invalid or qid in interrupted or not event.get('event_id') or not event.get('reason', '').strip():
                    errors.append('更正依据或顺序无效')
                else:
                    analyses[qid] = (i, event.get('replacement'), event['event_id'])
            elif kind == 'invalidation':
                invalid.add(qid)
            else:
                interrupted.add(qid)
        else:
            errors.append('存在无法识别的会话事件')
    event_ids = [e.get('event_id') for e in turns if e.get('type') in ('support', 'correction', 'invalidation')]
    if any(not isinstance(x, str) or not x.strip() for x in event_ids) or len(set(event_ids)) != len(event_ids):
        errors.append('支持、更正或失效事件 ID 缺失或重复')

    items = []
    for qid, (qi, q) in questions.items():
        if q.get('concept') != 'C01' or q.get('purpose') != 'assessment':
            continue
        reasons = []
        answer = answers.get(qid)
        analysis = analyses.get(qid)
        if qid in invalid: reasons.append('题目已失效')
        if qid in interrupted: reasons.append('授权或旧会话中断')
        if not auth or q.get('authorization_sha256') != auth.get('authorization_sha256'):
            reasons.append('当前授权不可用或与出题授权不同')
        if not answer or not analysis or answer[0] <= qi or analysis[0] <= answer[0]:
            reasons.append('原答或评价缺失、顺序无效')
        try:
            if (not sessions.nonempty(q['text']) or not sessions.nonempty(q['context']) or not sessions.nonempty(q['answer_basis'])
                or type(q['practice']) is not bool or not isinstance(q['dimensions'], list) or not q['dimensions']
                or len(set(q['dimensions'])) != len(q['dimensions']) or any(d not in sessions.DIMENSIONS for d in q['dimensions'])
                or not {'wiki/concepts/observation-vs-inference.md', 'pilot-c01-c02/wiki/concepts/C01.md'} <= set(q['wiki_sources'])
                or not set(q['wiki_sources']) <= set(authorization.FILES)):
                raise ValueError('题目声明不完整')
            for path, sha in q['wiki_sources'].items():
                if coach.digest(authorization.ROOT / path) != sha: raise ValueError('Wiki 摘要变化')
            if answer and analysis:
                ai, value, aid = analysis
                if not sessions.nonempty(answer[1]['text']) or set(value) != {'dimensions', 'observations'}:
                    raise ValueError('原答或评价不完整')
                sessions.validate_dimensions(value['dimensions'], q, answer[1]['text'])
                supports = [e for e in turns[:ai] if e.get('type') == 'support']
                sessions.validate_observations(value['observations'], q, answer[1]['text'], turns[:ai], supports)
                if value['dimensions']['novel_application']['status'] == 'supported' and value['observations']['novel_transfer']['status'] != 'yes':
                    raise ValueError('陌生应用缺少迁移判断')
        except (sessions.Invalid, OSError, ValueError, KeyError, TypeError, AttributeError) as exc:
            reasons.append('依据不完整或不匹配: ' + str(exc))
        value = analysis[1] if analysis and isinstance(analysis[1], dict) else {}
        obs = value.get('observations', {})
        dims = value.get('dimensions', {})
        semantic_usable = not reasons
        repetition = obs.get('repetition', {}).get('status')
        eligibility_reasons = []
        if repetition != 'no': eligibility_reasons.append('实质重复或重复性未知')
        if any(prior.get('text') == q.get('text') for index, prior in questions.values() if index < qi):
            eligibility_reasons.append('原题与先前题目完全相同')
        record = {'id': qid, 'analysis_id': analysis[2] if analysis else None, 'session_id': q.get('session_id'),
                  'context': q.get('context'), 'practice': q.get('practice'), 'question': q.get('text'), 'answer': answer[1].get('text') if answer else None,
                  'valid': not reasons, 'eligible_for_coverage': not reasons and not eligibility_reasons,
                  'semantic_usable': semantic_usable, 'reasons': reasons, 'eligibility_reasons': eligibility_reasons,
                  'correctness': dims.get('accuracy', {}).get('status', 'unknown'),
                  'dimensions': dims, 'observations': obs,
                  'answer_time': timestamp(answer[1]) if answer else None, 'analysis_order': analysis[0] if analysis else -1}
        items.append(record)

    valid = [x for x in items if x['eligible_for_coverage']]
    ids = lambda rows: [x['id'] for x in rows]
    def condition(ok, rows, reason):
        return {'met': bool(ok), 'evidence_ids': ids(rows), 'reason': '' if ok else reason}
    conditions = {}
    conditions['valid_questions'] = condition(len(valid) >= 3, valid, '至少需要 3 道有效且非重复的评估题')
    contexts = {}
    for item in valid: contexts.setdefault(item['context'], item)
    conditions['contexts'] = condition(len(contexts) >= 2, list(contexts.values()), '至少需要 2 种不同情境及非重复判断')
    pair = []
    zone = dt.timezone(dt.timedelta(hours=8))
    for a in valid:
        for b in valid:
            if not a['answer_time'] or not b['answer_time'] or a['session_id'] == b['session_id']: continue
            first, second = (a, b) if a['answer_time'] < b['answer_time'] else (b, a)
            s1, s2 = timeline.get(first['session_id'], {}), timeline.get(second['session_id'], {})
            # Follow the complete chain of ended sessions, not just distinct IDs.
            cursor, visited = second['session_id'], set()
            while cursor and cursor != first['session_id'] and cursor not in visited:
                visited.add(cursor); node = timeline.get(cursor, {})
                if not node.get('valid'): break
                parent = node.get('previous'); parent_node = timeline.get(parent, {})
                if not parent_node.get('valid') or not parent_node.get('end') or not node.get('start') or parent_node['end'] > node['start']: break
                cursor = parent
            if (cursor == first['session_id'] and s1.get('valid') and s2.get('valid') and s1.get('end')
                    and first['answer_time'] <= s1['end'] <= s2['start'] <= second['answer_time']
                    and second['answer_time'] - first['answer_time'] >= dt.timedelta(hours=12)
                    and first['answer_time'].astimezone(zone).date() != second['answer_time'].astimezone(zone).date()):
                pair = [first, second]; break
        if pair: break
    conditions['independent_sessions'] = condition(pair, pair, '需要可靠结束与恢复链、UTC+8 跨日且作答间隔至少 12 小时')
    successes = [x for x in valid if x['correctness'] == 'supported' and x['dimensions'].get('explanation', {}).get('status') == 'supported'
                 and x['observations'].get('support_complete', {}).get('status') == 'confirmed'
                 and not x['observations']['support_complete'].get('support_event_ids')]
    conditions['unprompted_reasoned'] = condition(len(successes) >= 2, successes, '需要 2 道无提示、正确且理由成立的题，支持完整性必须确认')
    transfer = [x for x in successes if x['observations'].get('novel_transfer', {}).get('status') == 'yes'
                and x['dimensions'].get('novel_application', {}).get('status') == 'supported'
                and all(ref in answers and ref not in invalid and ref not in interrupted
                        and sessions.nonempty(questions[ref][1].get('context'))
                        and questions[ref][1]['context'] != x['context']
                        for ref in x['observations']['novel_transfer'].get('related_question_ids', []))]
    conditions['novel_transfer'] = condition(transfer, transfer, '需要有依据的成功陌生迁移且没有提示污染')
    practice = [x for x in valid if x['practice'] is True and x['correctness'] == 'supported'
                and x['dimensions'].get('explanation', {}).get('status') == 'supported']
    conditions['generative_practice'] = condition(practice, practice, '需要完成有正确作答及理由依据的生成性实践')
    for dim in sessions.DIMENSIONS:
        positive = [x for x in valid if x['dimensions'].get(dim, {}).get('status') == 'supported'
                    and (dim != 'novel_application' or x in transfer)]
        conditions['dimension_' + dim] = condition(positive, positive, '缺少该维度可追溯的正向证据')
    unresolved, unknown = set(), []
    for item in sorted(items, key=lambda x: x['analysis_order']):
        if not item['semantic_usable']: continue
        ob = item['observations'].get('misconception', {})
        status = ob.get('status')
        if status == 'present': unresolved.add(item['id'])
        elif status == 'resolved':
            if (item['correctness'] == 'supported' and item['dimensions'].get('explanation', {}).get('status') == 'supported'
                    and all(sessions.nonempty(questions[ref][1].get('context'))
                            and questions[ref][1]['context'] != item['context'] for ref in ob.get('related_question_ids', []))):
                unresolved.difference_update(ob.get('related_question_ids', []))
            else:
                unknown.append(item['id'])
        elif status != 'absent': unknown.append(item['id'])
    blockers = [x for x in items if x['id'] in unresolved or x['id'] in unknown]
    conditions['no_unresolved_misconception'] = condition(not blockers and bool(valid),
        blockers if blockers else [x for x in items if x['semantic_usable']], '存在未解决或未知的关键混淆')
    conditions['authorization'] = {'met': bool(auth), 'evidence_ids': [auth['authorization_sha256']] if auth else [], 'reason': auth_error if not auth else ''}
    conditions['record_integrity'] = {'met': not errors, 'evidence_ids': [], 'reason': '；'.join(dict.fromkeys(errors))}
    return {'concept': 'C01', 'rule_version': DYNAMIC_RULE_VERSION, 'evidence_digest': digest,
            'snapshot_revision': snapshot['revision'], 'candidate': all(c['met'] for c in conditions.values()),
            'conditions': conditions,
            'evidence': [{k: v for k, v in x.items() if k not in ('answer_time', 'analysis_order', 'semantic_usable')} for x in items],
            'note': '只读合成候选，不是掌握、家长确认或教学授权；语义判断仍须 Sigma 复核。'}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('capture', 'assess', 'confirm-c01', 'recommend', 'dynamic-candidate'))
    parser.add_argument('--learner', required=True)
    parser.add_argument('--session')
    parser.add_argument('--synthetic-confirmation', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'capture':
            if not args.session:
                raise EvidenceError('capture 需要 --session 和标准输入 JSON')
            result = capture(args.learner, args.session, json.load(sys.stdin))
        elif args.action == 'dynamic-candidate':
            result = dynamic_candidate(args.learner)
        elif args.action == 'assess':
            result = assess(args.learner)
        elif args.action == 'confirm-c01':
            result = confirm_c01(args.learner, args.synthetic_confirmation)
        else:
            result = recommend(args.learner)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (EvidenceError, coach.Stop, roadmap.Invalid, OSError, ValueError, KeyError, TypeError) as exc:
        print('停止：' + str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
