import json, unittest
from unittest.mock import patch
from nicktrail.engines import lookup_platform


class EngineTests(unittest.TestCase):
    def lookup(self, engine, body):
        class Client:
            def get(self, url):
                return {'state': 'found', 'text': json.dumps(body)}

        with (
            patch('nicktrail.engineconfig.instances', return_value={}),
            patch(
                'nicktrail.engines.instances',
                return_value={'Fixture': {'host': 'profiles.example', 'engine': engine}},
            ),
        ):
            return lookup_platform('Fixture', 'fictional', Client())

    def test_gitea_exact_public_profile_and_outgoing_link(self):
        r = self.lookup(
            'gitea', {'id': 9, 'login': 'fictional', 'description': 'https://github.com/another-fictional'}
        )
        self.assertEqual(r['state'], 'found')
        self.assertEqual(r['matches'][0]['data']['stable_id'], '9')
        self.assertTrue(r['matches'][0]['evidence'])

    def test_wrong_alias_is_not_found(self):
        self.assertEqual(self.lookup('gitea', {'id': 9, 'login': 'someone-else'})['state'], 'partial')

    def test_malformed_lemmy_nested_body_is_partial(self):
        for view in ('unexpected', [], None, {'person': 'unexpected'}):
            self.assertEqual(self.lookup('lemmy', {'person_view': view})['state'], 'partial')

    def test_remote_lemmy_actor_is_not_local_account(self):
        self.assertEqual(
            self.lookup(
                'lemmy',
                {
                    'person_view': {
                        'person': {
                            'id': 9,
                            'name': 'fictional',
                            'local': False,
                            'actor_id': 'https://remote.example/u/fictional',
                        }
                    }
                },
            )['state'],
            'partial',
        )

    def test_wordpress_author_requires_same_host(self):
        self.assertEqual(
            self.lookup(
                'wordpress',
                [{'id': 9, 'slug': 'fictional', 'link': 'https://other.example/author/fictional'}],
            )['state'],
            'partial',
        )

    def test_gitlab_requires_exact_filtered_username(self):
        self.assertEqual(
            self.lookup('gitlab', [{'id': 9, 'username': 'fictional-extra'}])['state'], 'not_found'
        )
