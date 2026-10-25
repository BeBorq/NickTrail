"""Bounded discovery then verification, with one visible total budget."""

import json
import time
from .search import discover, results
from .ranking import evaluate
from .engine import scan


def search_and_verify(
    store,
    project,
    nickname,
    platforms=None,
    options=None,
    aliases=(),
    related=True,
    criteria=None,
    verify_top=5,
    stopped=lambda: False,
    client=None,
    variants=False,
    scan_mode='CUSTOM',
):
    if type(verify_top) is not int or not 0 <= verify_top <= 10:
        raise ValueError('Weryfikacja: od 0 do 10 profili')
    opts = {'queries': 40, 'seconds': 120, 'per_domain': 15, 'candidates': 50} | (options or {})
    if (
        set(opts) != {'queries', 'seconds', 'per_domain', 'candidates'}
        or any(type(v) is not int or v < 0 for v in opts.values())
        or not opts['seconds']
    ):
        raise ValueError('Nieprawidłowe limity')
    reserved = min(verify_top, max(0, opts['queries'] // 3))
    started = time.monotonic()
    from .network import Client

    session = client or Client(
        queries=opts['queries'], seconds=opts['seconds'], per_domain=opts['per_domain']
    )
    if hasattr(session, 'maximum'):
        session.maximum = opts['queries'] - reserved
    search_id = discover(
        store,
        project,
        nickname,
        platforms,
        opts | {'queries': opts['queries'] - reserved},
        client=session,
        stopped=stopped,
        aliases=aliases,
        related=related,
        criteria=criteria,
        variants=variants,
        scan_mode=scan_mode,
    )
    if hasattr(session, 'maximum'):
        session.maximum = opts['queries']
    row = next(r for r in results(store, project) if r['run']['id'] == search_id)
    metadata = {'requested': verify_top, 'scan': None, 'reason': ''}
    if not reserved:
        metadata['reason'] = 'Weryfikacja wyłączona lub brak budżetu'
    elif stopped():
        metadata['reason'] = 'Wstrzymano przez użytkownika'
    else:
        params = json.loads(row['run']['options'])
        snapshot = store.snapshot(project)
        ranked = evaluate(snapshot, criteria, params.get('_terms', []))
        ids = {i for s in row['sources'] for i in json.loads(s['nodes'])}
        eligible = {
            n['id']
            for n in snapshot['nodes']
            if n['id'] in ids and n['ownership'] != 'not_mine' and n['kind'] in ('profile', 'page')
        }
        targets = [i for i in ranked['order'] if i in eligible][:verify_top]
        remaining = int(opts['seconds'] - (time.monotonic() - started))
        if targets and remaining > 0:
            offset = session.count
            if hasattr(session, 'maximum'):
                session.maximum = min(opts['queries'], offset + reserved)

            class VerificationClient:
                @property
                def count(self):
                    return session.count - offset

                def get(self, *args, **kwargs):
                    if self.count >= reserved:
                        from .network import Limit

                        raise Limit('Limit drugiego etapu')
                    return session.get(*args, **kwargs)

                def profile_get(self, url):
                    # Same budget, and the robots.txt check of the real client is kept.
                    if self.count >= reserved:
                        from .network import Limit

                        raise Limit('Limit drugiego etapu')
                    return getattr(session, 'profile_get', session.get)(url)

                def post_json(self, *args, **kwargs):
                    if self.count >= reserved:
                        from .network import Limit

                        raise Limit('Limit drugiego etapu')
                    return session.post_json(*args, **kwargs)

            metadata['scan'] = scan(
                store,
                project,
                {
                    'queries': reserved,
                    'seconds': remaining,
                    'profiles': verify_top,
                    'pages': verify_top,
                    'per_domain': opts['per_domain'],
                },
                targets=targets,
                stopped=stopped,
                client=VerificationClient(),
            )
            metadata['reason'] = 'Odczyt najlepiej dopasowanych kandydatów; własność pozostaje bez zmian'
        else:
            metadata['reason'] = 'Brak kandydatów albo czasu na drugi etap'
    saved = json.loads(row['run']['options'])
    saved['_verification'] = metadata
    store.execute(
        'UPDATE searches SET options=? WHERE id=?', (json.dumps(saved, ensure_ascii=False), search_id)
    )
    return search_id
