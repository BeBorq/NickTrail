import json
import unittest

from nicktrail import emailid
from nicktrail.entitylinks import build, view

KNOWN = {'gmail.com', 'github.com', 'gitlab.com', 'x.com', 'codeberg.org'}


def node(i, url, platform, kind='profile', data=None, ownership='unknown', state='found'):
    return {
        'id': i,
        'url': url,
        'platform': platform,
        'kind': kind,
        'ownership': ownership,
        'state': state,
        'data': json.dumps(data or {}),
    }


def mail(i, address):
    return node(i, address, 'Deklaracja', kind='email', state='unverified')


def ev(i, s, t, relation, method='parser', context='own', current=1, decision='unknown', location=''):
    return {
        'id': i,
        'source': s,
        'target': t,
        'relation': relation,
        'method': method,
        'context': context,
        'current': current,
        'decision': decision,
        'source_url': '',
        'location': location,
        'snippet': '',
    }


def run(nodes, evidence, focus=()):
    return build({'nodes': nodes, 'evidence': evidence, 'focus': [{'node': f} for f in focus]}, KNOWN)


def members(result):
    return [set(c['members']) for c in result['clusters']]


class EmailCanonicalTest(unittest.TestCase):
    def test_gmail_forms_merge_but_other_domains_keep_dots_and_tags(self):
        key = lambda value: emailid.canonical_key(value)[0]
        self.assertEqual(key('Jan.Kowalski+gh@gmail.com'), key('jankowalski@googlemail.com'))
        self.assertNotEqual(key('jan.kowalski@firma.example'), key('jankowalski@firma.example'))
        self.assertEqual(key('user+news@firma.example'), 'user+news@firma.example')
        self.assertEqual(key('user+news@outlook.com'), 'user@outlook.com')
        self.assertTrue(emailid.canonical_key('plain@firma.example')[1]['lossless'])

    def test_invalid_addresses_are_rejected(self):
        for value in ('none', 'a@@b.example', 'a@b', 'a@ b.example', '@x.example', 'a@'):
            with self.assertRaises(ValueError):
                emailid.canonical_key(value)

    def test_gravatar_hash(self):
        digest = emailid.email_hashes('Me@Example.com')['md5']
        self.assertEqual(
            emailid.gravatar_hash_from_url('https://www.gravatar.com/avatar/' + digest + '?s=80'), digest
        )
        self.assertIsNone(emailid.gravatar_hash_from_url('https://example.com/avatar/' + digest))


class EntityLinksTest(unittest.TestCase):
    def test_different_nicks_same_mailbox_cluster_with_original_evidence(self):
        nodes = [
            node(1, 'https://github.com/octo-cat', 'GitHub', data={'alias': 'octo-cat'}),
            node(2, 'https://gitlab.com/feline99', 'GitLab', data={'alias': 'feline99'}),
            mail(3, 'Jan.Kowalski+github@gmail.com'),
            mail(4, 'jankowalski@googlemail.com'),
        ]
        result = run(
            nodes, [ev(10, 1, 3, 'public_contact_occurrence'), ev(11, 2, 4, 'public_contact_occurrence')]
        )
        self.assertEqual(members(result), [{1, 2}])
        fact = result['clusters'][0]['bridges'][0]['facts'][0]
        self.assertEqual((fact['kind'], fact['evidence']), ('shared_email', [10, 11]))
        self.assertFalse(result['clusters'][0]['identity_confirmed'])

    def test_role_mailbox_alias_and_one_way_link_are_distractors(self):
        nodes = [
            node(1, 'https://github.com/alpha-dev', 'GitHub', data={'alias': 'samealias'}),
            node(2, 'https://gitlab.com/samealias', 'GitLab', data={'alias': 'samealias'}),
            mail(3, 'support@acme.example'),
        ]
        evidence = [
            ev(10, 1, 3, 'public_contact_occurrence'),
            ev(11, 2, 3, 'public_contact_occurrence'),
            ev(12, 1, 2, 'links'),
        ]
        result = run(nodes, evidence)
        self.assertEqual(result['clusters'], [])
        self.assertEqual(result['pairs'][0]['tier'], 'weak')

    def test_stale_manual_rejected_and_third_party_evidence_ignored(self):
        nodes = [
            node(1, 'https://github.com/a1', 'GitHub'),
            node(2, 'https://gitlab.com/b2', 'GitLab'),
            mail(3, 'person@gmail.com'),
        ]
        for bad in (
            {'current': 0},
            {'method': 'manual_observation'},
            {'decision': 'rejected'},
            {'context': 'third_party'},
        ):
            evidence = [
                ev(10, 1, 3, 'public_contact_occurrence'),
                ev(11, 2, 3, 'public_contact_occurrence', **bad),
            ]
            self.assertEqual(run(nodes, evidence)['clusters'], [], bad)

    def test_rejected_unread_and_bot_accounts_never_cluster(self):
        evidence = [ev(10, 1, 3, 'public_contact_occurrence'), ev(11, 2, 3, 'public_contact_occurrence')]
        for variant in ({'ownership': 'not_mine'}, {'state': 'unverified'}, {'data': {'entity_type': 'bot'}}):
            second = node(2, 'https://gitlab.com/b2', 'GitLab', **variant)
            nodes = [node(1, 'https://github.com/a1', 'GitHub'), second, mail(3, 'person@gmail.com')]
            self.assertEqual(run(nodes, evidence)['clusters'], [], variant)

    def test_reciprocal_links_need_review_but_mutual_claims_cluster(self):
        nodes = [node(1, 'https://github.com/a1', 'GitHub'), node(2, 'https://x.com/b2', 'X')]
        links = run(nodes, [ev(10, 1, 2, 'links'), ev(11, 2, 1, 'links')])
        self.assertEqual((links['clusters'], links['pairs'][0]['tier']), ([], 'review'))
        claims = run(nodes, [ev(10, 1, 2, 'claims_ownership'), ev(11, 2, 1, 'claims_ownership')])
        self.assertEqual(members(claims), [{1, 2}])

    def test_gravatar_hash_bridges_to_published_address(self):
        digest = emailid.email_hashes('jan@example.org')['md5']
        nodes = [
            node(1, 'https://github.com/g1', 'GitHub'),
            node(
                2,
                'https://codeberg.org/g2',
                'Codeberg',
                data={'avatar_url': 'https://www.gravatar.com/avatar/' + digest},
            ),
            mail(3, 'jan@example.org'),
        ]
        result = run(nodes, [ev(10, 1, 3, 'public_contact_occurrence')])
        self.assertEqual(members(result), [{1, 2}])
        self.assertEqual(result['clusters'][0]['bridges'][0]['facts'][0]['stored_fields'], ['2.avatar_url'])

    def test_widely_shared_mailbox_does_not_create_mega_cluster(self):
        nodes, evidence = [mail(100, 'fans@gmail.com')], []
        for i in range(1, 9):
            nodes.append(node(i, f'https://github.com/user{i}', 'GitHub'))
            evidence.append(ev(200 + i, i, 100, 'public_contact_occurrence'))
        self.assertEqual(run(nodes, evidence)['clusters'], [])

    def test_contradiction_blocks_cluster(self):
        nodes = [
            node(1, 'https://github.com/p1', 'GitHub'),
            node(2, 'https://gitlab.com/p2', 'GitLab'),
            mail(3, 'pair@gmail.com'),
        ]
        evidence = [
            ev(10, 1, 3, 'public_contact_occurrence'),
            ev(11, 2, 3, 'public_contact_occurrence'),
            ev(12, 1, 2, 'identity_contradiction'),
        ]
        result = run(nodes, evidence)
        self.assertEqual(result['clusters'], [])
        self.assertEqual(result['pairs'][0]['contradiction_evidence'], [12])

    def test_late_bridge_joins_transitively(self):
        nodes = [
            node(1, 'https://github.com/a1', 'GitHub'),
            node(2, 'https://gitlab.com/b2', 'GitLab'),
            node(3, 'https://x.com/c3', 'X'),
            mail(9, 'one@gmail.com'),
        ]
        base = [ev(10, 1, 9, 'public_contact_occurrence'), ev(11, 2, 9, 'public_contact_occurrence')]
        self.assertEqual(members(run(nodes, base)), [{1, 2}])
        late = base + [ev(12, 2, 3, 'claims_ownership'), ev(13, 3, 2, 'claims_ownership')]
        self.assertEqual(members(run(nodes, late)), [{1, 2, 3}])

    def test_view_is_json_safe_and_puts_your_accounts_first(self):
        nodes = [
            node(1, 'https://github.com/a1', 'GitHub'),
            node(2, 'https://gitlab.com/b2', 'GitLab'),
            node(3, 'https://github.com/c3', 'GitHub', ownership='mine'),
            node(4, 'https://github.com/d4', 'GitHub'),
            mail(8, 'other@gmail.com'),
            mail(9, 'mine@gmail.com'),
        ]
        evidence = [
            ev(10, 1, 8, 'public_contact_occurrence'),
            ev(11, 2, 8, 'public_contact_occurrence'),
            ev(12, 3, 9, 'public_contact_occurrence'),
            ev(13, 4, 9, 'public_contact_occurrence'),
        ]
        result = view({'nodes': nodes, 'evidence': evidence, 'focus': []})
        json.dumps(result)
        first = result['clusters'][0]
        self.assertTrue(first['contains_your_account'])
        self.assertEqual(first['same_platform_accounts'], ['GitHub'])
        self.assertEqual(first['unreviewed'], [4])

    def test_repeated_weak_signals_of_one_kind_count_once(self):
        nodes = [
            node(1, 'https://linktr.ee/first', 'Linktree'),
            node(2, 'https://linktr.ee/second', 'Linktree'),
        ]
        evidence = []
        for i in range(20):
            nodes.append(node(100 + i, f'https://about.me/shared{i}', 'AboutMe', state='unverified'))
            evidence += [ev(1000 + 2 * i, 1, 100 + i, 'links'), ev(1001 + 2 * i, 2, 100 + i, 'links')]
        result = run(nodes, evidence)
        pair = next(p for p in result['pairs'] if (p['a'], p['b']) == (1, 2))
        self.assertEqual(result['clusters'], [])
        self.assertEqual((pair['tier'], pair['score']), ('weak', -0.5))
        self.assertEqual(
            {f['kind']: f['repeats'] for f in pair['facts']}, {'shared_hub': 19, 'shared_target': 19}
        )

    def test_rel_me_on_any_page_of_a_personal_site_verifies_the_profile_link(self):
        nodes = [
            node(1, 'https://fictional.example', 'Strona', kind='page'),
            node(2, 'https://fictional.example/about', 'Strona', kind='page'),
            node(3, 'https://codeberg.org/old-nick', 'Codeberg'),
        ]
        evidence = [ev(10, 2, 3, 'links', location='html.rel-me'), ev(11, 3, 1, 'links', location='website')]
        result = build({'nodes': nodes, 'evidence': evidence, 'focus': []}, KNOWN)
        self.assertEqual(members(result), [{1, 3}])
        self.assertEqual(result['clusters'][0]['site_pages'], {1: [2]})
        self.assertEqual(result['clusters'][0]['bridges'][0]['facts'][0]['kind'], 'reciprocal_verified')

    def test_group_reciprocity_adds_hub_and_account_declared_by_the_group(self):
        nodes = [
            node(1, 'https://github.com/seed', 'GitHub'),
            node(2, 'https://fictional.example', 'Strona', kind='page'),
            node(3, 'https://linktr.ee/hubname', 'Linktree'),
            node(4, 'https://dev.to/writer', 'DEV'),
            mail(9, 'person@gmail.com'),
        ]
        evidence = [
            ev(10, 1, 9, 'public_contact_occurrence'),
            ev(11, 2, 9, 'public_contact_occurrence'),
            ev(12, 2, 3, 'links', location='html.rel-me'),
            ev(13, 3, 1, 'links', location='page'),
            ev(14, 3, 4, 'links', location='page'),
            ev(15, 4, 2, 'links', location='website_url'),
        ]
        self.assertEqual(
            members(build({'nodes': nodes, 'evidence': evidence, 'focus': []}, KNOWN)), [{1, 2, 3, 4}]
        )
        # Without the group's explicit declaration of the hub, plain links do not pull it in.
        plain = [e if e['id'] != 12 else ev(12, 2, 3, 'links', location='page') for e in evidence]
        result = build({'nodes': nodes, 'evidence': plain, 'focus': []}, KNOWN)
        self.assertEqual(members(result), [{1, 2}])

    def test_friend_pages_linking_each_other_stay_review(self):
        nodes = [
            node(1, 'https://fictional.example', 'Strona', kind='page'),
            node(2, 'https://github.com/friend', 'GitHub'),
        ]
        evidence = [ev(10, 1, 2, 'links', location='page'), ev(11, 2, 1, 'links', location='bio')]
        result = build({'nodes': nodes, 'evidence': evidence, 'focus': []}, KNOWN)
        self.assertEqual((result['clusters'], result['pairs'][0]['tier']), ([], 'review'))

    def test_one_way_keybase_proof_is_review_not_cluster(self):
        nodes = [node(1, 'https://github.com/seed', 'GitHub'), node(2, 'https://keybase.io/other', 'Keybase')]
        result = build(
            {
                'nodes': nodes,
                'evidence': [ev(10, 2, 1, 'links', location='keybase.proof.github')],
                'focus': [],
            },
            KNOWN,
        )
        self.assertEqual(
            (result['clusters'], result['pairs'][0]['tier'], result['pairs'][0]['facts'][0]['kind']),
            ([], 'review', 'proof_directory'),
        )

    def test_friend_with_similar_nick_linking_site_and_seed_is_never_grouped(self):
        nodes = [
            node(1, 'https://github.com/seed', 'GitHub'),
            node(2, 'https://fictional.example', 'Strona', kind='page'),
            node(3, 'https://codeberg.org/old', 'Codeberg'),
            node(4, 'https://github.com/seed2', 'GitHub'),
            mail(9, 'person@gmail.com'),
        ]
        evidence = [
            ev(10, 1, 9, 'public_contact_occurrence'),
            ev(11, 2, 9, 'public_contact_occurrence'),
            ev(12, 1, 2, 'links', location='blog'),
            ev(13, 3, 2, 'links', location='website'),
            ev(14, 2, 3, 'links', location='html.rel-me'),
            ev(15, 2, 4, 'links', location='page'),
            ev(16, 4, 2, 'links', location='bio'),
            ev(17, 4, 1, 'links', location='bio'),
        ]
        result = build({'nodes': nodes, 'evidence': evidence, 'focus': []}, KNOWN)
        self.assertEqual(members(result), [{1, 2, 3}])
        self.assertIn(4, {x for p in result['pairs'] if p['tier'] == 'review' for x in (p['a'], p['b'])})

    def test_review_pairs_touching_your_accounts_come_first(self):
        nodes = [
            node(1, 'https://github.com/seed', 'GitHub', ownership='mine'),
            node(2, 'https://x.com/near', 'X'),
            node(3, 'https://gitlab.com/far', 'GitLab'),
            node(4, 'https://codeberg.org/far2', 'Codeberg'),
        ]
        evidence = [
            ev(10, 1, 2, 'links'),
            ev(11, 2, 1, 'links'),
            ev(12, 3, 4, 'links'),
            ev(13, 4, 3, 'links'),
            ev(14, 3, 4, 'links', location='html.rel-me'),
        ]
        pairs = view({'nodes': nodes, 'evidence': evidence, 'focus': []})['review_pairs']
        self.assertEqual([p['touches_your_accounts'] for p in pairs], [True])
        evidence[-1] = ev(14, 3, 4, 'links', location='page')
        pairs = view({'nodes': nodes, 'evidence': evidence, 'focus': []})['review_pairs']
        self.assertEqual([p['touches_your_accounts'] for p in pairs], [True, False])


if __name__ == '__main__':
    unittest.main()
