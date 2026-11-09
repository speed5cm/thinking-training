"""Publication maintenance uses isolated synthetic approval records."""
import importlib.util
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'pilot-c01-c02/scripts'))
spec = importlib.util.spec_from_file_location('publication_test', ROOT / 'pilot-c01-c02/scripts/publication.py')
publication = importlib.util.module_from_spec(spec)
spec.loader.exec_module(publication)

class PublicationTest(unittest.TestCase):
    def test_publish_revoke_and_failed_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for name in ('cards', 'reviews', 'wiki'):
                shutil.copytree(ROOT / 'pilot-c01-c02' / name, root / name)
            review_path = root / 'reviews/ST-C02-01@1.1.0.json'
            review = json.loads(review_path.read_text())
            review['transitions'] = review['transitions'][:2]
            for transition in review['transitions']: transition['actor'] = 'SYNTHETIC_TEST_ONLY'
            review_path.write_text(json.dumps(review, ensure_ascii=False))
            with mock.patch.object(publication.coach, 'ROOT', root):
                tampered = dict(review, content_sha256='0' * 64)
                review_path.write_text(json.dumps(tampered, ensure_ascii=False))
                with self.assertRaises(publication.coach.Stop): publication.maintain('publish', 'ST-C02-01', 'SYNTHETIC', 'test')
                review_path.write_text(json.dumps(review, ensure_ascii=False))
                old = review_path.read_bytes()
                with mock.patch.object(publication.os, 'replace', side_effect=OSError('synthetic failure')):
                    with self.assertRaises(OSError): publication.maintain('publish', 'ST-C02-01', 'SYNTHETIC', 'test')
                self.assertEqual(old, review_path.read_bytes())
                self.assertEqual(publication.maintain('publish', 'ST-C02-01', 'SYNTHETIC', 'test')['status'], 'published')
                publication.coach.load_card('ST-C02-01')
                self.assertEqual(publication.maintain('revoke', 'ST-C02-01', 'SYNTHETIC', 'test')['status'], 'revoked')
                with self.assertRaises(publication.coach.Stop): publication.coach.load_card('ST-C02-01')
                with self.assertRaises(publication.coach.Stop): publication.maintain('publish', 'ST-C02-01', 'SYNTHETIC', 'test')
                self.assertEqual([x['state'] for x in json.loads(review_path.read_text())['transitions']], ['verified','approved','published','revoked'])

if __name__ == '__main__': unittest.main()
