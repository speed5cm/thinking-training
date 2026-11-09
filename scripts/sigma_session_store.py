#!/usr/bin/env python3
"""Atomic Sigma session snapshot with synthetic content and progression gates."""
import argparse
import copy
import datetime as dt
import uuid
import fcntl
import json
import os
from pathlib import Path
import sys
import tempfile

import learning_evidence as evidence
import concept_authorization as authorization

class Invalid(ValueError):
    pass

def read_folder(folder):
    """Read with the learner lock already held, or from an atomically replaced file."""
    return read(folder / 'sigma' / 'session-snapshot.json')

def read(path):
    if not path.exists():
        return {'schema_version': 1, 'revision': 0, 'state': {}, 'session': '', 'turns': []}
    obj = json.loads(path.read_text(encoding='utf-8'))
    validate(obj)
    return obj

def validate(obj):
    if (not isinstance(obj, dict) or set(obj) != {'schema_version', 'revision', 'state', 'session', 'turns'}
        or type(obj['schema_version']) is not int or obj['schema_version'] != 1
        or type(obj['revision']) is not int or obj['revision'] < 0
        or not isinstance(obj['state'], dict) or not isinstance(obj['session'], str)
        or not isinstance(obj['turns'], list) or any(not isinstance(t, dict) for t in obj['turns'])):
        raise Invalid('会话快照格式无效')
    if 'planning_basis' in obj['state'] and not isinstance(obj['state']['planning_basis'], dict):
        raise Invalid('planning_basis 必须是对象')

DIMENSIONS = ('accuracy', 'explanation', 'novel_application', 'discrimination')


def utc_now():
    return dt.datetime.now(dt.timezone.utc)

def nonempty(value):
    return isinstance(value, str) and bool(value.strip())


def validate_dimensions(value, question, answer):
    if not isinstance(value, dict) or set(value) != set(DIMENSIONS):
        raise Invalid('评估须记录完整四维评价')
    for dimension, item in value.items():
        if (not isinstance(item, dict) or set(item) != {'status', 'answer_quote', 'wiki_path', 'wiki_quote'}
                or item['status'] not in ('supported', 'not_supported', 'unknown')
                or any(not isinstance(item[k], str) for k in ('answer_quote', 'wiki_path', 'wiki_quote'))):
            raise Invalid('四维评价格式无效')
        if dimension not in question['dimensions'] and item['status'] != 'unknown':
            raise Invalid('未声明考查的维度须为 unknown')
        quote, path, wiki_quote = item['answer_quote'], item['wiki_path'], item['wiki_quote']
        if item['status'] != 'unknown' and (not nonempty(quote) or not nonempty(path) or not nonempty(wiki_quote)):
            raise Invalid('已评价维度必须引用原答和 Wiki 依据')
        if quote and (not nonempty(quote) or quote not in answer):
            raise Invalid('原答引用不匹配')
        if path or wiki_quote:
            if (path not in question['wiki_sources'] or not nonempty(wiki_quote)
                    or wiki_quote not in (authorization.ROOT / path).read_text(encoding='utf-8')):
                raise Invalid('Wiki 依据不匹配')


def validate_observations(value, question, answer, old, support_events):
    """Validate references, not the correctness of Sigma's semantic judgments."""
    if not isinstance(value, dict) or set(value) != {'repetition', 'novel_transfer', 'misconception', 'support_complete'}:
        raise Invalid('缺少语义观察或支持完整性')
    complete = value['support_complete']
    ids = [e['event_id'] for e in support_events]
    question_ids = [e['event_id'] for e in support_events if e.get('question_id') == question['question_id']]
    if (not isinstance(complete, dict) or set(complete) != {'status', 'support_event_ids'}
            or complete['status'] not in ('confirmed', 'unknown')
            or not isinstance(complete['support_event_ids'], list)
            or any(not nonempty(x) for x in complete['support_event_ids'])
            or len(set(complete['support_event_ids'])) != len(complete['support_event_ids'])
            or not set(question_ids) <= set(complete['support_event_ids'])
            or complete['support_event_ids'] != [x for x in ids if x in complete['support_event_ids']]):
        raise Invalid('支持完整性或关联事件无效')
    old_questions = {e.get('question_id'): e for e in old if e.get('type') == 'question'}
    old_answers = {e.get('question_id') for e in old if e.get('type') == 'answer'}
    for name, statuses in (('repetition', ('yes', 'no', 'unknown')),
                           ('novel_transfer', ('yes', 'no', 'unknown')),
                           ('misconception', ('present', 'resolved', 'absent', 'unknown'))):
        item = value[name]
        fields = {'status', 'question_quote', 'answer_quote', 'wiki_path', 'wiki_quote', 'reason', 'related_question_ids'}
        if (not isinstance(item, dict) or set(item) != fields or item['status'] not in statuses
                or any(not isinstance(item[k], str) for k in ('question_quote', 'answer_quote', 'wiki_path', 'wiki_quote', 'reason'))
                or not isinstance(item['related_question_ids'], list)
                or any(not nonempty(x) for x in item['related_question_ids'])
                or len(set(item['related_question_ids'])) != len(item['related_question_ids'])
                or any(x not in old_questions or x == question['question_id'] for x in item['related_question_ids'])):
            raise Invalid('语义观察字段或引用问题无效')
        if item['question_quote'] and item['question_quote'] not in question['text']:
            raise Invalid('语义观察的原题引用不匹配')
        if item['answer_quote'] and item['answer_quote'] not in answer:
            raise Invalid('语义观察的原答引用不匹配')
        if item['wiki_path'] or item['wiki_quote']:
            if (item['wiki_path'] not in question['wiki_sources'] or not nonempty(item['wiki_quote'])
                    or item['wiki_quote'] not in (authorization.ROOT / item['wiki_path']).read_text(encoding='utf-8')):
                raise Invalid('语义观察的 Wiki 引用不匹配')
        if item['status'] != 'unknown':
            if (not nonempty(item['question_quote']) or item['question_quote'] not in question['text']
                    or not nonempty(item['answer_quote']) or item['answer_quote'] not in answer
                    or item['wiki_path'] not in question['wiki_sources'] or not nonempty(item['wiki_quote'])
                    or item['wiki_quote'] not in (authorization.ROOT / item['wiki_path']).read_text(encoding='utf-8')
                    or not nonempty(item['reason'])):
                raise Invalid('语义观察须关联原题、原答和 Wiki 依据')
        if ((name == 'repetition' and item['status'] == 'yes')
                or (name == 'novel_transfer' and item['status'] == 'yes')
                or (name == 'misconception' and item['status'] == 'resolved')):
            if not item['related_question_ids'] or any(x not in old_answers for x in item['related_question_ids']):
                raise Invalid('该语义判断须引用此前已作答的问题')
        if name == 'misconception' and item['status'] == 'resolved':
            effective = {}
            for event in old:
                prior_qid = event.get('question_id')
                if prior_qid not in item['related_question_ids']:
                    continue
                if event.get('type') == 'analysis':
                    effective[prior_qid] = event.get('analysis', {}).get('observations', {}).get('misconception', {}).get('status')
                elif event.get('type') == 'correction':
                    effective[prior_qid] = event.get('replacement', {}).get('observations', {}).get('misconception', {}).get('status')
                elif event.get('type') in ('invalidation', 'interruption'):
                    effective[prior_qid] = None
            prior_present = 'present' in effective.values()
            if not prior_present:
                raise Invalid('解决关键混淆须关联已记录的混淆')


def lifecycle(previous, current):
    added = current['turns'][len(previous['turns']):]
    kinds = {'session_start', 'session_end', 'session_resume'}
    if not any(e.get('type') in kinds for e in added):
        if current['session'] != previous['session']:
            raise Invalid('session 由存储程序维护')
        return False
    if len(added) != 1 or set(added[0]) != {'type'} or current['session'] != previous['session'] or current['state'] != previous['state']:
        raise Invalid('会话边界须单独提交，不能指定 ID 或时间')
    kind = added[0]['type']
    events = [e for e in previous['turns'] if e.get('type') in kinds]
    if kind == 'session_start':
        if events:
            raise Invalid('已有会话历史，须先结束再恢复')
    elif kind == 'session_end':
        if not events or events[-1]['type'] not in ('session_start', 'session_resume') or previous['session'] != events[-1].get('session_id'):
            raise Invalid('没有可结束的活动会话')
        questions = {e.get('question_id') for e in previous['turns'] if e.get('type') == 'question'}
        closed = {e.get('question_id') for e in previous['turns'] if e.get('type') in ('answer', 'invalidation')}
        if questions - closed:
            raise Invalid('未答问题须先恢复或处理，不能结束会话')
    elif kind == 'session_resume':
        if not events or events[-1]['type'] != 'session_end' or previous['session']:
            raise Invalid('须先结束上一次会话才能恢复')
    return True


def validate_new_events(previous, current, auth, blocked):
    """Validate the new tail against committed questions, preserving old history."""
    old = previous['turns']
    added = current['turns'][len(old):]
    if not added:
        return
    if any(e.get('type') in ('session_start', 'session_end', 'session_resume') for e in added):
        return
    # An emergency save is strictly answer + interruption, without state changes.
    emergency = blocked is not None
    if emergency:
        if (current['state'] != previous['state'] or current['session'] != previous['session']
                or len(added) != 2 or [e.get('type') for e in added] != ['answer', 'interruption']):
            raise Invalid('授权失效后只能保存原答和中断记录')
    committed_questions = {e.get('question_id'): e for e in old if e.get('type') == 'question'}
    if len(committed_questions) != sum(e.get('type') == 'question' for e in old):
        raise Invalid('旧记录问题 ID 重复，须人工核对')
    questions = dict(committed_questions)
    answered = {e.get('question_id') for e in old if e.get('type') == 'answer'}
    interrupted = {e.get('question_id') for e in old if e.get('type') == 'interruption'}
    analyses = {e.get('question_id') for e in old if e.get('type') == 'analysis'}
    invalidated = {e.get('question_id') for e in old if e.get('type') == 'invalidation'}
    pending = set(questions) - answered - invalidated
    if len(pending) > 1:
        raise Invalid('存在多个未答问题，须人工核对')
    batch_answers = set()
    event_ids = {e.get('event_id') for e in old if e.get('event_id') is not None}
    for event in added:
        kind = event.get('type')
        qid = event.get('question_id')
        if not nonempty(qid):
            raise Invalid('事件须关联问题 ID')
        if kind == 'question':
            required = {'type', 'concept', 'session_id', 'question_id', 'purpose', 'text', 'wiki_sources', 'authorization_sha256'}
            optional = {'review_task_id', 'context', 'dimensions', 'answer_basis', 'practice'}
            if (not required <= set(event) or set(event) - required - optional or qid in questions or pending
                    or event['concept'] != auth['concept'] or event['purpose'] not in ('teaching', 'assessment')
                    or not nonempty(event['session_id']) or event['session_id'] != previous['session'] or not nonempty(event['text'])
                    or event['authorization_sha256'] != auth['authorization_sha256']):
                raise Invalid('问题字段、用途、授权或顺序无效')
            if 'review_task_id' in event and not nonempty(event['review_task_id']):
                raise Invalid('复习任务 ID 无效')
            sources = event['wiki_sources']
            basis = authorization.concept_basis(event['concept'])
            required_sources = basis['required_sources']
            if (not isinstance(sources, dict) or not required_sources <= set(sources)
                    or not set(sources) <= set(basis['files'])):
                raise Invalid('Wiki 来源不完整或未授权')
            for path, digest in sources.items():
                if not isinstance(digest, str) or digest != evidence.coach.digest(authorization.ROOT / path):
                    raise Invalid('Wiki 来源摘要不匹配')
            if event['purpose'] == 'assessment':
                dimensions = event.get('dimensions')
                if (not nonempty(event.get('context')) or not nonempty(event.get('answer_basis'))
                        or not isinstance(dimensions, list) or not dimensions
                        or any(d not in DIMENSIONS for d in dimensions) or len(set(dimensions)) != len(dimensions)
                        or type(event.get('practice')) is not bool):
                    raise Invalid('评估题须声明情境、维度、判断依据及实践用途')
            questions[qid] = event
            pending.add(qid)
            continue
        if kind not in ('answer', 'analysis', 'support', 'interruption', 'correction', 'invalidation'):
            raise Invalid('新事件类型无效')
        if kind in ('support', 'correction', 'invalidation'):
            event_id = event.get('event_id')
            if not nonempty(event_id) or event_id in event_ids:
                raise Invalid('事件 ID 缺失或重复')
            event_ids.add(event_id)
        # A question must have been saved in an earlier revision before any response.
        if qid not in committed_questions or event.get('session_id') != committed_questions[qid].get('session_id'):
            raise Invalid('事件必须关联先前提交的唯一问题及会话')
        question = committed_questions[qid]
        if kind in ('support', 'answer', 'analysis') and event['session_id'] != previous['session'] and blocked != 'legacy_session_unverified':
            raise Invalid('问题不属于当前活动会话')
        if kind in ('support', 'answer', 'analysis', 'correction') and qid in invalidated | interrupted:
            raise Invalid('已中断或失效的问题不得继续教学或评价')
        if kind in ('support', 'answer', 'analysis', 'correction') and not emergency:
            if question.get('authorization_sha256') != auth['authorization_sha256']:
                raise Invalid('问题依据或授权已变化，须停止并重新核对')
        if kind == 'support':
            if (set(event) != {'type', 'session_id', 'question_id', 'event_id', 'kind', 'text'} or qid in answered
                    or event['kind'] not in ('hint', 'example', 'demonstration', 'clarification', 'other')
                    or not nonempty(event['text'])):
                raise Invalid('支持记录无效')
        elif kind == 'answer':
            if set(event) != {'type', 'session_id', 'question_id', 'text'} or not isinstance(event['text'], str) or qid in answered or qid not in pending:
                raise Invalid('原答无效或重复')
            answered.add(qid); pending.discard(qid); batch_answers.add(qid)
        elif kind == 'analysis':
            if set(event) != {'type', 'session_id', 'question_id', 'analysis'} or qid not in batch_answers or qid in analyses:
                raise Invalid('分析须与首次回答同次提交')
            analysis = event['analysis']
            if not isinstance(analysis, dict) or not analysis:
                raise Invalid('分析须为非空对象')
            if question.get('purpose') == 'assessment':
                if set(analysis) != {'dimensions', 'observations'}:
                    raise Invalid('评估分析须包含四维及语义观察')
                answer = next(e['text'] for e in added if e.get('type') == 'answer' and e.get('question_id') == qid)
                validate_dimensions(analysis['dimensions'], question, answer)
                supports = [e for e in old + added if e.get('type') == 'support']
                validate_observations(analysis['observations'], question, answer, old, supports)
                if analysis['dimensions']['novel_application']['status'] == 'supported' and analysis['observations']['novel_transfer']['status'] != 'yes':
                    raise Invalid('陌生应用成立须有陌生迁移观察及依据')
            analyses.add(qid)
        elif kind == 'interruption':
            if (not emergency or set(event) != {'type', 'session_id', 'question_id', 'reason'}
                    or qid not in batch_answers or event['reason'] != blocked):
                raise Invalid('中断记录无效')
            interrupted.add(qid)
        elif kind == 'invalidation':
            if set(event) != {'type', 'session_id', 'question_id', 'event_id', 'reason'} or not nonempty(event['reason']) or qid in invalidated:
                raise Invalid('失效记录无效或重复')
            invalidated.add(qid); pending.discard(qid)
        elif kind == 'correction':
            if (set(event) != {'type', 'session_id', 'question_id', 'event_id', 'reason', 'replacement'}
                    or qid not in analyses or qid in invalidated or not nonempty(event['reason'])
                    or question.get('purpose') != 'assessment'
                    or not isinstance(event['replacement'], dict) or set(event['replacement']) != {'dimensions', 'observations'}):
                raise Invalid('更正须关联评估并提供依据及完整四维')
            answers = [e['text'] for e in old if e.get('type') == 'answer' and e.get('question_id') == qid]
            if len(answers) != 1:
                raise Invalid('更正缺少唯一原答')
            validate_dimensions(event['replacement']['dimensions'], question, answers[0])
            supports = [e for e in old if e.get('type') == 'support']
            validate_observations(event['replacement']['observations'], question, answers[0], old, supports)
            if event['replacement']['dimensions']['novel_application']['status'] == 'supported' and event['replacement']['observations']['novel_transfer']['status'] != 'yes':
                raise Invalid('陌生应用成立须有陌生迁移依据')
    if emergency:
        if added[0]['question_id'] != added[1]['question_id'] or added[0]['session_id'] != added[1]['session_id']:
            raise Invalid('原答和中断记录必须关联同一问题')
    elif batch_answers - analyses:
        raise Invalid('每个回答须在同次提交中保存分析')


def operate(learner, proposed=None, expected=None):
    folder = evidence.get_folder(learner)
    dest = folder / 'sigma'
    dest.mkdir(mode=0o700, exist_ok=True)
    path = dest / 'session-snapshot.json'
    with (evidence.coach.ROOT / '.publication.lock').open('a') as pub, (folder / '.lock').open('a') as lock:
        fcntl.flock(pub, fcntl.LOCK_SH)
        fcntl.flock(lock, fcntl.LOCK_EX)
        previous = read_folder(folder)
        if proposed is None:
            return previous
        if type(expected) is not int or expected != previous['revision']:
            raise Invalid('会话已被更新，请重新读取后重试')
        if not isinstance(proposed, dict) or set(proposed) != {'state', 'session', 'turns'}:
            raise Invalid('提交须同时包含 state、session、turns')
        current = {'schema_version': 1, 'revision': expected + 1, **proposed}
        validate(current)
        # Previously committed turns must remain byte-for-byte equivalent in JSON data.
        if current['turns'][:len(previous['turns'])] != previous['turns']:
            raise Invalid('不能覆盖已提交的逐轮记录')
        added = current['turns'][len(previous['turns']):]
        if any('recorded_at' in e for e in added):
            raise Invalid('事件时间由存储程序生成')
        is_lifecycle = lifecycle(previous, current)
        legacy_answer = False
        if added and not is_lifecycle:
            events = [e for e in previous['turns'] if e.get('type') in ('session_start', 'session_end', 'session_resume')]
            if not events and added[0].get('type') == 'answer':
                # A pending pre-contract question can only be preserved as interrupted.
                legacy_answer = any(e.get('type') == 'question' and e.get('question_id') == added[0].get('question_id')
                                    for e in previous['turns'])
            elif not events or events[-1]['type'] not in ('session_start', 'session_resume') or previous['session'] != events[-1].get('session_id'):
                raise Invalid('须先开始或恢复活动会话')
        auth = None
        blocked = None
        if added:
            try:
                first = added[0]
                if is_lifecycle:
                    if not authorization.synthetic_learner(learner):
                        raise authorization.Invalid('仅支持隔离合成学习者')
                    prior_questions = [e for e in previous['turns'] if e.get('type') == 'question']
                    concept = prior_questions[-1].get('concept') if prior_questions else None
                elif first.get('type') == 'question':
                    concept = first.get('concept')
                else:
                    matches = [e for e in previous['turns'] if e.get('type') == 'question'
                               and e.get('question_id') == first.get('question_id')]
                    concept = matches[0].get('concept') if len(matches) == 1 else None
                auth = authorization.check(concept, learner) if concept is not None else None
                # Reauthorization after a question cannot retroactively authorize its answer.
                if added[0].get('type') == 'answer':
                    matches = [e for e in previous['turns'] if e.get('type') == 'question' and e.get('question_id') == added[0].get('question_id')]
                    if len(matches) == 1 and matches[0].get('authorization_sha256') != auth['authorization_sha256']:
                        blocked = 'authorization_or_content_changed'
            except (authorization.Invalid, evidence.EvidenceError, evidence.coach.Stop, OSError, ValueError, TypeError, KeyError):
                blocked = 'authorization_or_content_changed'
            if not blocked and first.get('type') in ('question', 'support', 'answer', 'analysis'):
                try:
                    evidence.authorize_concept_locked(learner, concept)
                except (authorization.Invalid, evidence.EvidenceError, evidence.coach.Stop, OSError, ValueError, TypeError, KeyError) as exc:
                    raise Invalid('路线、先修或概念门禁不可用: ' + str(exc)) from exc
        if legacy_answer:
            blocked = 'legacy_session_unverified'
        if blocked and is_lifecycle:
            raise Invalid('授权不可用，不能开始、结束或恢复会话')
        if blocked and not authorization.synthetic_learner(learner):
            raise Invalid('中断保存仅适用于隔离合成测试')
        validate_new_events(previous, current, auth, blocked)
        current = copy.deepcopy(current)
        if added:
            recorded_at = utc_now()
            prior_times = [e['recorded_at'] for e in previous['turns'] if 'recorded_at' in e]
            if prior_times:
                prior = dt.datetime.fromisoformat(prior_times[-1])
                if prior.tzinfo is None or recorded_at < prior:
                    raise Invalid('系统时钟倒退或历史时间无效')
            for event in current['turns'][len(previous['turns']):]:
                event['recorded_at'] = recorded_at.isoformat()
            if is_lifecycle:
                boundary = current['turns'][-1]
                if boundary['type'] in ('session_start', 'session_resume'):
                    boundary['session_id'] = str(uuid.uuid4())
                    if any(e.get('session_id') == boundary['session_id'] for e in previous['turns']):
                        raise Invalid('生成的会话 ID 重复')
                    if boundary['type'] == 'session_resume':
                        boundary['previous_session_id'] = next(e['session_id'] for e in reversed(previous['turns']) if e.get('type') == 'session_end')
                    current['session'] = boundary['session_id']
                else:
                    boundary['session_id'] = previous['session']
                    current['session'] = ''
        fd, temp = tempfile.mkstemp(dir=dest, prefix='.session-')
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(current, f, ensure_ascii=False, indent=2)
                f.write('\n'); f.flush(); os.fsync(f.fileno())
            os.replace(temp, path)
            directory = os.open(dest, os.O_RDONLY)
            try: os.fsync(directory)
            finally: os.close(directory)
        finally:
            if os.path.exists(temp): os.unlink(temp)
        return current

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('read', 'commit'))
    parser.add_argument('--learner', required=True)
    parser.add_argument('--expected-revision', type=int)
    args = parser.parse_args()
    try:
        result = operate(args.learner, json.load(sys.stdin), args.expected_revision) if args.action == 'commit' else operate(args.learner)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (Invalid, authorization.Invalid, evidence.EvidenceError, evidence.coach.Stop, OSError, ValueError, TypeError) as exc:
        print('停止：' + str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
