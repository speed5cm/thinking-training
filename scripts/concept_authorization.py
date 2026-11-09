#!/usr/bin/env python3
"""Synthetic concept content authorization. No authority to approve human records."""
import argparse
import fcntl
import json
import os
from pathlib import Path
import re
import sys
import tempfile

import learning_evidence as evidence

ROOT = Path(__file__).resolve().parents[1]
FILES = ('wiki/index.md', 'wiki/concepts/observation-vs-inference.md',
         'curriculum/12-week-plan.md', 'references/sources.md', 'references/pedagogy.md',
         'question-bank/original-examples.md', 'pilot-c01-c02/wiki/index.md',
         'pilot-c01-c02/wiki/overview.md', 'pilot-c01-c02/wiki/concepts/C01.md',
         'pilot-c01-c02/wiki/sources/project-research.md')
RECORD = 'pilot-c01-c02/concept-authorizations/C01.json'
C02_FILES = tuple('wiki/concepts/attribute-comparison.md' if p == 'wiki/concepts/observation-vs-inference.md' else 'pilot-c01-c02/wiki/concepts/C02.md' if p == 'pilot-c01-c02/wiki/concepts/C01.md' else p for p in FILES)

class Invalid(ValueError):
    pass

def synthetic_learner(learner):
    return isinstance(learner, str) and bool(re.fullmatch(r'synthetic(?:[-_][A-Za-z0-9_-]+)?', learner))

def concept_basis(concept):
    """Derive the required sources from the indexed curriculum, never from a card."""
    if not isinstance(concept, str) or not re.fullmatch(r'C\d{2}', concept):
        raise Invalid('概念编号无效')
    index = (ROOT / 'wiki/index.md').read_text(encoding='utf-8')
    matches = re.findall(r'^\| ' + re.escape(concept) + r' \| \[\[concepts/([^\]]+)\]\]', index, re.M)
    if len(matches) != 1 or not re.fullmatch(r'[A-Za-z0-9_-]+', matches[0]):
        raise Invalid('概念不在 Wiki 索引或索引不唯一')
    page = 'wiki/concepts/' + matches[0] + '.md'
    text = (ROOT / page).read_text(encoding='utf-8')
    if not re.search(r'^# ' + re.escape(concept) + r'\s', text, re.M):
        raise Invalid('概念页编号不匹配')
    goal = re.search(r'\*\*掌握判据\*\*：([^\n]+)', text)
    source = re.search(r'\*\*来源索引\*\*：([^\n]+)', text)
    definition = re.search(r'\*\*概念定义（项目原创表述）\*\*：([^\n]+)', text)
    pilot = 'pilot-c01-c02/wiki/concepts/' + concept + '.md'
    if (ROOT / pilot).is_file():
        # Preserve the established authorization contract for existing pilot pages.
        files = [p for p in FILES if p not in (FILES[1], 'pilot-c01-c02/wiki/concepts/C01.md')]
        files.insert(1, page)
        files.insert(-1, pilot)
        scope = re.search(r'## Core Thesis\s*\n([^\n]+)', (ROOT / pilot).read_text(encoding='utf-8'))
        required_sources = {page, pilot}
    else:
        files = ['wiki/index.md', page, 'curriculum/12-week-plan.md',
                 'references/sources.md', 'references/pedagogy.md']
        scope = definition
        required_sources = {page}
    if not goal or not source or not scope:
        raise Invalid('概念目标、范围或来源缺失')
    sources = re.findall(r'R\d\d', source.group(1))
    if not sources:
        raise Invalid('概念来源缺失')
    return {'files': files, 'required_sources': required_sources, 'goal': goal.group(1).strip(),
            'scope': scope.group(1).strip(), 'sources': sources}

def check(concept, learner):
    """Caller holds the shared publication lock through use; only synthetic records count."""
    if not synthetic_learner(learner):
        raise Invalid('概念授权仅适用于隔离合成测试')
    basis = concept_basis(concept)
    files = basis['files']
    record = evidence.coach.json_read(ROOT / ('pilot-c01-c02/concept-authorizations/' + concept + '.json'))
    required = {'schema_version', 'concept', 'version', 'review', 'status', 'teaching_goal', 'scope', 'sources', 'content_sha256'}
    if (not isinstance(record, dict) or set(record) != required or type(record['schema_version']) is not int
            or record['schema_version'] != 1 or record['concept'] != concept
            or not isinstance(record['version'], str) or not re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9._-]{0,63}', record['version'])
            or '..' in record['version']):
        raise Invalid('概念授权记录不完整')
    review = record['review']
    if (not isinstance(review, dict) or set(review) != {'kind', 'actor', 'basis'}
            or review['kind'] != 'synthetic_simulation'
            or any(not isinstance(review[k], str) or not review[k].strip() for k in ('actor', 'basis'))):
        raise Invalid('仅接受明确标记的合成模拟审核；真实人工审核身份尚无可信验证')
    if record['status'] != 'active':
        raise Invalid('概念授权未生效或已撤销')
    hashes = record['content_sha256']
    if not isinstance(hashes, dict) or set(hashes) != set(files):
        raise Invalid('授权内容或来源不完整')
    for rel in files:
        path = ROOT / rel
        if not isinstance(hashes[rel], str) or not re.fullmatch(r'[0-9a-f]{64}', hashes[rel]) or evidence.coach.digest(path) != hashes[rel]:
            raise Invalid('授权内容已变化：' + rel)
    if record['teaching_goal'] != basis['goal'] or record['scope'] != basis['scope']:
        raise Invalid('教学目标或范围依据缺失')
    if record['sources'] != basis['sources']:
        raise Invalid('来源依据缺失')
    return {'concept': concept, 'version': record['version'], 'review_kind': review['kind'], 'status': 'active',
            'authorization_sha256': evidence.evidence_digest([record])}

def revoke(concept='C01'):
    """Revoke an existing simulated record; never create or approve one."""
    concept_basis(concept)
    path = ROOT / ('pilot-c01-c02/concept-authorizations/' + concept + '.json')
    with (evidence.coach.ROOT / '.publication.lock').open('a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        record = evidence.coach.json_read(path)
        if not isinstance(record, dict) or record.get('concept') != concept or record.get('status') != 'active' or not isinstance(record.get('review'), dict) or record['review'].get('kind') != 'synthetic_simulation':
            raise Invalid('没有可撤销的合成授权')
        record['status'] = 'revoked'
        fd, temp = tempfile.mkstemp(dir=path.parent, prefix='.concept-')
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                json.dump(record, f, ensure_ascii=False, indent=2); f.write('\n'); f.flush(); os.fsync(f.fileno())
            os.replace(temp, path)
            fd = os.open(path.parent, os.O_RDONLY)
            try: os.fsync(fd)
            finally: os.close(fd)
        finally:
            if os.path.exists(temp): os.unlink(temp)
    return {'concept': concept, 'status': 'revoked', 'review_kind': 'synthetic_simulation'}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('check', 'revoke'))
    parser.add_argument('--learner')
    parser.add_argument('--concept', default='C01')
    args = parser.parse_args()
    try:
        if args.action == 'revoke': result = revoke(args.concept)
        else:
            with (evidence.coach.ROOT / '.publication.lock').open('a') as lock:
                fcntl.flock(lock, fcntl.LOCK_SH)
                result = check(args.concept, args.learner)
        print(json.dumps(result, ensure_ascii=False))
    except (Invalid, evidence.coach.Stop, OSError, ValueError, TypeError, KeyError) as exc:
        print('停止：' + str(exc), file=sys.stderr); return 1
    return 0

if __name__ == '__main__': sys.exit(main())
