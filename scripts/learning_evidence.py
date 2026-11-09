#!/usr/bin/env python3
"""Recompute isolated dynamic evidence and enforce concept gates."""
import argparse
import contextlib
import datetime as dt
import fcntl
import hashlib
import importlib.util
import json
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

def evidence_digest(records):
    return hashlib.sha256(json.dumps(records, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')).hexdigest()

DYNAMIC_RULE_VERSION = 'dynamic-candidate-v1'


def dynamic_candidate(learner, already_locked=False, concept='C01'):
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
            auth = authorization.check(concept, learner)
            auth_error = ''
        except (authorization.Invalid, authorization.evidence.coach.Stop, coach.Stop, OSError, ValueError, KeyError, TypeError) as exc:
            auth, auth_error = None, str(exc)
        return aggregate_dynamic(snapshot, auth, auth_error, sessions, authorization, concept)


def aggregate_dynamic(snapshot, auth, auth_error, sessions, authorization, concept='C01'):
    """Pure with respect to records; validates citations against current authorized files."""
    turns = snapshot['turns']
    assessment_ids = {e.get('question_id') for e in turns if e.get('type') == 'question'
                      and e.get('concept') == concept and e.get('purpose') == 'assessment'}
    last = max((i for i, e in enumerate(turns) if e.get('question_id') in assessment_ids), default=-1)
    # Prior questions can be cited as transfer or support context. Later routine
    # teaching does not change the evidence; corrections to prior context do.
    context_ids = {e.get('question_id') for e in turns[:last + 1] if e.get('type') == 'question'}
    relevant = [e for i, e in enumerate(turns) if e.get('question_id') in context_ids
                or (i <= last and e.get('type') in ('session_start', 'session_end', 'session_resume'))]
    digest = evidence_digest([{'rule_version': DYNAMIC_RULE_VERSION, 'concept': concept, 'turns': relevant,
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
        if q.get('concept') != concept or q.get('purpose') != 'assessment':
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
                or not authorization.concept_basis(concept)['required_sources'] <= set(q['wiki_sources'])
                or not set(q['wiki_sources']) <= set(authorization.concept_basis(concept)['files'])):
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
                for observation in ('repetition', 'novel_transfer', 'misconception'):
                    for ref in value['observations'][observation]['related_question_ids']:
                        if ref not in questions or questions[ref][1].get('concept') != concept:
                            raise ValueError('关联问题必须属于同一概念')
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
    return {'concept': concept, 'rule_version': DYNAMIC_RULE_VERSION, 'evidence_digest': digest,
            'snapshot_revision': snapshot['revision'], 'candidate': all(c['met'] for c in conditions.values()),
            'conditions': conditions,
            'evidence': [{k: v for k, v in x.items() if k not in ('answer_time', 'analysis_order', 'semantic_usable')} for x in items],
            'note': '只读合成候选，不是掌握、家长确认或教学授权；语义判断仍须 Sigma 复核。'}


def current_plan_locked(learner):
    """Verify the published route while publication and learner locks are held."""
    import sigma_plan_store as plans
    import validate_personal_roadmap as planner
    history = plans.read(get_folder(learner) / 'sigma' / 'plan-history.json').get('history')
    if not isinstance(history, list) or not history:
        raise EvidenceError('缺少已确认路线')
    item = history[-1]
    ctx = planner.context(learner, already_locked=True)
    keys = ('curriculum_digest', 'learner_digest', 'evidence_digest')
    if (item.get('confirmation_kind') != 'synthetic_simulation' or not item.get('confirmation_nonce')
            or item.get('plan_sha256') != plans.sha(item.get('plan'))
            or item.get('inputs') != {k: ctx[k] for k in keys}):
        raise EvidenceError('路线无效或已过期')
    planner.validate(item['plan'], ctx, learner)
    return item, ctx


def confirmation_path(folder, concept):
    return folder / 'sigma' / ('mastery-' + concept + '.json')


def confirmed_locked(learner, concept, item):
    candidate = dynamic_candidate(learner, already_locked=True, concept=concept)
    try:
        record = json.loads(confirmation_path(get_folder(learner), concept).read_text(encoding='utf-8'))
    except (OSError, ValueError, UnicodeError):
        return False
    return (candidate['candidate'] and isinstance(record, dict)
            and record.get('concept') == concept and record.get('confirmation') == 'synthetic_simulation'
            and record.get('rule_version') == candidate['rule_version']
            and record.get('evidence_digest') == candidate['evidence_digest']
            and record.get('plan_sha256') == item['plan_sha256'])


def authorize_concept_locked(learner, concept):
    """Recheck route, earlier confirmations, prerequisites and content at use."""
    import concept_authorization as authorization
    item, ctx = current_plan_locked(learner)
    concepts = {c['id']: c for c in ctx['curriculum']['concepts']}
    order = [s['concept'] for s in item['plan']['steps'] if s['kind'] == 'introduce']
    if concept not in concepts or concept not in order:
        raise EvidenceError('概念不在当前路线')
    authorization.check(concept, learner)
    required = set(order[:order.index(concept)]) | set(concepts[concept]['hard_prerequisites'])
    for prerequisite in required:
        if not confirmed_locked(learner, prerequisite, item):
            raise EvidenceError('先前概念证据或家长确认无效: ' + prerequisite)
    return {'allowed': concept, 'plan_sha256': item['plan_sha256']}


def confirm_dynamic(learner, concept, synthetic_confirmation=False):
    import concept_authorization as authorization
    import sigma_plan_store as plans
    if not synthetic_confirmation or not authorization.synthetic_learner(learner):
        raise EvidenceError('仅接受显式标记的合成模拟确认')
    folder = get_folder(learner)
    with (coach.ROOT / '.publication.lock').open('a') as publication, (folder / '.lock').open('a') as lock:
        fcntl.flock(publication, fcntl.LOCK_SH); fcntl.flock(lock, fcntl.LOCK_EX)
        authorize_concept_locked(learner, concept)
        item, _ = current_plan_locked(learner)
        candidate = dynamic_candidate(learner, already_locked=True, concept=concept)
        if not candidate['candidate']:
            raise EvidenceError('动态证据不足，不能确认')
        if confirmed_locked(learner, concept, item):
            raise EvidenceError('该证据已确认，不能重复确认')
        record = {'concept': concept, 'confirmation': 'synthetic_simulation',
                  'rule_version': candidate['rule_version'], 'evidence_digest': candidate['evidence_digest'],
                  'plan_sha256': item['plan_sha256'], 'confirmed_at': dt.datetime.now(dt.timezone.utc).isoformat()}
        plans.write(confirmation_path(folder, concept), record)
        return record


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('confirm', 'check', 'dynamic-candidate'))
    parser.add_argument('--learner', required=True)
    parser.add_argument('--concept', default='C01')
    parser.add_argument('--synthetic-confirmation', action='store_true')
    args = parser.parse_args()
    try:
        if args.action == 'dynamic-candidate':
            result = dynamic_candidate(args.learner, concept=args.concept)
        elif args.action == 'confirm':
            result = confirm_dynamic(args.learner, args.concept, args.synthetic_confirmation)
        elif args.action == 'check':
            folder = get_folder(args.learner)
            with (coach.ROOT / '.publication.lock').open('a') as pub, (folder / '.lock').open('a') as lock:
                fcntl.flock(pub, fcntl.LOCK_SH); fcntl.flock(lock, fcntl.LOCK_SH)
                result = authorize_concept_locked(args.learner, args.concept)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (EvidenceError, coach.Stop, roadmap.Invalid, OSError, ValueError, KeyError, TypeError) as exc:
        print('停止：' + str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
