import json
import re
import html
from .identity import EMAIL


def outgoing_url(value):
    from .identity import normalize

    try:
        normalize(value)
        return value
    except (ValueError, TypeError, AttributeError):
        return None


LABELS = {
    'pl': {
        'scope': 'Wyłącznie zapisane publiczne źródła; brak wyniku nie oznacza braku konta.',
        'omitted': '[pominięty e-mail]',
        'items': 'Elementy',
        'items_html': 'Elementy i profile',
        'evidence': 'Dowody',
        'groups': 'Sugerowane grupy kont',
        'sources': 'Źródła dowodów',
        'full': 'Pełne dane raportu',
        'title': 'NickTrail — raport',
        'h1': 'NickTrail — raport lokalny',
        'intro': 'Relacja nie oznacza wspólnego właściciela. Wyniki obejmują wyłącznie sprawdzone źródła.',
        'ownership': 'własność',
        'source': 'źródło',
        'decision': 'ocena relacji',
        'current': 'aktualny',
        'archived': 'archiwalny',
        'group': 'Grupa ({n} kont, najsłabszy most {p}%)',
        'proof': 'dowody',
        'scope_h': 'Zakres wyszukiwań',
        'reason': 'Powód znalezienia kandydata nie jest dowodem wspólnego właściciela.',
        'element': 'Element',
        'searched': 'szukano',
        'searched_at': 'Szukano',
        'state': 'stan',
    },
    'en': {
        'scope': 'Saved public sources only; no result does not mean no account.',
        'omitted': '[email omitted]',
        'items': 'Items',
        'items_html': 'Items and profiles',
        'evidence': 'Evidence',
        'groups': 'Suggested account groups',
        'sources': 'Evidence sources',
        'full': 'Full report data',
        'title': 'NickTrail — report',
        'h1': 'NickTrail — local report',
        'intro': 'A relationship does not mean a shared owner. Results cover only the sources that were checked.',
        'ownership': 'ownership',
        'source': 'source',
        'decision': 'relation decision',
        'current': 'current',
        'archived': 'archived',
        'group': 'Group ({n} accounts, weakest bridge {p}%)',
        'proof': 'evidence',
        'scope_h': 'Search scope',
        'reason': 'Why a candidate was found is not evidence of a shared owner.',
        'element': 'Item',
        'searched': 'searched for',
        'searched_at': 'Searched',
        'state': 'state',
    },
}


def export(store, project, fmt="json", omit_email=False, exclude=(), include_sensitive=False, language="pl"):
    """Report wording follows the interface language; record contents keep their original language."""
    import json as _json
    from .localization import translate_message

    language = language if language in LABELS else 'en'
    L = LABELS[language]

    def T(text):
        return text if language == 'pl' else translate_message(str(text), 'en')

    raw = store.snapshot(project)
    blocked = set(exclude)
    if omit_email:
        blocked |= {n["id"] for n in raw["nodes"] if n["kind"] == "email"}
    if not include_sensitive:
        from .sensitive import is_sensitive_url

        blocked |= {
            n["id"]
            for n in raw["nodes"]
            if _json.loads(n["data"]).get("sensitive") or is_sensitive_url(n["url"])
        }
    nodes = [n for n in raw["nodes"] if n["id"] not in blocked]
    evidence = [e for e in raw["evidence"] if e["source"] not in blocked and e["target"] not in blocked]
    # Exclude scan queues/notes: they can carry identifiers of excluded nodes.
    payload = {"project": raw["projects"], "nodes": nodes, "evidence": evidence, "scope": L["scope"]}
    from .independence import provenance

    payload['evidence_provenance'] = provenance({'nodes': nodes, 'evidence': evidence})
    payload['focus'] = [f for f in raw.get('focus', []) if f['node'] not in blocked]
    from .search import results, hints

    payload['candidate_hints'] = [h for h in hints(store, project) if h['node'] not in blocked]
    payload['historical_addresses'] = [a for a in raw.get('addresses', []) if a['node'] not in blocked]
    from .entitylinks import view as identity_view

    payload['identity_clusters'] = identity_view(
        {'nodes': nodes, 'evidence': evidence, 'focus': payload['focus']}, limit=100
    )
    if language != 'pl':
        clusters = payload['identity_clusters']
        clusters['note'] = T(clusters.get('note', ''))
        for c in clusters.get('clusters', []):
            for b in c.get('bridges', []):
                for f in b.get('facts', []):
                    f['why'] = T(f.get('why', ''))
    # Opt-in sensitive sources are left out of the scope too: their task details name
    # the sites and handles that were checked.
    payload['discovery_scope'] = [
        {
            'id': r['run']['id'],
            'started': r['run']['started'],
            'status': r['run']['status'],
            'sources': [
                {'platform': s['platform'], 'state': s['state'], 'detail': T(s['detail'])}
                for s in r['sources']
                if include_sensitive or s['platform'] != 'Sensitive'
            ],
        }
        for r in results(store, project)
    ]
    if omit_email:

        def redact(v):
            if isinstance(v, str):
                return EMAIL.sub(L["omitted"], v)
            if isinstance(v, list):
                return [redact(x) for x in v]
            if isinstance(v, dict):
                return {k: redact(x) for k, x in v.items()}
            return v

        payload = redact(payload)
    if fmt == "json":
        return json.dumps(payload, ensure_ascii=False, indent=2)
    if fmt == 'html':
        safe_html = html.escape(json.dumps(payload, ensure_ascii=False, indent=2))

        def link(value):
            safe = html.escape(value, quote=True)
            return (
                '<a target="_blank" rel="noopener noreferrer" href="' + safe + '">' + safe + '</a>'
                if outgoing_url(value)
                else safe
            )

        profiles = (
            '<h2>'
            + html.escape(L['items_html'])
            + '</h2><ul>'
            + ''.join(
                '<li>' + link(n['url']) + ' — ' + html.escape(n['ownership']) + '</li>'
                for n in payload['nodes']
            )
            + '</ul>'
        )
        groups = (
            '<h2>'
            + html.escape(L['groups'])
            + '</h2><p>'
            + html.escape(payload['identity_clusters']['note'])
            + '</p><ul>'
            + ''.join(
                '<li>'
                + ', '.join(link(m['url']) for m in c['members'])
                + '<ul>'
                + ''.join(
                    '<li>' + html.escape('; '.join(f['why'] for f in b['facts'])) + '</li>'
                    for b in c['bridges']
                )
                + '</ul></li>'
                for c in payload['identity_clusters']['clusters']
            )
            + '</ul>'
        )
        sources = (
            '<h2>'
            + html.escape(L['sources'])
            + '</h2><ul>'
            + ''.join(
                '<li>' + link(e['source_url']) + ' — ' + html.escape(e['snippet']) + '</li>'
                for e in payload['evidence']
            )
            + '</ul>'
        )
        return (
            '<!doctype html><html lang="'
            + language
            + '"><meta charset="utf-8"><meta name="referrer" content="no-referrer"><meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'"><title>'
            + html.escape(L['title'])
            + '</title><style>body{max-width:1000px;margin:40px auto;padding:20px;font:16px system-ui}pre{white-space:pre-wrap;overflow-wrap:anywhere}</style><h1>'
            + html.escape(L['h1'])
            + '</h1><p>'
            + html.escape(L['intro'])
            + '</p>'
            + profiles
            + groups
            + sources
            + '<details><summary>'
            + html.escape(L['full'])
            + '</summary><pre>'
            + safe_html
            + '</pre></details></html>'
        )

    def safe(value):
        value = str(value).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        return re.sub(r"([\\`*_{}\[\]()#+.!|>~-])", r"\\\1", value).replace("\n", " ")

    def md_link(value):
        from urllib.parse import quote

        return (
            '<' + quote(value, safe=":/?#[]@!$&'()*+,;=%-._~") + '>' if outgoing_url(value) else safe(value)
        )

    lines = ["# NickTrail", "", payload["scope"], "", "## " + L["items"], ""]
    lines += [
        f"- {md_link(n['url'])} — {safe(n['state'])}; {L['ownership']}: {safe(n['ownership'])}"
        for n in payload["nodes"]
    ]
    lines += ["", "## " + L["evidence"], ""]
    lines += [
        f"- {e['source']} → {e['target']}: {safe(e['relation'])}; {safe(e['snippet'])}; {L['source']}: {md_link(e['source_url'])}; {safe(e['fetched'])}; {L['decision']}: {safe(e['decision'])}; {L['current'] if e.get('current',1) else L['archived']}"
        for e in payload["evidence"]
    ]
    clusters = payload['identity_clusters']
    lines += ['', '## ' + L['groups'], '', safe(clusters['note']), '']
    for c in clusters['clusters']:
        lines += [
            "- "
            + L['group'].format(n=len(c['members']), p=round(c['weakest_bridge_probability'] * 100))
            + ": "
            + ', '.join(md_link(m['url']) for m in c['members'])
        ]
        lines += [
            f"  - {b['a']} ↔ {b['b']}: "
            + '; '.join(
                safe(f['why']) + ' [' + L['proof'] + ': ' + ', '.join(map(str, f['evidence'])) + ']'
                for f in b['facts']
            )
            for b in c['bridges']
        ]
    lines += ['', '## ' + L['scope_h'], '']
    lines += [L['reason'], '']
    lines += [
        f"- {L['element']} {h['node']}: {safe(h['basis'])}; {L['searched']} {safe(h['term'])}"
        for h in payload['candidate_hints']
    ]
    for run in payload['discovery_scope']:
        lines += [f"{L['searched_at']} {safe(run['started'])}; {L['state']}: {safe(run['status'])}", '']
        lines += [
            f"- {safe(s['platform'])}: {safe(s['state'])} — {safe(s['detail'])}" for s in run['sources']
        ]
    return "\n".join(lines) + "\n"
