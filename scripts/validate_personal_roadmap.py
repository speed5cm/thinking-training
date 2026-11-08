#!/usr/bin/env python3
"""Validate an AI-authored planning proposal; never authorize or start teaching."""
import argparse
import fcntl
import hashlib
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import generate_roadmap as base
import learning_evidence as evidence
import sigma_session_store as sigma_session

class Invalid(ValueError):
    pass

def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode()).hexdigest()

def context(learner, already_locked=False):
    if not already_locked:
        folder = evidence.get_folder(learner)
        with (evidence.coach.ROOT / '.publication.lock').open('a') as publication, (folder / '.lock').open('a') as lock:
            fcntl.flock(publication, fcntl.LOCK_SH)
            fcntl.flock(lock, fcntl.LOCK_SH)
            return context(learner, already_locked=True)
    curriculum = base.build()
    assessment = evidence.assess(learner, already_locked=already_locked)
    recommendation = evidence.recommend(learner, already_locked=already_locked)
    # Bind full Wiki text and pedagogy, not just extracted metadata.
    paths = ['wiki/index.md', 'curriculum/12-week-plan.md', 'references/pedagogy.md', 'references/sources.md']
    paths += [c['wiki_page'] for c in curriculum['concepts']]
    contents = {p: (ROOT / p).read_text(encoding='utf-8') for p in paths}
    folder = evidence.get_folder(learner)
    # Raw coach events include routine questions and answers. Formal evidence and
    # parent confirmation are bound independently; transient activity is not a
    # reason to invalidate the whole plan.
    names = ('planner-profile.md', 'evidence.jsonl', 'mastery-confirmation.json')
    learner_files = {name: (folder / name).read_text(encoding='utf-8') if (folder / name).is_file() else None for name in names}
    # Bind tutor decisions when present without invalidating existing plans with no tutor data.
    tutor = folder / 'tutor-state.json'
    if tutor.exists():
        learner_files['tutor-state.json'] = tutor.read_text(encoding='utf-8')
    sigma = folder / 'sigma'
    if sigma.exists():
        snapshot = sigma_session.read_folder(folder)
        basis = snapshot['state'].get('planning_basis')
        if basis is not None:
            learner_files['sigma/planning_basis'] = basis
    return {'curriculum': curriculum, 'curriculum_digest': digest(contents),
            'learner_digest': digest(learner_files),
            'evidence_digest': assessment['evidence_digest'], 'assessment': assessment,
            'current_recommendation': recommendation}

def validate(plan, ctx, learner):
    if not isinstance(plan, dict) or set(plan) != {'schema_version', 'learner', 'curriculum_digest', 'evidence_digest', 'learner_digest', 'steps', 'gaps', 'revision_suggestions'}:
        raise Invalid('规划顶层字段不符合约定')
    if type(plan['schema_version']) is not int or plan['schema_version'] != 1 or plan['learner'] != learner:
        raise Invalid('版本或化名不匹配')
    if plan['curriculum_digest'] != ctx['curriculum_digest'] or plan['evidence_digest'] != ctx['evidence_digest'] or plan['learner_digest'] != ctx['learner_digest']:
        raise Invalid('Wiki 或学习证据已变化，须重新规划')
    items = {c['id']: c for c in ctx['curriculum']['concepts']}
    if not isinstance(plan['steps'], list) or not plan['steps']:
        raise Invalid('步骤不能为空')
    seen = set()
    for step in plan['steps']:
        if not isinstance(step, dict) or set(step) != {'kind', 'concept', 'reason', 'wiki_pages'}:
            raise Invalid('步骤字段无效')
        cid, kind = step['concept'], step['kind']
        if not isinstance(cid, str) or cid not in items or kind not in ('introduce', 'review', 'interleave'):
            raise Invalid('未知概念或步骤类型')
        c = items[cid]
        if not isinstance(step['reason'], str) or not step['reason'].strip():
            raise Invalid(f'{cid}: 缺少依据')
        pages = step['wiki_pages']
        if not isinstance(pages, list) or not pages or any(not isinstance(p, str) for p in pages) or len(pages) != len(set(pages)):
            raise Invalid(f'{cid}: Wiki 引用无效')
        allowed = {x['wiki_page'] for x in items.values()}
        if c['wiki_page'] not in pages or not set(pages) <= allowed:
            raise Invalid(f'{cid}: 必须引用本概念页且不能引用未知页')
        if kind == 'introduce':
            if cid in seen or not set(c['hard_prerequisites']) <= seen:
                raise Invalid(f'{cid}: 重复或硬先修未先列入路线')
            seen.add(cid)
        elif cid not in seen:
            raise Invalid(f'{cid}: 复习或穿插须先列入概念')
    if seen != set(items):
        raise Invalid('须覆盖所有课程概念')
    for key in ('gaps', 'revision_suggestions'):
        if not isinstance(plan[key], list) or any(not isinstance(x, str) or not x.strip() for x in plan[key]):
            raise Invalid(f'{key} 必须是非空文本组成的列表')
    return {'valid': True, 'notice': '仅验证规划结构和快照，不验证语义或授予教学许可；先修排列不等于掌握。',
            'current_recommendation': ctx['current_recommendation']}

def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('action', choices=['context', 'validate'])
    p.add_argument('--learner', required=True)
    p.add_argument('--plan', type=Path)
    args = p.parse_args()
    try:
        ctx = context(args.learner)
        if args.action == 'context':
            result = ctx
        else:
            if args.plan is None:
                raise Invalid('validate 需要 --plan')
            result = validate(json.loads(args.plan.read_text(encoding='utf-8')), ctx, args.learner)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (Invalid, base.Invalid, evidence.EvidenceError, evidence.coach.Stop, OSError, ValueError, KeyError, TypeError) as exc:
        print('停止：' + str(exc), file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
