import json, tempfile, unittest
from pathlib import Path
from nicktrail.storage import Store
from nicktrail.engine import record
from nicktrail.adapters import extract
from nicktrail.aipacket import build


class PrivacyTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir=Path.cwd())
        self.addCleanup(self.tmp.cleanup)
        self.s = Store(str(Path(self.tmp.name) / 't.db'))
        self.addCleanup(self.s.db.close)
        self.p = self.s.project('Fictional')

    def test_public_discord_handle_is_manual_not_an_automatic_profile_link(self):
        id = self.s.add(self.p, 'https://github.com/fictional')
        items = extract(
            'Discord: fictional.user\nDiscord: https://discord.gg/community', 'https://github.com/fictional'
        )
        record(self.s, self.s.node(id), items)
        handles = [n for n in self.s.snapshot(self.p)['nodes'] if n['kind'] == 'discord']
        self.assertEqual(len(handles), 1)
        self.assertEqual(handles[0]['url'], 'discord:fictional.user')
        self.assertEqual(handles[0]['ownership'], 'unknown')
        self.assertTrue(
            all(
                e['relation'] == 'mentions'
                for e in self.s.rows('select * from evidence where target=?', (handles[0]['id'],))
            )
        )

    def test_redacted_packet_is_offline_explicit_and_contains_only_selected_edges(self):
        a = self.s.apply_profile(
            self.p,
            'https://personal.example/alice?secret=hidden',
            {'alias': 'alice', 'display': 'Alice Example', 'declared_location': 'Example City'},
        )
        b = self.s.add(self.p, 'alice@personal.example', 'email')
        record(
            self.s,
            self.s.node(a),
            [
                {
                    'email': 'alice@personal.example',
                    'relation': 'public_contact_occurrence',
                    'location': 'bio',
                    'snippet': 'Alice Example in Example City',
                }
            ],
        )
        packet = build(self.s, self.p, [a, b])
        text = json.dumps(packet)
        for secret in (
            'alice@personal.example',
            'personal.example',
            'Alice Example',
            'Example City',
            'hidden',
        ):
            self.assertNotIn(secret, text)
        self.assertEqual(len(packet['packet']['evidence']), 1)
        self.assertFalse(packet['packet']['privacy']['external_submission'])
        self.assertEqual(build(self.s, self.p, [a])['packet']['evidence'], [])

    def test_export_cannot_implicitly_include_other_project_or_invalid_options(self):
        other = self.s.project('Other')
        id = self.s.add(other, 'https://github.com/other')
        with self.assertRaises(ValueError):
            build(self.s, self.p, [id])
        with self.assertRaises(ValueError):
            build(self.s, self.p, [])
