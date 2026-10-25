"""Bounded local observation history. No archive lookup or identity inference."""

import json

FIELDS = ('alias', 'display', 'declared_location', 'bio', 'description', 'stable_id')


def timeline(store, project, node_id, limit=50):
    if (
        type(project) is not int
        or type(node_id) is not int
        or type(limit) is not int
        or not 1 <= limit <= 100
    ):
        raise ValueError('Invalid history selection')
    node = store.node(node_id)
    if node['project'] != project:
        raise ValueError('History belongs to another project')
    rows = store.rows(
        'SELECT o.scan,o.state,o.data,o.detail,s.started FROM observations o JOIN scans s ON s.id=o.scan WHERE o.node=? AND s.project=? ORDER BY o.scan DESC LIMIT ?',
        (node_id, project, limit + 1),
    )
    truncated = len(rows) > limit
    rows = rows[:limit]
    previous = None
    events = []
    for row in reversed(rows):
        data = json.loads(row['data'] or '{}')
        fields = {k: data[k] for k in FIELDS if isinstance(data.get(k), str) and data[k]}
        changes = []
        if row['state'] == 'found':
            if previous is not None:
                changes = [
                    {'field': key, 'before': previous.get(key), 'after': fields.get(key)}
                    for key in FIELDS
                    if previous.get(key) != fields.get(key)
                ]
            previous = fields
        events.append(
            {
                'scan': row['scan'],
                'observed_at': row['started'],
                'state': row['state'],
                'detail': row['detail'],
                'fields': fields,
                'changes': changes,
                'identity_confirmed': False,
            }
        )
    return {
        'node': node_id,
        'current_url': node['url'],
        'addresses': store.rows(
            'SELECT url,first_seen,last_seen FROM profile_addresses WHERE node=? AND project=? ORDER BY first_seen',
            (node_id, project),
        ),
        'observations': list(reversed(events)),
        'truncated': truncated,
        'note': 'Local saved observations only. Old aliases and descriptions may be outdated; unavailable reads do not prove removal. No identity conclusion.',
    }
