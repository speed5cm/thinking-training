"""Synthetic fixtures only; never creates a human authorization."""
import hashlib
import json

FILES = ('wiki/index.md', 'wiki/concepts/observation-vs-inference.md',
         'curriculum/12-week-plan.md', 'references/sources.md', 'references/pedagogy.md',
         'question-bank/original-examples.md', 'pilot-c01-c02/wiki/index.md',
         'pilot-c01-c02/wiki/overview.md', 'pilot-c01-c02/wiki/concepts/C01.md',
         'pilot-c01-c02/wiki/sources/project-research.md')

def write_authorization(root, version='synthetic-1'):
    record = {'schema_version': 1, 'concept': 'C01', 'version': version,
              'review': {'kind': 'synthetic_simulation', 'actor': 'synthetic reviewer', 'basis': 'test fixture only'},
              'status': 'active',
              'teaching_goal': '面对两个新场景能各说出3条事实+1条推测，并提出一条核实方法。',
              'scope': '可直接核查的描述和对原因、经历、意图的猜测不同。',
              'sources': ['R04', 'R06'],
              'content_sha256': {p: hashlib.sha256((root / p).read_bytes()).hexdigest() for p in FILES}}
    path = root / 'pilot-c01-c02/concept-authorizations/C01.json'
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
    return path
