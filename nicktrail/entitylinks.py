"""Advisory identity clusters over the public evidence graph.

`graphsignals.analyze` reports per-node paths relative to anchors.  This module
adds a complementary, explainable *cluster* view:

* e-mail nodes are compared by provider-aware canonical key (`emailid`), so
  ``Jan.Kowalski+gh@gmail.com`` and ``jankowalski@googlemail.com`` bridge;
* a raw public address can bridge to a profile whose stored Gravatar/Libravatar
  URL contains the hash of that same address (a hash of an e-mail, never image
  similarity);
* independent public evidence is accumulated in log-odds, de-duplicated by
  source group, and pairs above a threshold are joined with union-find.

Nothing here changes ownership, merges database rows or confirms identity.
Every bridge keeps the IDs of the original evidence rows.  Rejected, stale,
manual, third-party, organization/bot and role-mailbox evidence is excluded.
The weights are hand-set review priorities, not a trained or calibrated model.
"""
import json
import math
from collections import defaultdict
from urllib.parse import urlsplit

from .accountentities import non_person
from .emailid import canonical_key, email_hashes, gravatar_hash_from_url
from .identity import team_email
from .independence import group as source_group

# Log-odds review weights.  PRIOR is the starting point for two arbitrary accounts.
PRIOR = -4.0
W_EMAIL = 5.5           # same personal mailbox published by both accounts
W_EMAIL_HASH = 5.5      # raw address on one account, its hash in the other's avatar URL
W_RECIPROCAL_OWN = 6.0  # mutual links where at least one side is an explicit declaration
W_PROOF = 5.0           # one-way Keybase proof directory entry (signature not verified by NickTrail)
W_RECIPROCAL = 4.5      # both accounts link each other
W_SITE = 3.0            # both declare the same personal website as their own (website field / rel=me)
W_SITE_MENTION = 1.0    # both link the same personal website, at least one only mentions it
W_OWNERSHIP = 2.5       # one account explicitly claims the other
W_HUB = 2.0             # both link the same identity hub page
W_TARGET_PROFILE = 1.5  # both link the same third profile
W_ALIAS = 1.0           # identical alias on different platforms (never enough alone)
W_LINK = 0.8            # one-way link
W_CONTRADICTION = -7.0  # current typed contradiction between the two accounts

POPULAR_CAP = 6         # an identifier shared by more accounts is not personal; it is skipped
STRONG = 1.5            # pairs at or above this join a suggested cluster
SUGGEST = 0.0           # pairs at or above this are listed for review

PUBLIC_METHODS = {'parser', 'rendered_public_page'}
LINK_RELATIONS = {'links', 'claims_ownership', 'public_contact_occurrence'}
IDENTITY_HUBS = {'linktr.ee', 'carrd.co', 'about.me', 'beacons.ai', 'bento.me', 'bio.site',
                 'taplink.cc', 'gravatar.com', 'keybase.io', 'lnk.bio', 'many.link', 'shor.by'}


def _data(node):
    raw = node.get('data', '{}')
    try:
        value = json.loads(raw) if isinstance(raw, str) else raw
    except (ValueError, TypeError):
        return {}
    return value if isinstance(value, dict) else {}


def _host(url):
    return (urlsplit(url).hostname or '').removeprefix('www.').lower()


def _personal_site(node, known_domains):
    if node.get('platform') != 'Strona' or urlsplit(node['url']).query:
        return None
    host = _host(node['url'])
    return host if host and host not in known_domains else None


def _hub(url):
    host = _host(url)
    return host if any(host == h or host.endswith('.' + h) for h in IDENTITY_HUBS) else None


class _UnionFind:
    def __init__(self):
        self.parent = {}

    def find(self, x):
        self.parent.setdefault(x, x)
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[max(ra, rb)] = min(ra, rb)


def _eligible(node):
    return (node.get('kind') in ('profile', 'page') and node.get('state') == 'found'
            and node.get('ownership') != 'not_mine' and not non_person(node))


def _usable(edge):
    return (edge.get('current', 1) and edge.get('decision') != 'rejected'
            and edge.get('context', 'own') == 'own'
            and edge.get('method', 'parser') in PUBLIC_METHODS)


# Evidence locations where a page or account explicitly declares another
# address as the same person (IndieWeb rel=me, schema.org sameAs, a profile's
# own website/links field, a Keybase proof directory entry).
CLAIM_LOCATIONS = {'html.rel-me', 'jsonld.sameAs', 'blog', 'website', 'website_url', 'links', 'bluesky.domain_handle', 'github.social_accounts'}


def _claim(edge):
    location = edge.get('location') or ''
    return edge['relation'] == 'claims_ownership' or location in CLAIM_LOCATIONS or location.startswith('keybase.proof.')


def _site_representatives(nodes, eligible, known_domains):
    """Pages of one personal website act as one entity (root page preferred)."""
    by_host = defaultdict(list)
    for i in eligible:
        host = _personal_site(nodes[i], known_domains)
        if host:
            by_host[host].append(i)
    rep = {}
    for host, ids in by_host.items():
        root = sorted(ids, key=lambda i: (urlsplit(nodes[i]['url']).path.strip('/') != '', i))[0]
        for i in ids:
            rep[i] = root
    return rep


def _score(facts, contradictions):
    pairs = []
    for pair, items in facts.items():
        a, b = sorted(pair)
        best = {}
        for f in items:
            if f['group'] not in best or f['weight'] > best[f['group']]['weight']:
                best[f['group']] = f
        # Repeated observations of one kind (e.g. two pages copying the same 20
        # links) are one consideration, not twenty: each kind counts once.
        by_kind = {}
        for f in sorted(best.values(), key=lambda f: (-f['weight'], f['group'])):
            if f['kind'] in by_kind:
                by_kind[f['kind']]['repeats'] += 1
            else:
                by_kind[f['kind']] = f | {'repeats': 0}
        kept = sorted(by_kind.values(), key=lambda f: (-f['weight'], f['kind']))
        score = PRIOR + sum(f['weight'] for f in kept)
        blocked = sorted(contradictions.get(pair, ()))
        if blocked:
            score += W_CONTRADICTION
        tier = 'cluster' if score >= STRONG else 'review' if score >= SUGGEST else 'weak'
        pairs.append({'a': a, 'b': b, 'score': round(score, 3), 'probability': round(1 / (1 + math.exp(-score)), 4),
                      'tier': tier, 'contradiction_evidence': blocked, 'independent_signals': len(kept),
                      'facts': [{k: f[k] for k in ('kind', 'why', 'weight', 'evidence', 'stored_fields', 'repeats')} for f in kept],
                      'identity_confirmed': False})
    pairs.sort(key=lambda p: (-p['score'], p['a'], p['b']))
    return pairs


def _union(pairs, contradictions=None):
    """Join strong pairs, strongest first, never merging two groups in conflict.

    A contradiction between any member of one group and any member of the other
    blocks the merge, so A-B and B-C cannot pull C next to A when A and C were
    declared different people.  A blocked pair stays visible as a review pair
    with the reason, instead of silently joining or silently disappearing.
    """
    union = _UnionFind()
    members = {}
    conflicts = contradictions or {}
    for p in sorted(pairs, key=lambda p: (-p['score'], p['a'], p['b'])):
        if p['tier'] != 'cluster':
            continue
        ra, rb = union.find(p['a']), union.find(p['b'])
        if ra == rb:
            continue
        left, right = members.get(ra, {ra}), members.get(rb, {rb})
        clash = sorted((x, y) for x in left for y in right if frozenset((x, y)) in conflicts)
        if clash:
            x, y = clash[0]
            p['tier'] = 'review'
            p['blocked_by_group_conflict'] = [x, y]
            p['facts'] = p['facts'] + [{'kind': 'group_conflict', 'weight': 0, 'repeats': 0, 'stored_fields': [],
                                        'evidence': sorted(conflicts[frozenset((x, y))]),
                                        'why': f'Nie połączono: konto #{x} i konto #{y} oznaczono jako różne osoby, a połączenie objęłoby oba'}]
            continue
        union.union(p['a'], p['b'])
        root = union.find(p['a'])
        members[root] = left | right
    return union


def build(snapshot, known_domains=()):
    """Pure function of a snapshot: bridge facts, scored pairs and clusters."""
    known_domains = {d.lower() for d in known_domains}
    nodes = {n['id']: n for n in snapshot['nodes']}
    eligible = {i for i, n in nodes.items() if _eligible(n)}
    rep = _site_representatives(nodes, eligible, known_domains)

    def R(i):
        return rep.get(i, i)

    emails = defaultdict(lambda: defaultdict(set))   # canonical -> node -> evidence ids
    email_meta = {}
    email_forms = defaultdict(set)                    # canonical -> exact published forms
    directed = {}                                     # (a, b) -> {'claim','proof','ids'}
    sites = defaultdict(lambda: defaultdict(set))     # host -> node -> evidence ids
    site_claims = defaultdict(set)                    # host -> nodes declaring it as their site
    hubs = defaultdict(lambda: defaultdict(set))
    targets = defaultdict(lambda: defaultdict(set))   # third profile -> node -> evidence ids
    contradictions = defaultdict(set)                 # pair -> evidence ids

    for e in snapshot['evidence']:
        if e['source'] not in nodes or e['target'] not in nodes:
            continue
        a, b = R(e['source']), R(e['target'])
        if a == b:
            continue
        if e.get('relation') == 'identity_contradiction':
            if a in eligible and b in eligible and e.get('current', 1) and e.get('decision') != 'rejected':
                contradictions[frozenset((a, b))].update({e['id']} if e.get('id') is not None else ())
            continue
        if e['source'] not in eligible or not _usable(e) or e.get('relation') not in LINK_RELATIONS:
            continue
        target = nodes[e['target']]
        if e['relation'] == 'public_contact_occurrence':
            if target.get('kind') != 'email' or team_email(target['url']):
                continue
            try:
                canonical, meta = canonical_key(target['url'])
            except ValueError:
                continue
            emails[canonical][a].update({e['id']} if e.get('id') is not None else ())
            email_meta[canonical] = meta
            email_forms[canonical].add(meta['exact'].lower())
            continue
        if target.get('kind') not in ('profile', 'page') or target.get('ownership') == 'not_mine' or non_person(target):
            continue
        edge = directed.setdefault((a, b), {'claim': False, 'proof': False, 'ids': set()})
        edge['claim'] = edge['claim'] or _claim(e)
        edge['proof'] = edge['proof'] or (e.get('location') or '').startswith('keybase.proof.')
        if e.get('id') is not None:
            edge['ids'].add(e['id'])
        host = _personal_site(target, known_domains)
        if host:
            sites[host][a].update({e['id']} if e.get('id') is not None else ())
            if _claim(e):
                site_claims[host].add(a)
        hub = _hub(target['url'])
        if hub:
            hubs[target['url']][a].update({e['id']} if e.get('id') is not None else ())
        if target.get('kind') == 'profile':
            targets[b][a].update({e['id']} if e.get('id') is not None else ())

    facts = defaultdict(list)
    skipped = []

    def fact(a, b, weight, group, kind, why, evidence=(), stored_fields=()):
        if a != b:
            facts[frozenset((a, b))].append({'kind': kind, 'why': why, 'weight': weight, 'group': group,
                                             'evidence': sorted(evidence), 'stored_fields': list(stored_fields)})

    def pairwise(owners, weight, group, kind, why, exclude=None):
        owners = {k: v for k, v in owners.items() if k != exclude}
        if len(owners) > POPULAR_CAP:
            skipped.append({'kind': kind, 'group': group, 'accounts': len(owners)})
            return
        members = sorted(owners)
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                fact(a, b, weight, group, kind, why, owners[a] | owners[b])

    for canonical, owners in emails.items():
        meta = email_meta[canonical]
        why = 'Ten sam publiczny adres e-mail na obu kontach'
        if meta['transforms']:
            why += ' (po normalizacji: ' + '; '.join(meta['transforms']) + ')'
        pairwise(owners, W_EMAIL, 'email:' + canonical, 'shared_email', why)

    avatar_hashes = defaultdict(set)
    for i in eligible:
        if R(i) != i:
            continue
        value = _data(nodes[i]).get('avatar_url')
        found = gravatar_hash_from_url(value) if isinstance(value, str) else None
        if found:
            avatar_hashes[found].add(i)
    for canonical, owners in emails.items():
        if len(owners) > POPULAR_CAP:
            continue
        for exact_form in email_forms[canonical] | {canonical}:
            hashes = email_hashes(exact_form)
            for digest in {hashes['md5'], hashes['sha256']}:
                for b in avatar_hashes.get(digest, ()):
                    for a, ids in owners.items():
                        fact(a, b, W_EMAIL_HASH, 'email:' + canonical, 'shared_email_hash',
                             'Adres awatara Gravatar/Libravatar zawiera hash adresu e-mail podanego na drugim koncie',
                             ids, [f'{b}.avatar_url'])

    def mutual(a, b, there, back, group, kind, why_verified, why_plain):
        verified = there['claim'] or back['claim']
        fact(a, b, W_RECIPROCAL_OWN if verified else W_RECIPROCAL, group,
             kind + ('_verified' if verified else ''), why_verified if verified else why_plain,
             there['ids'] | back['ids'])

    for (a, b), edge in directed.items():
        back = directed.get((b, a))
        if back:
            if a < b:
                mutual(a, b, edge, back, 'mutual:' + str(a) + ':' + str(b), 'reciprocal',
                       'Wzajemne odnośniki, z których co najmniej jeden jest jawną deklaracją (rel=me, sameAs, pole strony WWW lub dowód Keybase)',
                       'Oba konta linkują siebie nawzajem zwykłymi odnośnikami')
        elif edge['proof']:
            fact(a, b, W_PROOF, source_group(nodes[a]), 'proof_directory',
                 'Wpis katalogu dowodów Keybase wskazuje to konto; NickTrail nie weryfikuje podpisu', edge['ids'])
        elif edge['claim']:
            fact(a, b, W_OWNERSHIP, source_group(nodes[a]), 'ownership_claim',
                 'Jednostronna jawna deklaracja (rel=me, sameAs, pole strony WWW lub deklaracja własności)', edge['ids'])
        else:
            fact(a, b, W_LINK, source_group(nodes[a]), 'one_way_link', 'Jednostronny odnośnik', edge['ids'])

    for host, owners in sites.items():
        site_rep = next((R(i) for i in eligible if _personal_site(nodes[i], known_domains) == host), None)
        owners = {k: v for k, v in owners.items() if k != site_rep}
        if len(owners) > POPULAR_CAP:
            skipped.append({'kind': 'shared_website', 'group': 'site:' + host, 'accounts': len(owners)})
            continue
        members = sorted(owners)
        for i, a in enumerate(members):
            for b in members[i + 1:]:
                declared = a in site_claims[host] and b in site_claims[host]
                fact(a, b, W_SITE if declared else W_SITE_MENTION, 'site:' + host,
                     'shared_website' if declared else 'shared_website_mention',
                     ('Oba konta deklarują prywatną stronę ' if declared else 'Oba konta wspominają prywatną stronę ') + host,
                     owners[a] | owners[b])
    for url, owners in hubs.items():
        pairwise(owners, W_HUB, 'hub:' + url, 'shared_hub', 'Oba konta linkują tę samą stronę-wizytówkę')
    for third, owners in targets.items():
        pairwise(owners, W_TARGET_PROFILE, 'node:' + str(third), 'shared_target', 'Oba konta linkują ten sam trzeci profil')

    aliases = defaultdict(dict)
    for i in eligible:
        alias = _data(nodes[i]).get('alias')
        if R(i) == i and isinstance(alias, str) and 4 <= len(alias) <= 63:
            aliases[alias.casefold()][i] = nodes[i].get('platform')
    for alias, owners in aliases.items():
        if len(owners) > POPULAR_CAP:
            skipped.append({'kind': 'shared_alias', 'group': 'alias:' + alias, 'accounts': len(owners)})
            continue
        members = sorted(owners)
        for x, a in enumerate(members):
            for b in members[x + 1:]:
                if owners[a] != owners[b]:
                    fact(a, b, W_ALIAS, 'alias:' + alias, 'shared_alias',
                         'Identyczny nick na różnych platformach (sam nie wystarcza)', (), [f'{a}.alias', f'{b}.alias'])

    pairs = _score(facts, contradictions)
    union = _union(pairs, contradictions)

    # Group-level reciprocity: an account declared/linked by one member of a
    # suggested group that links back to another member closes the same loop a
    # direct reciprocal link would.  Repeat until no new account joins.
    outgoing, incoming = defaultdict(set), defaultdict(set)
    for a, b in directed:
        outgoing[a].add(b)
        incoming[b].add(a)
    closed = set()
    for _ in range(5):
        added = False
        for x in sorted({R(i) for i in eligible}):
            own_root = union.find(x)
            by_root_in, by_root_out = defaultdict(list), defaultdict(list)
            for a in incoming[x]:
                by_root_in[union.find(a)].append(a)
            for b in outgoing[x]:
                by_root_out[union.find(b)].append(b)
            for root in sorted(set(by_root_in) & set(by_root_out)):
                if root == own_root or (x, root) in closed:
                    continue
                choice = next(((a, b) for a in sorted(by_root_in[root]) for b in sorted(by_root_out[root]) if a != b), None)
                if choice is None:
                    continue
                a, b = choice
                there, back = directed[(a, x)], directed[(x, b)]
                closed.add((x, root))
                # Only an explicit declaration may extend a group; plain links between
                # friends stay review pairs.  Same key as the direct pair: no double count.
                if not (there['claim'] or back['claim']):
                    continue
                added = True
                mutual(x, a, there, back, 'mutual:' + str(min(x, a)) + ':' + str(max(x, a)), 'group_reciprocal',
                       f'Konto #{a} z tej grupy jawnie wskazuje to konto, a ono linkuje konto #{b} z tej samej grupy',
                       f'Konto #{a} z tej grupy linkuje to konto, a ono linkuje konto #{b} z tej samej grupy')
        if not added:
            break
        pairs = _score(facts, contradictions)
        union = _union(pairs, contradictions)

    groups = defaultdict(list)
    for p in pairs:
        if p['tier'] == 'cluster' and union.find(p['a']) == union.find(p['b']):
            groups[union.find(p['a'])].append(p)
    pages = defaultdict(list)
    for page, root in rep.items():
        if page != root:
            pages[root].append(page)
    clusters = []
    for bridges in groups.values():
        members = sorted({x for p in bridges for x in (p['a'], p['b'])})
        clusters.append({'members': members, 'bridges': bridges,
                         'site_pages': {m: sorted(pages[m]) for m in members if pages.get(m)},
                         'weakest_bridge_probability': min(p['probability'] for p in bridges),
                         'identity_confirmed': False})
    clusters.sort(key=lambda c: (-len(c['members']), c['members']))
    return {'clusters': clusters, 'pairs': pairs, 'skipped_popular_identifiers': skipped,
            'model': {'prior': PRIOR, 'cluster_threshold': STRONG, 'review_threshold': SUGGEST,
                      'popular_identifier_cap': POPULAR_CAP, 'calibrated': False}}


def known_domains():
    from .context import SITES
    from .identity import SERVICES
    return {d.lower() for d in SITES} | {d.lower() for d in SERVICES}


def view(snapshot, limit=20):
    """JSON-safe panel/report view: clusters touching your accounts first."""
    result = build(snapshot, known_domains())
    nodes = {n['id']: n for n in snapshot['nodes']}
    focus = {f['node'] for f in snapshot.get('focus', [])}

    def member(i):
        n = nodes[i]
        return {'id': i, 'url': n['url'], 'platform': n.get('platform'), 'ownership': n.get('ownership'),
                'alias': _data(n).get('alias'), 'focus': i in focus}

    clusters = []
    for c in result['clusters']:
        people = [member(i) for i in c['members']]
        platforms = defaultdict(int)
        for p in people:
            platforms[p['platform']] += 1
        clusters.append(c | {'members': people,
                             'contains_your_account': any(p['ownership'] == 'mine' or p['focus'] for p in people),
                             'unreviewed': [p['id'] for p in people if p['ownership'] == 'unknown'],
                             'same_platform_accounts': sorted(k for k, v in platforms.items() if v > 1)})
    clusters.sort(key=lambda c: (not c['contains_your_account'], -len(c['members'])))
    yours = {n['id'] for n in snapshot['nodes'] if n.get('ownership') == 'mine'} | focus
    for c in result['clusters']:
        ids = set(c['members']) | {p for pages in c['site_pages'].values() for p in pages}
        if ids & yours:
            yours |= ids
    review = [p | {'members': [member(p['a']), member(p['b'])], 'touches_your_accounts': bool({p['a'], p['b']} & yours)}
              for p in result['pairs'] if p['tier'] == 'review']
    review.sort(key=lambda p: (not p['touches_your_accounts'], -p['score']))
    return {'clusters': clusters[:limit], 'clusters_total': len(clusters),
            'review_pairs': review[:limit], 'review_pairs_total': len(review), 'model': result['model'],
            'skipped_popular_identifiers': len(result['skipped_popular_identifiers']),
            'note': 'Sugestie z publicznych dowodów. Nie zmieniają własności i nie potwierdzają tożsamości.'}
