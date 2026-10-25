"""Explicit platform account kinds are not inferred human identities."""

import json

NON_PERSON = {'organization', 'bot', 'group', 'service_account'}


def non_person_type(value):
    return isinstance(value, str) and value in NON_PERSON


def api_fields(body):
    kind = body.get('type')
    if kind not in ('User', 'Organization', 'Bot'):
        return {}
    return {
        'entity_type': {'User': 'account', 'Organization': 'organization', 'Bot': 'bot'}[kind],
        'entity_type_source': 'platform_api',
        'platform_account_type': kind,
    }


def non_person(node):
    data = node.get('data', {})
    if isinstance(data, str):
        try:
            data = json.loads(data)
        except (ValueError, TypeError):
            return False
    return isinstance(data, dict) and non_person_type(data.get('entity_type'))
