# Contributing to NickTrail

Thanks for helping! NickTrail is a **self-audit** tool: it helps people find and clean up their *own* public
footprint. Contributions must keep it that way.

## Ground rules

- **Public data only.** No sign-in automation, no CAPTCHA solving, no `robots.txt` or rate-limit evasion, no
  proxies or header tricks to get past blocks (including 403 “bypassers”). A blocked site becomes a manual-check item.
- **No private or breached data.** No leak databases, stolen credentials, session cookies or scraping of
  non-public content.
- **Never infer ownership.** A matching nick, name, avatar or location is a lead. Only the user marks “mine”.
- **No profiling of others.** Features must make sense for auditing yourself.
- **Standard library only** for the core (`nicktrail/`). Optional extras must stay optional.

## Adding a source

1. Check `nicktrail/providers.py`, `freeprofiles.py`, `servicecatalog.py` and [docs/SOURCES.md](docs/SOURCES.md)
   first — it may already exist.
2. Read the site's API documentation, terms and `robots.txt`. Prefer an official public API. If access
   needs permissions you do not have, the source is `unsupported`; never fake a response.
3. For address recognition add the host to `nicktrail/services.json` and path tests for
   `identity.identify`. Tell a profile apart from a repository, project, post or sign-in page. For
   federated services keep the instance host.
4. Every read goes through `nicktrail.network.Client.get` (DNS pinning, budgets, robots policy). Never open
   sockets or create a second client, never send browser cookies, never store keys or raw HTML.
5. Validate the exact username and a stable account ID. Treat redirects to another host or user as
   "not confirmed". The adapter contract is: `state` and `detail` for failures; minimal `data` (with a
   stable ID) and an `evidence` list for a successful read.
6. Evidence has an address or email, a `relation`, a `location` and a `snippet`. A link to a project is not
   the owner's account. Do not overwrite the user's decisions.
7. Add offline tests with fixtures: a valid profile, a missing one, a block, malformed data, a project
   link, a quote, and a "similar but different" username.
8. Distinguish *template exists*, *validated read* and *live-tested* in the catalog. A template count is
   not accuracy.

See [docs/HOW-IT-WORKS.md](docs/HOW-IT-WORKS.md) for the pipeline and the data model.

## Interface text

Polish is the source catalog. Any new user-facing text needs an English entry (`nicktrail/translations.json`
for the panel, `nicktrail/system_translations.json` for server messages). `tests/test_localization_complete20.py`
fails if Polish text leaks into the English interface.

## Code style

Code is formatted with [Black](https://black.readthedocs.io/) (settings in `pyproject.toml`): one
statement per line, lines up to 110 characters. Prefer small named helpers over long functions; a rule
about evidence should be readable on its own. CI checks the formatting.

## Before opening a pull request

```bash
black nicktrail tests
python -m unittest discover -s tests -q
for f in tests/test_panel_*.js; do node "$f"; done
python tests/web_smoke.py
python -m compileall -q nicktrail tests
```

Never commit databases (`*.sqlite3`), error logs (`*.errors.log`), API keys, exports or screenshots that show
real people's data. Use fictional data (`*.example` domains) in tests and documentation.
