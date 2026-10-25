"""Explicit single-URL Wayback lookups. Historical links never become current proof."""

import datetime, ipaddress, json, re
from urllib.parse import urlsplit, urlunsplit, urlencode, unquote
from .storage import SCHEMA_LOCK, now
from .identity import identify


def schema(store):
    with SCHEMA_LOCK:
        store.db.execute(
            '''CREATE TABLE IF NOT EXISTS archive_checks(id INTEGER PRIMARY KEY,project INTEGER REFERENCES projects ON DELETE CASCADE,node INTEGER REFERENCES nodes ON DELETE CASCADE,original_url TEXT,requested_date TEXT,checked TEXT,state TEXT,detail TEXT,snapshot_url TEXT DEFAULT '',captured_at TEXT DEFAULT '',aliases TEXT DEFAULT '[]',leads TEXT DEFAULT '[]',evidence_ids TEXT DEFAULT '[]',requests INTEGER DEFAULT 0,UNIQUE(project,node,original_url,requested_date))'''
        )
        store.db.commit()


def public_url(value):
    if not isinstance(value, str):
        raise ValueError('Public URL required')
    url = identify(value)['url']
    p = urlsplit(url)
    host = p.hostname or ''
    if (
        '.' not in host
        or host == 'localhost'
        or host.endswith(('.localhost', '.local', '.internal', '.onion'))
    ):
        raise ValueError('Public hostname required')
    try:
        ipaddress.ip_address(host)
    except ValueError:
        pass
    else:
        raise ValueError('Archive lookup is restricted to named public websites')
    if any(
        re.search(
            r'(?i)(?:^|[?&])(?:password|passwd|api[_-]?key|access[_-]?token|token|cookie|authorization)=',
            part,
        )
        for part in (p.query, '?' + p.query)
    ):
        raise ValueError('Secret-like query parameters refused')
    return url


def preview(store, project, node_id, date):
    node = store.node(node_id)
    if (
        node['project'] != project
        or node['kind'] not in ('profile', 'page')
        or node['ownership'] == 'not_mine'
    ):
        raise ValueError('Choose a non-rejected public profile/page from this project')
    try:
        day = datetime.date.fromisoformat(date)
    except (ValueError, TypeError):
        raise ValueError('Use archive date YYYY-MM-DD')
    if day.year < 1996:
        raise ValueError('Archive date must be 1996 or later')
    original = public_url(node['url'])
    return {
        'project': project,
        'node': node_id,
        'original_url': original,
        'requested_date': day.isoformat(),
        'lookup_url': 'https://archive.org/wayback/available?'
        + urlencode({'url': original, 'timestamp': day.strftime('%Y%m%d')}),
        'max_requests': 4,
        'max_links': 10,
        'network_calls': 0,
        'notice': 'This sends one public URL/date to Internet Archive only when explicitly run. Historical traces are leads, not current ownership proof.',
    }


def snapshot_identity(value, original):
    if not isinstance(value, str):
        raise ValueError('Invalid archive snapshot URL')
    p = urlsplit(value)
    if (
        p.hostname != 'web.archive.org'
        or p.scheme not in ('http', 'https')
        or p.username
        or p.password
        or p.port not in (None, 80, 443)
    ):
        raise ValueError('Archive snapshot left allowed host')
    match = re.fullmatch(r'/web/([0-9]{14})/(https?://.+)', p.path)
    if not match:
        raise ValueError('Invalid archive capture route')
    captured = (
        datetime.datetime.strptime(match[1], '%Y%m%d%H%M%S').replace(tzinfo=datetime.timezone.utc).isoformat()
    )
    embedded = match[2] + ('?' + p.query if p.query else '')
    if public_url(embedded) != original:
        raise ValueError('Archive snapshot points to a different original resource')
    return urlunsplit(('https', 'web.archive.org', p.path, p.query, '')), captured


def history(store, project, node=None):
    schema(store)
    rows = store.rows(
        'SELECT * FROM archive_checks WHERE project=?'
        + (' AND node=?' if node is not None else '')
        + ' ORDER BY id DESC LIMIT 50',
        (project, node) if node is not None else (project,),
    )
    for row in rows:
        for key in ('aliases', 'leads', 'evidence_ids'):
            row[key] = json.loads(row[key])
    return rows


def lookup(
    store, project, node_id, date, read_content=False, consent=False, client=None, stopped=lambda: False
):
    if type(read_content) is not bool or consent is not True:
        raise ValueError('Explicit consent to archive lookup required')
    plan = preview(store, project, node_id, date)
    schema(store)
    previous = store.rows(
        'SELECT * FROM archive_checks WHERE project=? AND node=? AND original_url=? AND requested_date=?',
        (project, node_id, plan['original_url'], date),
    )
    cached = (
        previous
        and (
            datetime.datetime.now(datetime.timezone.utc)
            - datetime.datetime.fromisoformat(previous[0]['checked'])
        ).total_seconds()
        < 86400
    )

    def result():
        row = store.rows(
            'SELECT * FROM archive_checks WHERE project=? AND node=? AND original_url=? AND requested_date=?',
            (project, node_id, plan['original_url'], date),
        )[0]
        for key in ('aliases', 'leads', 'evidence_ids'):
            row[key] = json.loads(row[key])
        return row

    if (
        cached
        and previous[0]['state'] in ('paused', 'limited', 'cancelled')
        and not previous[0]['snapshot_url']
    ):
        cached = False
    if cached and (
        not read_content or previous[0]['state'] not in ('available', 'paused', 'limited', 'cancelled')
    ):
        return result() | {'cached': True}
    from .network import Client, Limit

    session = client or Client(queries=4, seconds=35, per_domain=3)
    initial = session.count
    from .cooldowns import bind as bind_cooldowns

    bind_cooldowns(session, store)
    snapshot = ''
    captured = ''
    state = 'error'
    detail = ''
    aliases = []
    leads = []
    eids = []

    def save():
        store.execute(
            '''INSERT INTO archive_checks(project,node,original_url,requested_date,checked,state,detail,snapshot_url,captured_at,aliases,leads,evidence_ids,requests) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(project,node,original_url,requested_date) DO UPDATE SET checked=excluded.checked,state=excluded.state,detail=excluded.detail,snapshot_url=excluded.snapshot_url,captured_at=excluded.captured_at,aliases=excluded.aliases,leads=excluded.leads,evidence_ids=excluded.evidence_ids,requests=excluded.requests''',
            (
                project,
                node_id,
                plan['original_url'],
                date,
                now(),
                state,
                detail,
                snapshot,
                captured,
                json.dumps(aliases),
                json.dumps(leads),
                json.dumps(eids),
                session.count - initial + (previous[0]['requests'] if cached else 0),
            ),
        )

    try:
        if stopped():
            state = 'paused'
            detail = 'Archive lookup paused before network'
            save()
            return result()
        if cached:
            snapshot = previous[0]['snapshot_url']
            captured = previous[0]['captured_at']
            state = 'available'
        else:
            response = session.get(plan['lookup_url'])
            if response['state'] != 'found':
                state = response['state']
                detail = response.get('detail', 'Archive metadata unavailable')
                save()
                return result()
            body = json.loads(response['text'])
            closest = (
                body.get('archived_snapshots', {}).get('closest')
                if isinstance(body, dict) and isinstance(body.get('archived_snapshots', {}), dict)
                else None
            )
            if (
                not isinstance(closest, dict)
                or closest.get('available') is not True
                or str(closest.get('status')) != '200'
            ):
                state = 'no_snapshot'
                detail = (
                    'No available successful snapshot returned; this does not prove no historical presence.'
                )
                save()
                return result()
            snapshot, captured = snapshot_identity(closest.get('url'), plan['original_url'])
            state = 'available'
            detail = 'Metadata only; snapshot content has not been read.'
        if stopped() or store.node(node_id)['ownership'] == 'not_mine':
            state = 'paused' if stopped() else 'cancelled'
            detail = 'Stopped or source rejected; no further archive processing'
            save()
            return result()
        if read_content:
            response = getattr(session, 'profile_get', session.get)(snapshot)
            if response['state'] != 'found':
                state = response['state']
                detail = response.get('detail', 'Snapshot not readable')
            else:
                if stopped() or store.node(node_id)['ownership'] == 'not_mine':
                    state = 'paused' if stopped() else 'cancelled'
                    detail = 'Stopped or source rejected; snapshot not converted to leads'
                    save()
                    return result()
                actual, actual_time = snapshot_identity(response.get('url') or snapshot, plan['original_url'])
                snapshot, captured = actual, actual_time
                from .publicprofile import ProfileHTML
                from .freeprofiles import Meta
                from .adapters import extract
                from .aipacket import scrub

                html = response.get('text', '')
                page = ProfileHTML()
                page.feed(html)
                page.close()
                meta = Meta()
                meta.feed(html)
                alias = meta.values.get('profile:username', '')
                if isinstance(alias, str) and re.fullmatch(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}', alias):
                    aliases = [
                        {
                            'alias': alias,
                            'source': 'archived_profile_metadata',
                            'observed_at': captured,
                            'identity_confirmed': False,
                        }
                    ]
                original_links = []
                for link in page.links:
                    candidate = 'https://web.archive.org' + link if link.startswith('/web/') else link
                    wrapper = urlsplit(candidate)
                    if wrapper.hostname == 'web.archive.org':
                        wrapped = re.fullmatch(r'/web/[0-9]{14}(?:[a-z_]{1,4})?/(https?://.+)', wrapper.path)
                        if not wrapped:
                            continue
                        candidate = wrapped[1] + ('?' + wrapper.query if wrapper.query else '')
                    original_links.append(candidate)
                items = extract(
                    '\n'.join(page.parts), plan['original_url'], 'historical_snapshot', links=original_links
                )
                seen = set()
                for item in items:
                    if 'url' not in item:
                        continue
                    try:
                        url = public_url(item['url'])
                    except ValueError:
                        continue
                    if (
                        urlsplit(url).hostname in ('archive.org', 'web.archive.org', 'analytics.archive.org')
                        or url == plan['original_url']
                        or url in seen
                    ):
                        continue
                    target = store.add(project, url, seed=False)
                    seen.add(url)
                    store.execute(
                        '''INSERT OR IGNORE INTO evidence(project,source,target,relation,source_url,location,snippet,fetched,method,assessment,post_date,context,last_seen,current) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,0)''',
                        (
                            project,
                            node_id,
                            target,
                            'links',
                            snapshot,
                            'historical_snapshot',
                            scrub(item.get('snippet', ''))[:500],
                            now(),
                            'historical_archive',
                            'clue',
                            captured,
                            'own',
                            now(),
                        ),
                    )
                    evidence = store.rows(
                        "SELECT id FROM evidence WHERE project=? AND source=? AND target=? AND source_url=? AND method='historical_archive'",
                        (project, node_id, target, snapshot),
                    )
                    eids.extend(r['id'] for r in evidence)
                    leads.append(
                        {
                            'node': target,
                            'url': url,
                            'historical_only': True,
                            'captured_at': captured,
                            'independently_corroborated': bool(
                                store.rows(
                                    "SELECT 1 FROM evidence WHERE target=? AND current=1 AND method IN ('parser','rendered_public_page') AND decision!='rejected' LIMIT 1",
                                    (target,),
                                )
                            ),
                        }
                    )
                    if len(leads) >= 10:
                        break
                state = 'read'
                detail = 'Historical public metadata and at most ten link leads; no current identity or ownership assertion.'
    except Limit:
        state = 'limited'
        detail = 'Archive request/time budget exhausted'
    except (ValueError, KeyError, TypeError, OSError) as e:
        state = 'error'
        detail = 'Archive parse/policy failure: ' + type(e).__name__
    save()
    return result()


def auto_targets(store, project, limit=5):
    """Most relevant saved accounts for an automatic archive check after a search.

    Your accounts and their suggested group first, then the best ranked read
    profiles.  Rejected accounts are never sent anywhere.
    """
    from .deadends import connected
    from .ranking import evaluate

    snapshot = store.snapshot(project)
    nodes = {n['id']: n for n in snapshot['nodes']}
    usable = (
        lambda n: n['kind'] in ('profile', 'page') and n['state'] == 'found' and n['ownership'] != 'not_mine'
    )
    reach, _ = connected(snapshot)
    order = [
        i
        for i, how in sorted(reach.items(), key=lambda x: ({'anchor': 0, 'group': 1}.get(x[1], 9), x[0]))
        if how in ('anchor', 'group')
    ]
    order += [i for i in evaluate(snapshot, {}, [])['order']]
    out = []
    for i in order:
        if i in nodes and usable(nodes[i]) and i not in out:
            out.append(i)
        if len(out) >= limit:
            break
    return out


def after_search(store, project, date, limit=5, stopped=lambda: False):
    """Explicitly requested (checkbox = consent) archive metadata checks after a search."""
    results = []
    for node in auto_targets(store, project, limit):
        if stopped():
            break
        try:
            row = lookup(store, project, node, date, read_content=False, consent=True, stopped=stopped)
        except ValueError as error:
            results.append({'node': node, 'state': 'error', 'detail': str(error)})
            continue
        results.append(
            {
                'node': node,
                'state': row['state'],
                'snapshot_url': row.get('snapshot_url', ''),
                'cached': bool(row.get('cached')),
            }
        )
        # Internet Archive rate limits are an availability constraint: stop instead of retrying around them.
        if row['state'] in ('blocked', 'limited'):
            break
    return {
        'checked': len(results),
        'results': results,
        'detail': 'Tylko metadane migawek; treść nie była czytana. Brak migawki nie dowodzi braku konta.',
    }
