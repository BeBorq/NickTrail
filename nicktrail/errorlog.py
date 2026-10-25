"""Local error log next to the project database.

A failing site or an unexpected response must not end a whole search, but the
cause still has to be findable afterwards.  Tracebacks go to
`<database>.errors.log` beside the user's own database; nothing leaves the
computer.  The file is capped so it cannot grow without bound.
"""

import os
import traceback
from datetime import datetime, timezone

LIMIT = 1_000_000


def path(store):
    base = getattr(store, 'path', None)
    return str(base) + '.errors.log' if base and str(base) != ':memory:' else None


def write(store, where, error):
    target = path(store)
    if not target:
        return None
    try:
        if os.path.exists(target) and os.path.getsize(target) > LIMIT:
            os.replace(target, target + '.old')
        text = ''.join(traceback.format_exception(type(error), error, error.__traceback__))
        with open(target, 'a', encoding='utf-8') as handle:
            handle.write(f"--- {datetime.now(timezone.utc).isoformat()} · {where}\n{text}\n")
    except OSError:
        return None
    return target
