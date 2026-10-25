import json
import unittest
from nicktrail.ranking import evaluate


def node(id, url, platform, alias=None, kind='profile', ownership='unknown', state='found'):
    return {
        'id': id,
        'state': state,
        'kind': kind,
        'ownership': ownership,
        'platform': platform,
        'data': json.dumps({'alias': alias} if alias else {}),
        'url': url,
    }


def edge(id, source, target, location, relation='links', current=1, decision='unknown'):
    return {
        'id': id,
        'source': source,
        'target': target,
        'relation': relation,
        'location': location,
        'current': current,
        'decision': decision,
        'method': 'parser',
        'context': 'own',
        'source_url': '',
        'snippet': '',
    }


def fixture():
    nodes = [
        node(1, 'https://github.com/seed', 'GitHub', 'seed'),
        node(2, 'https://fictional.example', 'Strona', kind='page'),
        node(3, 'https://codeberg.org/old', 'Codeberg', 'old'),
        node(4, 'https://github.com/seed2', 'GitHub', 'seed2'),
        node(5, 'https://gitlab.com/seed', 'GitLab', 'seed'),
        node(6, 'https://keybase.io/other', 'Keybase', 'other'),
    ]
    evidence = [
        edge(10, 1, 2, 'blog'),
        edge(11, 2, 3, 'html.rel-me'),
        edge(12, 3, 2, 'website'),
        edge(13, 2, 4, 'page'),
        edge(14, 4, 2, 'bio'),
        edge(15, 6, 1, 'keybase.proof.github'),
    ]
    return {'nodes': nodes, 'evidence': evidence, 'focus': [{'node': 1}], 'scans': []}


class GroupRankingTests(unittest.TestCase):
    def test_rel_me_group_member_outranks_friend_and_proof_outranks_same_nick(self):
        order = evaluate(fixture())['order']
        self.assertLess(order.index(3), order.index(4))  # verified old account above friend with shorter path
        self.assertLess(order.index(6), order.index(5))  # proof directory entry above bare same-nick account
        r = evaluate(fixture())['nodes']
        self.assertIn('identity_group', r['3']['weights'])
        self.assertIn('identity_review', r['6']['weights'])
        self.assertNotIn('identity_group', r['5']['weights'])

    def test_stale_or_rejected_declarations_do_not_create_group_priority(self):
        for change in ({'current': 0}, {'decision': 'rejected'}):
            s = fixture()
            s['evidence'][1].update(change)
            self.assertNotIn('identity_group', evaluate(s)['nodes']['3']['weights'], change)

    def test_rejected_account_is_never_promoted(self):
        s = fixture()
        s['nodes'][2]['ownership'] = 'not_mine'
        self.assertNotIn('identity_group', evaluate(s)['nodes']['3']['weights'])


if __name__ == '__main__':
    unittest.main()
