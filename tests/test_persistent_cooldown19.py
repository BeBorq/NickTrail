import tempfile, unittest, time
from pathlib import Path
from unittest.mock import patch
from nicktrail.storage import Store
from nicktrail.search import discover, results
from nicktrail.network import Client
from nicktrail.cooldowns import active


class PersistentCooldown19Tests(unittest.TestCase):
    def test_rate_limited_task_stays_pending_other_sources_continue_and_new_client_waits(self):
        class Response:
            def __init__(self, status):
                self.status = status

            def getheader(self, key, default=''):
                return '120' if key == 'Retry-After' else default

        class Connection:
            ready = False

            def __init__(self, host, *args, **kwargs):
                self.host = host

            def request(self, *args, **kwargs):
                pass

            def getresponse(self):
                return Response(429 if self.host == 'api.github.com' and not Connection.ready else 404)

            def close(self):
                pass

        folder = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(folder.cleanup)
        s = Store(Path(folder.name) / 'fixture.db')
        self.addCleanup(s.db.close)
        project = s.project('Synthetic')
        with (
            patch.dict('nicktrail.network.PROCESS_COOLDOWNS', {}, clear=True) as memory,
            patch('nicktrail.network.public_addresses', return_value=['93.184.216.34']) as dns,
            patch('nicktrail.network.PinnedTLS', Connection),
        ):
            id = discover(s, project, 'fictional', platforms=['GitHub', 'RubyGems'], client=Client(delay=0))
            item = results(s, project)[0]
            self.assertEqual(item['run']['status'], 'paused')
            states = {t['platform']: t['state'] for t in item['tasks']}
            self.assertEqual(states, {'GitHub': 'pending', 'RubyGems': 'not_found'})
            self.assertTrue(active(s))
            memory.clear()
            dns.reset_mock()
            discover(s, project, resume=id, client=Client(delay=0))
            dns.assert_not_called()
            self.assertEqual(results(s, project)[0]['run']['status'], 'paused')
            s.execute('update provider_cooldowns set until_epoch=?', (time.time() - 1,))
            memory.clear()
            Connection.ready = True
            discover(s, project, resume=id, client=Client(delay=0))
            self.assertEqual(results(s, project)[0]['run']['status'], 'completed')
            self.assertEqual(results(s, project)[0]['run']['requests'], 3)
