"""Definitions, capabilities and observations are different concepts; no template-count claims."""

from .providers import REGISTRY
from .engineconfig import instances
from .servicecatalog import services as native_templates
from .extended import services as imported_templates
from .coverage import describe
from .forums import HOSTS


def matrix(store=None):
    observed = {r['id']: r for r in describe()}
    rows = []
    experimental = instances()
    for id, p in REGISTRY.items():
        status = (
            'INDEX_ONLY'
            if p.scope in ('web_index', 'domain_index')
            else (
                'API_KEY_REQUIRED'
                if p.required_env
                else 'MANUAL' if id in ('Free', 'Extended') else 'PUBLIC_API'
            )
        )
        if id in experimental and experimental[id]['live_status'] == 'UNTESTED':
            status = 'EXPERIMENTAL_PUBLIC_API'
        rows.append(
            {
                'id': id,
                'group': 'provider',
                'status': status,
                'configured': bool(p.available()),
                'exact_username': p.supports_exact,
                'context_search': p.context_search,
                'profile_extraction': p.scope in ('public_api', 'platform_search'),
                'live_test': observed[id]['live_test']['state'],
                'limitations': observed[id]['limitations'],
            }
        )
    for row in native_templates():
        rows.append(
            {
                'id': row['id'],
                'group': 'Free',
                'status': 'PUBLIC_HTML',
                'configured': True,
                'exact_username': True,
                'context_search': False,
                'profile_extraction': 'strict_metadata_only',
                'live_test': row['validation']['live_status'],
                'limitations': 'Szablon URL; blokady i niejednoznaczne odpowiedzi wymagają kontroli ręcznej.',
            }
        )
    for row in imported_templates():
        rows.append(
            {
                'id': row['id'],
                'group': 'Extended',
                'status': 'DEFINITION_UNVALIDATED',
                'configured': True,
                'exact_username': True,
                'context_search': False,
                'profile_extraction': 'strict_metadata_only',
                'live_test': 'not_tested',
                'limitations': 'Import MIT; polityka robots i rygorystyczny odczyt. Definicja nie potwierdza dostępności.',
            }
        )
    stable_ids = {
        'GitHub',
        'GitLab',
        'Roblox',
        'Bluesky',
        'DEV',
        'Codeberg',
        'Gitea',
        'ChessCom',
        'Keybase',
        'Modrinth',
        'RubyGems',
        'HuggingFace',
        'CratesIO',
        'Speedrun',
    }
    for row in rows:
        provider = row['group'] == 'provider'
        source = observed.get(row['id'], {})
        row['verification'] = source.get('verification', False) if provider else 'strict_public_metadata'
        row['enrichment'] = source.get('enrichment', False) if provider else 'limited_public_metadata'
        row['outbound_links'] = source.get('outbound_links', False) if provider else 'only_if_readable'
        row['stable_id'] = (
            'supported'
            if provider and (row['id'] in stable_ids or row['id'] in HOSTS or row['id'] in experimental)
            else 'not_declared'
        )
        row['live_tested_at'] = source.get('live_test', {}).get('checked_at') if provider else None
        row['requires_configuration'] = bool(REGISTRY[row['id']].required_env) if provider else False
        from .engineconfig import HTML_ENGINES

        if provider and experimental.get(row['id'], {}).get('engine') in HTML_ENGINES:
            row.update(
                status='EXPERIMENTAL_PUBLIC_HTML',
                profile_extraction='strict_metadata_only',
                verification='strict_public_metadata',
                enrichment='limited_public_metadata',
                outbound_links='only_if_readable',
                stable_id='not_declared',
            )
    observations = __import__('nicktrail.health', fromlist=['latest']).latest(store) if store else {}
    for row in rows:
        row['health_key'] = row['group'] + ':' + row['id']
        row['health'] = observations.get(
            row['health_key'], {'status': 'UNTESTED', 'confidence': 'not_operationally_validated'}
        )
    return {
        'rows': rows,
        'counts': {
            'providers': len(REGISTRY),
            'strict_templates': len(native_templates()),
            'imported_definitions': len(imported_templates()),
        },
        'note': 'Liczby definicji i dostawców mogą obejmować te same serwisy. To nie liczba skutecznie przeszukanych witryn.',
    }


def presets():
    from .scanmodes import presets as modes

    return modes()
