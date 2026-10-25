"""Offline licensed dataset normalization. Upstream detectors are metadata, never code."""

import datetime, hashlib, re
from urllib.parse import urlsplit
from .identity import normalize

PATTERN = r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}'
SOURCES = {
    'Maigret': 'https://github.com/soxoj/maigret',
    'WhatsMyName': 'https://github.com/WebBreacher/WhatsMyName',
    'Sherlock': 'https://github.com/sherlock-project/sherlock',
}


def convert(kind, payload, revision, license_text='', limit=1000, excluded_routes=()):
    if (
        kind not in SOURCES
        or not re.fullmatch(r'[a-f0-9]{40}', revision)
        or type(limit) is not int
        or not 1 <= limit <= 1500
    ):
        raise ValueError('Pinned source/revision and limit required')
    if kind == 'Sherlock':
        from .catalog_import import convert as sherlock

        return sherlock(payload, revision, license_text, limit, excluded_routes)
    if not isinstance(payload, dict):
        raise ValueError('Expected dataset object')
    if kind == 'Maigret':
        if 'MIT License' not in license_text or 'Soxoj' not in license_text:
            raise ValueError('Maigret MIT attribution required')
        entries = payload.get('sites', {})
        license = 'MIT'
        authors = ['Soxoj']
        if not isinstance(entries, dict) or len(entries) > 20000:
            raise ValueError('Invalid Maigret sites')
        entries = list(entries.items())
    else:
        text = '\n'.join(payload.get('license', []))
        if (
            'Micah Hoffman' not in text
            or 'Creative Commons Attribution-ShareAlike' not in text
            or '4.0' not in text
        ):
            raise ValueError('WhatsMyName CC-BY-SA-4.0 provenance required')
        license = 'CC-BY-SA-4.0'
        license_text = text
        authors = payload.get('authors', [])
        raw = payload.get('sites')
        if not isinstance(raw, list) or len(raw) > 5000:
            raise ValueError('Invalid WhatsMyName sites')
        entries = [(row.get('name', ''), row) for row in raw if isinstance(row, dict)]
    records = []
    rejected = []
    seen = {normalize(t.format(nick='nicktrailfixture')) for t in excluded_routes}
    selection = {}
    imported = datetime.datetime.now(datetime.timezone.utc).isoformat()
    for name, row in entries:
        why = None
        if not isinstance(name, str) or not name or not isinstance(row, dict):
            why = 'schema'
        elif row.get('disabled') or row.get('valid') is False:
            why = 'upstream_disabled'
        elif row.get('engine'):
            why = 'inherited_engine_semantics_not_imported'
        elif (
            row.get('headers')
            or row.get('post_body')
            or row.get('requestPayload')
            or row.get('requestMethod', 'GET') != 'GET'
            or row.get('urlProbe')
        ):
            why = 'unsupported_request_semantics'
        elif row.get('protection'):
            why = 'access_protection_requires_manual_review'
        elif any(
            'nsfw' in str(t).casefold() or str(t).casefold() in ('porn', 'adult')
            for t in row.get('tags', [row.get('cat', '')])
        ):
            why = 'explicit_content_not_selected'
        elif row.get('type', 'username') != 'username':
            why = 'non_username_identifier'
        template = (
            row.get('url', '') if kind == 'Maigret' else row.get('uri_pretty') or row.get('uri_check', '')
        )
        placeholder = '{username}' if kind == 'Maigret' else '{account}'
        if why is None and (
            not isinstance(template, str)
            or template.count(placeholder) != 1
            or '{' in template.replace(placeholder, '')
            or '}' in template.replace(placeholder, '')
            or len(template) > 400
        ):
            why = 'unsafe_template'
        if why is None:
            template = template.replace(placeholder, '{nick}')
            try:
                url = normalize(template.format(nick='nicktrailfixture'))
                p = urlsplit(url)
                if (
                    p.scheme != 'https'
                    or p.query
                    or p.fragment
                    or p.port not in (None, 443)
                    or not p.path.strip('/')
                    and not p.hostname.startswith('nicktrailfixture.')
                ):
                    why = 'unsupported_public_route'
            except ValueError:
                why = 'unsafe_public_url'
        if why is None and url in seen:
            why = 'duplicate_route'
        if why:
            rejected.append({'name': name, 'reason': why})
            continue
        seen.add(url)
        controls = {}
        candidates = (
            [row.get('usernameClaimed'), row.get('usernameUnclaimed')]
            if kind == 'Maigret'
            else [(row.get('known') or [None])[0], None]
        )
        for key, value in zip(('positive', 'negative'), candidates):
            if isinstance(value, str) and re.fullmatch(PATTERN, value):
                controls[key] = value
        rank = row.get('alexaRank')
        rank = rank if type(rank) is int and rank > 0 else 10**12
        tags = {str(t).casefold() for t in row.get('tags', [row.get('cat', '')])}
        selection[name] = (
            0 if len(controls) == 2 else 1,
            0 if tags & {'coding', 'social', 'gaming', 'art', 'blog', 'tech', 'music', 'video'} else 1,
            rank,
            name.casefold(),
        )
        records.append(
            {
                'id': kind + '.' + hashlib.sha256(name.encode()).hexdigest()[:12],
                'name': name,
                'domain': p.hostname,
                'profile_url': template,
                'username_pattern': PATTERN,
                'category': 'imported',
                'detection': {
                    'strategy': 'explicit_profile_metadata',
                    'redirect_policy': 'same_normalized_url',
                    'not_found_titles': ['404 not found', 'page not found', 'user not found'],
                },
                'public_metadata': ['explicit_profile_only'],
                'public_api': False,
                'rate_limits': {'policy': 'robots_and_common_client'},
                'validation': {'live_status': 'UNTESTED', 'coverage_claim': 'definition_only_not_verified'},
                'controls': controls,
                'provenance': {
                    'repository': SOURCES[kind],
                    'revision': revision,
                    'license': license,
                    'source_name': name,
                    'imported_at': imported,
                    'upstream_detector_used': False,
                    'upstream_check_type': row.get('checkType') or 'presence_absence',
                    'upstream_regex_used': False,
                },
            }
        )
    records.sort(key=lambda r: selection[r['name']])
    selected = []
    domains = {}
    for row in records:
        if len(selected) >= limit:
            rejected.append({'name': row['name'], 'reason': 'not_selected_in_bounded_pack'})
            continue
        if domains.get(row['domain'], 0) >= 2:
            rejected.append({'name': row['name'], 'reason': 'duplicate_domain_route_cap'})
            continue
        selected.append(row)
        domains[row['domain']] = domains.get(row['domain'], 0) + 1
    records = selected
    return {
        'schema_version': 1,
        'license': license,
        'license_text': license_text,
        'authors': authors,
        'revision': revision,
        'source': SOURCES[kind],
        'imported_at': imported,
        'services': records,
        'rejected': rejected,
        'notice': 'Normalized routes are modified, unvalidated discovery definitions; upstream detector expressions are not executed. CC-BY-SA packs retain their data license separately from MIT application code.',
    }
