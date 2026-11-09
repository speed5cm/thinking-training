import importlib.util
import json
import shutil
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('roadmap_generator', ROOT / 'scripts/generate_roadmap.py')
roadmap = importlib.util.module_from_spec(spec)
spec.loader.exec_module(roadmap)

class RoadmapTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        for path in ('wiki', 'references', 'question-bank', 'pilot-c01-c02/scripts', 'pilot-c01-c02/wiki', 'pilot-c01-c02/cards', 'pilot-c01-c02/reviews'):
            shutil.copytree(ROOT / path, self.root / path)

    def test_complete_graph_and_publication(self):
        data = roadmap.build(self.root)
        items = {c['id']: c for c in data['concepts']}
        self.assertEqual(set(items), {f'C{i:02}' for i in range(1, 15)})
        # The roadmap is informational; formal teaching remains closed for every concept.
        self.assertEqual({c['id'] for c in items.values() if c['formal_teaching_available']}, set())
        self.assertEqual(set(data['ability_domains']), {a for c in items.values() for a in c['abilities']})
        self.assertEqual(items['C02']['hard_prerequisites'], ['C01'])
        self.assertEqual(items['C11']['interleavable'], ['C02', 'C09'])
        self.assertEqual(items['C14']['interleavable'], ['C01', 'C09'])

    def test_missing_page_and_invalid_source_fail(self):
        page = self.root / 'wiki/concepts/pattern-rule.md'
        original = page.read_text()
        page.unlink()
        with self.assertRaises(roadmap.Invalid): roadmap.build(self.root)
        page.write_text(original.replace('R01, R02', 'R99, R02'))
        with self.assertRaises(roadmap.Invalid): roadmap.build(self.root)

    def test_cycle_and_dangling_relationship_fail(self):
        page = self.root / 'wiki/concepts/observation-vs-inference.md'
        original = page.read_text()
        page.write_text(original.replace('**先修**：无', '**先修**：[[concepts/attribute-comparison]]').replace('"hard_prerequisites": []', '"hard_prerequisites": ["C02"]'))
        index = self.root / 'wiki/index.md'
        index.write_text(index.read_text().replace('观察事实与推测 | W01 | 无 |', '观察事实与推测 | W01 | C02 |'))
        with self.assertRaisesRegex(roadmap.Invalid, '循环依赖'): roadmap.build(self.root)
        page.write_text(original.replace('"hard_prerequisites": []', '"hard_prerequisites": ["C99"]'))
        with self.assertRaises(roadmap.Invalid): roadmap.build(self.root)

    def test_changed_card_or_missing_review_blocks(self):
        path = self.root / 'pilot-c01-c02/cards/ST-C01-01.json'
        path.write_text(path.read_text() + ' ')
        (self.root / 'pilot-c01-c02/reviews/ST-C02-01@1.1.0.json').unlink()
        data = roadmap.build(self.root)
        self.assertTrue(all(not c['formal_teaching_available'] for c in data['concepts']))
        self.assertTrue(all(not c['published_cards'] for c in data['concepts']))

    def test_html_is_escaped_and_standalone(self):
        data = roadmap.build(self.root)
        data['concepts'][0]['teaching_goal'] = '<script>alert(1)</script>'
        rendered = roadmap.render(data)
        self.assertNotIn('<script>', rendered)
        self.assertIn('&lt;script&gt;', rendered)
        self.assertEqual(rendered.count('<article>'), 14)

if __name__ == '__main__': unittest.main()
