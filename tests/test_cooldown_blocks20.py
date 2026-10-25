import os
import tempfile
import time
import unittest

from nicktrail.cooldowns import bind, waiting
from nicktrail.storage import Store


class FakeClient:
    """Minimal client exposing the cooldown hooks bind() wraps."""

    def __init__(self):
        self.cooldowns = {}

    def defer_host(self, host, seconds):
        self.cooldowns[host] = seconds


class BlockCountTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory()
        self.store = Store(os.path.join(self.dir.name, 'b.sqlite3'))

    def tearDown(self):
        self.store.db.close()
        self.dir.cleanup()

    def test_each_defer_increments_the_host_block_count(self):
        client = FakeClient()
        self.assertTrue(bind(client, self.store))
        client.defer_host('users.roblox.com', 60)
        client.defer_host('users.roblox.com', 90)  # a second block extends and counts again
        client.defer_host('api.github.com', 30)
        w = waiting(self.store)
        by_host = {h['host']: h for h in w['hosts']}
        self.assertEqual(by_host['users.roblox.com']['blocks'], 2)
        self.assertEqual(by_host['api.github.com']['blocks'], 1)
        self.assertEqual(w['total_blocks'], 3)
        self.assertGreater(by_host['users.roblox.com']['until_epoch'], time.time())

    def test_expired_pause_leaves_the_block_tally_but_drops_from_active(self):
        client = FakeClient()
        bind(client, self.store)
        client.defer_host('slow.example', 0)  # already elapsed
        w = waiting(self.store)
        self.assertEqual(w['hosts'], [])  # nothing to wait for
        self.assertEqual(w['total_blocks'], 1)  # but the block still counted


if __name__ == '__main__':
    unittest.main()
