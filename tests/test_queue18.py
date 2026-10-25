import unittest, tempfile, json, time
from pathlib import Path
from unittest.mock import patch
from nicktrail.search import discover
from nicktrail.storage import Store


class Queue18Tests(unittest.TestCase):
    def test_large_definition_batch_persists_all_aliases_and_resume(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as folder:
            s = Store(Path(folder) / 'q.db')
            p = s.project('Synthetic')

            class NoHTTP:
                count = 0

                def get(self, url):
                    raise AssertionError('No HTTP during stopped scheduling')

            rows = [{'id': 'Fixture.' + str(i)} for i in range(1000)]
            with patch('nicktrail.extended.services', return_value=rows):
                id = discover(
                    s,
                    p,
                    'first',
                    aliases=['second', 'third'],
                    platforms=['Extended'],
                    client=NoHTTP(),
                    stopped=lambda: True,
                )
                tasks = s.rows('select * from search_tasks where search=?', (id,))
                self.assertEqual(len(tasks), 3000)
                discover(s, p, resume=id, client=NoHTTP(), stopped=lambda: True)
                self.assertEqual(len(s.rows('select * from search_tasks where search=?', (id,))), 3000)
                self.assertEqual(
                    [r['term'] for r in tasks[:3]], ['Fixture.0:first', 'Fixture.0:second', 'Fixture.0:third']
                )
            s.db.close()
