"""Use what the user declared about themselves in their own searches.

Declarations are entries the user added in "Moje konta i znane adresy"
(nick, display name, e-mail, country, language).  Only entries the user
confirmed as theirs ("mine") are used, and only in ways that stay inside
the self-audit rules:

  * nick           -> searched as an extra alias in each new search;
  * display name   -> searched by name where a service has a people search,
                      and matched against profile names (only when no
                      keywords were given);
  * country        -> used as the location when none was given;
  * e-mail         -> never sent anywhere.  It links accounts that publicly
                      show the same address (that happens when profiles are
                      read) and pre-fills the user's own exposure check;
  * language       -> kept as information only.

Nothing here infers ownership: a profile matching a declared nick is still a
candidate until the user marks it.
"""

from .related import terms_for

MAX_ALIASES = 4


def declared(store, project):
    rows = store.rows(
        "SELECT kind,url FROM nodes WHERE project=? AND platform='Deklaracja' AND ownership='mine' ORDER BY id",
        (project,),
    )
    out = {'alias': [], 'display': [], 'email': [], 'country': [], 'language': []}
    for row in rows:
        values = out.get(row['kind'])
        if values is not None and row['url'] not in values:
            values.append(row['url'])
    return out


def apply(store, project, nickname, aliases, criteria):
    """Return (nickname, aliases, criteria, used) with the user's own declarations added."""
    from .context import criteria as validate, terms as context_terms

    if not isinstance(nickname, (str, type(None))) or not isinstance(aliases, (list, tuple, type(None))):
        return nickname, aliases, criteria, {}  # let the normal validation report the bad input
    found = declared(store, project)
    nickname = (nickname or '').strip()
    aliases = list(aliases or [])
    criteria = dict(validate(criteria))
    used = {}
    valid = []
    for alias in found['alias']:
        try:
            valid.append(terms_for(alias)[0])
        except ValueError:
            continue
    if not nickname and not context_terms(criteria) and valid:
        nickname = valid[0]
        used['nickname'] = nickname
    if nickname:
        taken = {nickname.casefold(), *(a.casefold() for a in aliases)}
        extra = [a for a in valid if a.casefold() not in taken][: max(0, MAX_ALIASES - len(aliases))]
        if extra:
            aliases += extra
            used['aliases'] = extra
    if (
        found['display']
        and not criteria.get('keywords')
        and not (criteria.get('first_name') or criteria.get('last_name'))
    ):
        criteria['keywords'] = found['display'][0][:160]
        used['display'] = criteria['keywords']
    if found['country'] and not criteria.get('location'):
        criteria['location'] = found['country'][0][:160]
        used['country'] = criteria['location']
    return nickname, aliases, criteria, used


def describe(used):
    values = ([used['nickname']] if used.get('nickname') else []) + list(used.get('aliases', []))
    values += [used[k] for k in ('display', 'country') if used.get(k)]
    return ', '.join(values)
