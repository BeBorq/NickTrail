import collections
import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

import nicktrail.network as N
from nicktrail import settings
from nicktrail.cooldowns import bind, flush, forget_robots
from nicktrail.network import Client
from nicktrail.prefetch import Prefetcher
from nicktrail.storage import Store


class Fixture(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, 's.sqlite3'))

    def tearDown(self):
        self.store.db.close()
        self.dir.cleanup()
        N.SETTINGS.clear()

    def policy(self, response, **changes):
        settings.save(self.store, changes) if changes else settings.apply(self.store)
        client = Client(delay=1)
        with patch.object(client, 'get', return_value=response):
            return client.profile_policy('https://profiles.example/user'), client


class SettingsTests(Fixture):
    def test_defaults_roundtrip_and_validation(self):
        self.assertEqual(settings.load(self.store), settings.DEFAULTS)
        settings.save(self.store, {'parallel_hosts': 5, 'crawl_delay_wait': True})
        self.assertEqual(settings.load(self.store)['parallel_hosts'], 5)
        self.assertTrue(N.setting('crawl_delay_wait'))
        for bad in ({'parallel_hosts': 0}, {'parallel_hosts': 9}, {'crawl_delay_wait': 'yes'}, {'unknown': 1}):
            with self.assertRaises(ValueError):
                settings.save(self.store, bad)


class RobotsSwitchTests(Fixture):
    def test_redirected_robots_is_followed_by_default_and_can_be_refused(self):
        moved = {'state': 'found', 'text': 'User-agent: *\nAllow: /', 'url': 'https://www.profiles.example/robots.txt'}
        self.assertIsNone(self.policy(moved)[0])
        self.assertIn('przekierowana', self.policy(moved, robots_follow_redirects=False)[0])

    def test_4xx_robots_is_restricted_by_default_and_optional_unavailable(self):
        forbidden = {'state': 'blocked', 'detail': 'HTTP 403'}
        self.assertIn('HTTP 403', self.policy(forbidden)[0])
        self.assertIsNone(self.policy(forbidden, robots_4xx_allow=True)[0])
        for still_closed in ({'state': 'blocked', 'detail': 'HTTP 429'}, {'state': 'blocked', 'detail': 'HTTP 503'},
                             {'state': 'error', 'detail': 'HTTP 500'}, {'state': 'blocked', 'detail': 'Wyzwanie dostępu'}):
            self.assertIn('ROBOTS_RESTRICTED', self.policy(still_closed, robots_4xx_allow=True)[0], still_closed)

    def test_crawl_delay_is_honoured_by_slowing_down_within_limit(self):
        delayed = {'state': 'found', 'text': 'User-agent: *\nCrawl-delay: 5'}
        self.assertIn('wolniejsze', self.policy(delayed)[0])
        denied, client = self.policy(delayed, crawl_delay_wait=True)
        self.assertIsNone(denied)
        self.assertEqual(client.host_intervals['profiles.example'], 5)
        too_slow = {'state': 'found', 'text': 'User-agent: *\nCrawl-delay: 30'}
        self.assertIn('powyżej progu', self.policy(too_slow, crawl_delay_wait=True, crawl_delay_max=10)[0])
        denied, client = self.policy(too_slow, crawl_delay_wait=True, crawl_delay_max=10, crawl_delay_long='wait')
        self.assertIsNone(denied)
        self.assertEqual(client.host_intervals['profiles.example'], 30)  # full declared pause, never capped at 10
        with self.assertRaises(ValueError):
            settings.save(self.store, {'crawl_delay_long': 'shorten'})

    def test_long_pause_defers_only_that_service_and_never_shortens(self):
        settings.save(self.store, {'crawl_delay_wait': True, 'crawl_delay_long': 'wait'})
        client = Client(queries=10, seconds=20, delay=1)
        client.host_intervals['pause.example'] = 15
        client.last['pause.example'] = time.monotonic()  # a request was just sent; the next must wait the full 15 s
        with patch.object(N, 'public_addresses', lambda h, resolver=None: ['93.184.216.34']), patch.object(N, 'PinnedTLS') as tls:
            client.deadline = time.monotonic() + 5
            result = client.get('https://pause.example/u')
            tls.assert_not_called()
        self.assertEqual(result['state'], 'blocked')
        self.assertIn('kolejnej rundzie', result['detail'])
        self.assertGreater(client.cooldowns['pause.example'] - time.monotonic(), 14)
        longer_than_round = Client(queries=10, seconds=20, delay=1)
        longer_than_round.host_intervals['round.example'] = 60
        longer_than_round.last['round.example'] = time.monotonic()
        with patch.object(N, 'public_addresses', lambda h, resolver=None: ['93.184.216.34']), patch.object(N, 'PinnedTLS') as tls:
            self.assertIn('dłuższy niż cała runda', longer_than_round.get('https://round.example/u')['detail'])
            tls.assert_not_called()

    def test_disallow_is_never_overridden(self):
        disallow = {'state': 'found', 'text': 'User-agent: *\nDisallow: /'}
        everything = dict(robots_follow_redirects=True, robots_4xx_allow=True, crawl_delay_wait=True)
        self.assertIn('zabroniony', self.policy(disallow, **everything)[0])


class RobotsMemoryTests(Fixture):
    def test_definitive_refusal_is_remembered_across_clients_but_transient_is_not(self):
        first = Client(delay=1)
        bind(first, self.store)
        with patch.object(first, 'get', return_value={'state': 'found', 'text': 'User-agent: *\nDisallow: /'}):
            self.assertIn('zabroniony', first.profile_policy('https://closed.example/u'))
        with patch.object(first, 'get', return_value={'state': 'blocked', 'detail': 'Limit domeny'}):
            first.profile_policy('https://busy.example/u')
        second = Client(delay=1)
        bind(second, self.store)
        with patch.object(second, 'get', side_effect=AssertionError('robots.txt must not be fetched again')):
            self.assertIn('zapamiętana', second.profile_policy('https://closed.example/u'))
        with patch.object(second, 'get', return_value={'state': 'not_found'}) as fetch:
            self.assertIsNone(second.profile_policy('https://busy.example/u'))
            fetch.assert_called_once()
        self.assertEqual(forget_robots(self.store), 1)

    def test_memory_switch_off_fetches_again(self):
        settings.save(self.store, {'robots_memory': False})
        client = Client(delay=1)
        bind(client, self.store)
        with patch.object(client, 'get', return_value={'state': 'found', 'text': 'User-agent: *\nDisallow: /'}) as fetch:
            client.profile_policy('https://closed.example/u')
            client.profile_policy('https://closed.example/u')
            self.assertEqual(fetch.call_count, 2)

    def test_writes_from_reader_threads_are_queued_until_flush(self):
        client = Client(delay=1)
        bind(client, self.store)
        thread = threading.Thread(target=client.defer_host, args=('slow.example', 120))
        thread.start(); thread.join()
        self.assertEqual(self.store.rows('SELECT count(*) n FROM provider_cooldowns')[0]['n'], 0)
        self.assertEqual(len(client.persist_queue), 1)
        flush(client, self.store)
        self.assertEqual(self.store.rows('SELECT host FROM provider_cooldowns')[0]['host'], 'slow.example')


class ParallelPacingTests(unittest.TestCase):
    def test_parallel_reads_keep_one_request_and_full_pause_per_host(self):
        log, active, overlap, lock = [], collections.Counter(), [0], threading.Lock()

        class Response:
            status = 404
            def getheader(self, name, default=''):
                return 'text/plain' if name == 'Content-Type' else default
            def read1(self, n):
                return b''

        class Connection:
            def __init__(self, host, ip, timeout):
                self.host = host
            def request(self, *args, **kwargs):
                with lock:
                    active[self.host] += 1
                    overlap[0] += active[self.host] > 1
                    log.append((self.host, time.monotonic()))
                time.sleep(0.05)
            def getresponse(self):
                with lock:
                    active[self.host] -= 1
                return Response()
            def close(self):
                pass

        client = Client(queries=50, seconds=60, delay=0.3)
        tasks = [{'platform': 'Free', 'term': f'{host}:{n}', 'mode': 'probe'} for host in ('a', 'b', 'c', 'd') for n in range(3)]
        prefetcher = Prefetcher(client, 4, lambda t: client.get(f"https://{t['term'].split(':')[0]}.example/u{t['term'][-1]}"))
        started = time.monotonic()
        with patch.object(N, 'PinnedTLS', Connection), patch.object(N, 'public_addresses', lambda h, resolver=None: ['93.184.216.34']):
            results = []
            for i, task in enumerate(tasks):
                prefetcher.schedule(tasks[i:i + 8])
                results.append(prefetcher.take((task['platform'], task['term'], task['mode'])))
            prefetcher.close()
        elapsed = time.monotonic() - started
        self.assertTrue(all(r and r[0] == 'ok' and r[2] == 1 for r in results))
        self.assertEqual(overlap[0], 0)
        by_host = collections.defaultdict(list)
        for host, at in log:
            by_host[host].append(at)
        self.assertGreaterEqual(min(b - a for times in by_host.values() for a, b in zip(times, times[1:])), 0.29)
        self.assertLess(elapsed, 12 * 0.35)  # sequential would need ~12 x (pause+latency)
        self.assertEqual(client.count, 12)


if __name__ == '__main__':
    unittest.main()
