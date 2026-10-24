"""Learn the naming scheme behind a person's own handles, propose related ones.

People reuse one stem across platforms and add small tokens to it: a word
("quillon" → "quillonior") or a run of digits ("quillon" → "quillon111111"), and on
some sites a discriminator like a Riot tag ("quillon#2tag").  When only the
suffixed forms are known, the bare stem is very often the person's handle
somewhere else, and vice versa.

This module reads the user's *confirmed* handles and proposes related handles as
search candidates.  They are candidates for review only: a matching handle never
proves ownership, and nothing here changes a label or runs a query by itself.
"""
import re

HANDLE = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.-]{0,62}')
# The token added to a stem: a digit run, or a short word, optionally with a separator.
SUFFIX = re.compile(r'^_?[0-9]{1,8}$|^_?[a-z]{1,8}$')
MIN_ROOT = 4
CAP = 8


def _split(alias):
    """A handle without its platform discriminator (Riot #tag, Discord #0001)."""
    return re.split(r'[#@]', alias, 1)[0]


def _stem(forms):
    """The shared prefix most of the handles start with (case-insensitive), length >= MIN_ROOT."""
    counts = {}
    for f in forms:
        low = f.lower()
        for end in range(MIN_ROOT, len(low) + 1):
            prefix = low[:end]
            if sum(1 for g in forms if g.lower().startswith(prefix)) >= 2:
                counts[prefix] = sum(1 for g in forms if g.lower().startswith(prefix))
    if not counts:
        return None, 0
    best = max(counts, key=lambda p: (counts[p], len(p)))
    # Display it with the casing of the first handle that carries it.
    display = next((f[:len(best)] for f in forms if f.lower().startswith(best)), best)
    return display, counts[best]


def scheme(aliases):
    """From known handles, return the shared stem, the suffix tokens, and new candidate handles."""
    forms = []
    for a in aliases:
        if not isinstance(a, str):
            continue
        bare = _split(a.strip())
        if HANDLE.fullmatch(bare) and bare.lower() not in (f.lower() for f in forms):
            forms.append(bare)
    lowered = {f.lower() for f in forms}

    stem, family = _stem(forms)
    suffixes = []
    if stem:
        for f in forms:
            if f.lower().startswith(stem.lower()) and len(f) > len(stem):
                token = f[len(stem):]
                if SUFFIX.match(token.lower()) and token.lower() not in (s.lower() for s in suffixes):
                    suffixes.append(token)
    suffix_kinds = [{'text': s, 'kind': 'digits' if s.lstrip('_').isdigit() else 'word'} for s in suffixes]

    candidates = []

    def add(alias, basis):
        if HANDLE.fullmatch(alias) and alias.lower() not in lowered and alias.lower() not in (c['alias'].lower() for c in candidates):
            candidates.append({'alias': alias, 'basis': basis})

    # 1. The bare stem itself — the strongest related handle when only suffixed forms are known.
    if stem and family >= 2 and stem.lower() not in lowered:
        add(stem, 'Wspólny rdzeń Twoich potwierdzonych nicków; sam rdzeń bywa osobnym kontem. Tylko kandydatura do oceny.')

    # 2. The stem recombined with each suffix the person is known to use elsewhere.
    if stem:
        for s in suffixes:
            add(stem + s, 'Twój rdzeń „' + stem + '” z końcówką „' + s + '”, której używasz na innym koncie. Tylko kandydatura.')

    return {'root': stem, 'suffixes': suffix_kinds, 'forms': forms, 'candidates': candidates[:CAP]}


def related_terms(aliases, limit=CAP):
    """Just the candidate handle strings, for feeding discovery as reviewable terms."""
    return [c['alias'] for c in scheme(aliases)['candidates']][:limit]
