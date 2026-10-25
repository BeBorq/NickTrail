import json, unittest
from nicktrail.providers import lookup
from nicktrail.identity import identify


class Client:
    def __init__(self, body):
        self.body = body
        self.calls = []

    def get(self, url):
        self.calls.append(url)
        return {'state': 'found', 'text': json.dumps(self.body), 'url': url}


def user():
    return {
        'id': 'a' * 32,
        'basics': {'username': 'differentname', 'status': 0},
        'profile': {'bio': 'My site https://personal.example'},
        'proofs_summary': {
            'all': [
                {
                    'proof_type': 'github',
                    'nametag': 'oldalias',
                    'state': 1,
                    'service_url': 'https://github.com/oldalias',
                },
                {
                    'proof_type': 'twitter',
                    'nametag': 'stale',
                    'state': 2,
                    'service_url': 'https://x.com/stale',
                },
            ]
        },
    }


class IdentityAPITests(unittest.TestCase):
    def test_reverse_keybase_discovers_different_username_and_only_current_proofs(self):
        c = Client({'status': {'code': 0}, 'them': [user()]})
        r = lookup('Keybase', 'github:oldalias', c)
        self.assertEqual(r['state'], 'found')
        self.assertEqual(r['matches'][0]['data']['alias'], 'differentname')
        self.assertEqual(len(r['matches'][0]['evidence']), 2)
        self.assertIn('github=oldalias', c.calls[0])
        self.assertNotIn('public_keys', c.calls[0])

    def test_reverse_wrong_proof_and_exact_wrong_user_are_not_hits(self):
        body = {'status': {'code': 0}, 'them': [user()]}
        self.assertEqual(lookup('Keybase', 'github:someone', Client(body))['state'], 'not_found')
        self.assertEqual(lookup('Keybase', 'oldalias', Client(body))['state'], 'not_found')

    def test_public_hn_null_case_sensitivity_and_about(self):
        self.assertEqual(lookup('HackerNews', 'Fixture', Client(None))['state'], 'not_found')
        self.assertEqual(lookup('HackerNews', 'Fixture', Client({'id': 'fixture'}))['state'], 'partial')
        r = lookup(
            'HackerNews',
            'Fixture',
            Client({'id': 'Fixture', 'about': '<a href="https://site.example">My website</a>'}),
        )
        self.assertEqual(r['state'], 'found')
        self.assertEqual(len(r['matches'][0]['evidence']), 1)
        n = identify(r['matches'][0]['url'])
        self.assertEqual(n['kind'], 'profile')
        self.assertIn('id=Fixture', n['url'])

    def test_invalid_reverse_inputs_are_not_sent(self):
        c = Client({})
        r = lookup('Keybase', 'email:private@example.org', c)
        self.assertEqual(r['state'], 'unsupported')
        self.assertEqual(c.calls, [])

    def test_lookup_metadata_is_whitelisted_and_no_secret_response_fields_stored(self):
        u = user()
        u['pictures'] = []
        u['public_keys'] = {'bundle': 'not needed'}
        u['basics']['salt'] = 'not needed'
        r = lookup(
            'Keybase',
            'differentname',
            Client({'status': {'code': 0}, 'csrf_token': 'not needed', 'them': [u]}),
        )
        self.assertNotIn('not needed', json.dumps(r))
