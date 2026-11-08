#!/usr/bin/env python3
"""Build a conservative, static curriculum projection from the root Wiki."""
import argparse
import html
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ABILITIES = {'观察分析', '逻辑推理', '批判性思考', '创造性思维', '独立解决/元认知', '语言表达'}
DOMAINS = ABILITIES

class Invalid(ValueError):
    pass

def build(root=ROOT):
    root = Path(root)
    wiki = root / 'wiki'
    index = (wiki / 'index.md').read_text(encoding='utf-8')
    rows = re.findall(r'^\| (C\d{2}) \| \[\[concepts/([^\]]+)\]\][^|]*\|[^|]*\|([^|]*)\|', index, re.M)
    entries = [(cid, slug) for cid, slug, _ in rows]
    index_dependencies = {cid: set(re.findall(r'C\d{2}', deps)) for cid, _, deps in rows}
    if len(entries) != 14 or set(x[0] for x in entries) != {f'C{i:02}' for i in range(1, 15)} or len(set(x[1] for x in entries)) != 14:
        raise Invalid('Wiki 索引必须唯一列出 C01—C14')
    pages = list((wiki / 'concepts').glob('*.md'))
    if {p.stem for p in pages} != {slug for _, slug in entries}:
        raise Invalid('概念页与索引不一致（缺失或未收录）')
    source_text = (root / 'references/sources.md').read_text(encoding='utf-8')
    sources = set(re.findall(r'^## (R\d\d)\b', source_text, re.M))
    slug_to_id = {slug: cid for cid, slug in entries}
    concepts = []
    for cid, slug in entries:
        path = wiki / 'concepts' / (slug + '.md')
        text = path.read_text(encoding='utf-8')
        def one(pattern, label):
            match = re.search(pattern, text, re.M | re.S)
            if not match or not match.group(1).strip():
                raise Invalid(f'{cid}: 缺少 {label}')
            return match.group(1).strip()
        name = one(r'^# (C\d{2} [^\n]+)', '标题')
        if not name.startswith(cid + ' ') or one(r'\*\*知识点编号\*\*：([^\n]+)', 'ID') != cid:
            raise Invalid(f'{cid}: ID 不一致')
        meta = json.loads(one(r'<!-- roadmap-metadata\s*(\{.*?\})\s*-->', '结构化映射'))
        if set(meta) != {'abilities', 'hard_prerequisites', 'interleavable'}:
            raise Invalid(f'{cid}: 映射字段无效')
        for key in meta:
            if not isinstance(meta[key], list) or any(not isinstance(x, str) for x in meta[key]) or len(meta[key]) != len(set(meta[key])):
                raise Invalid(f'{cid}: {key} 无效')
        if not meta['abilities'] or not set(meta['abilities']) <= ABILITIES:
            raise Invalid(f'{cid}: 能力领域无效')
        hard, inter = meta['hard_prerequisites'], meta['interleavable']
        if set(hard) & set(inter) or any(x not in slug_to_id.values() or x == cid for x in hard + inter):
            raise Invalid(f'{cid}: 依赖无效或缺失')
        old_links = re.findall(r'\[\[concepts/([^\]]+)\]\]', one(r'^- \*\*先修\*\*：([^\n]+)', '先修'))
        if (any(x not in slug_to_id for x in old_links) or
                {slug_to_id[x] for x in old_links} != set(hard + inter) or
                index_dependencies[cid] != set(hard + inter)):
            raise Invalid(f'{cid}: 结构化关系与 Wiki 先修不一致')
        source_ids = re.findall(r'R\d\d', one(r'\*\*来源索引\*\*：([^\n]+)', '来源'))
        if not source_ids or not set(source_ids) <= sources:
            raise Invalid(f'{cid}: 来源索引无效')
        goal = one(r'\*\*掌握判据\*\*：([^\n]+)', '教学目标')
        concepts.append({'id': cid, 'name': name[4:], 'wiki_page': str(path.relative_to(root)), 'source_registry': 'references/sources.md', 'sources': source_ids, 'teaching_goal': goal, **meta})
    if not DOMAINS <= {a for c in concepts for a in c['abilities']}:
        raise Invalid('六项能力覆盖不完整')
    # Topological reachability from all hard-dependency roots; soft edges do not block.
    reached = set()
    while True:
        ready = {c['id'] for c in concepts if set(c['hard_prerequisites']) <= reached} - reached
        if not ready:
            break
        reached |= ready
    if len(reached) != len(concepts):
        raise Invalid('循环依赖或不可达路径: ' + ', '.join(sorted(set(slug_to_id.values()) - reached)))
    # Reuse the existing pilot gate; this is a snapshot, not authorization to teach.
    spec = importlib.util.spec_from_file_location('pilot_coach', root / 'pilot-c01-c02/scripts/coach.py')
    coach = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(coach)
    for c in concepts:
        cid = c['id']
        c['published_cards'] = []
        c['teaching_status'] = 'blocked_no_published_card'
        if cid in ('C01', 'C02'):
            try:
                coach.gate(cid)
                for qid in coach.MODES[cid]:
                    card, sha = coach.load_card(qid, cid)
                    c['published_cards'].append({'id': qid, 'version': card['version'], 'sha256': sha})
                c['teaching_status'] = 'pilot_published'
            except (coach.Stop, OSError, ValueError, KeyError, TypeError):
                c['published_cards'] = []
                c['teaching_status'] = 'blocked_pilot_gate'
        c['formal_teaching_available'] = c['teaching_status'] == 'pilot_published'
    return {'schema_version': 1, 'authority': 'wiki/index.md and wiki/concepts/*.md', 'notice': '静态快照；正式教学前须重新执行现有试点门禁和家长陪同流程。可用不表示先修已掌握。', 'ability_domains': sorted(DOMAINS), 'concepts': concepts}

def render(data):
    esc = lambda x: html.escape(str(x), quote=True)
    cards = []
    for c in data['concepts']:
        dep = lambda key: '、'.join(c[key]) or '无'
        state = '试点题卡已发布（须现场再验）' if c['formal_teaching_available'] else '不可进入正式教学'
        cards.append(f'<article><h2>{esc(c["id"])} · {esc(c["name"])}</h2><strong class="{"ready" if c["formal_teaching_available"] else "blocked"}">{state}</strong><p>硬性先修：{esc(dep("hard_prerequisites"))}；可穿插：{esc(dep("interleavable"))}</p><p>能力：{esc("、".join(c["abilities"]))}</p><p>目标：{esc(c["teaching_goal"])}</p><p>来源：{esc("、".join(c["sources"]))} · <a href="../{esc(c["wiki_page"])}">概念 Wiki</a></p></article>')
    return '<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>思维能力 Roadmap</title><style>body{font:16px/1.6 system-ui,sans-serif;max-width:1050px;margin:auto;padding:1.5rem;color:#172a35;background:#f3f6f6} main{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,300px),1fr));gap:1rem} article{background:white;border:1px solid #d1dcdc;border-radius:10px;padding:1rem} h2{font-size:1.1rem;margin:0 0 .5rem}.ready{color:#14644e}.blocked{color:#9a3c21} p{margin:.5rem 0}</style></head><body><h1>思维能力 Roadmap</h1><p>' + esc(data['notice']) + '</p><p>硬性先修用于完整概念学习；可穿插关系不阻断早期练习。12 周计划仅供参考。</p><main>' + ''.join(cards) + '</main></body></html>\n'

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--check', action='store_true', help='验证 Wiki 与已生成文件是否一致，不写入')
    args = parser.parse_args()
    try:
        data = build()
        outputs = {ROOT / 'roadmap/roadmap.json': json.dumps(data, ensure_ascii=False, indent=2) + '\n', ROOT / 'roadmap/roadmap.html': render(data)}
        if args.check:
            for path, content in outputs.items():
                if not path.is_file() or path.read_text(encoding='utf-8') != content:
                    raise Invalid(f'生成文件缺失或过期: {path}')
        else:
            for path, content in outputs.items():
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text(content, encoding='utf-8')
        print(f'通过：{len(data["concepts"])} 概念；{sum(c["formal_teaching_available"] for c in data["concepts"])} 个试点可用快照')
    except (Invalid, OSError, ValueError, KeyError, TypeError) as exc:
        print(f'Roadmap 验证失败：{exc}', file=sys.stderr)
        return 1
    return 0

if __name__ == '__main__':
    sys.exit(main())
