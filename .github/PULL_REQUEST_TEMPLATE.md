## What this changes

## How it was tested
- [ ] `python -m unittest discover -s tests -q`
- [ ] `python tests/web_smoke.py`
- [ ] `for f in tests/test_panel_*.js; do node "$f"; done` (panel changes)
- [ ] New user-facing text has an English translation

## Checklist
- [ ] Public data only; no sign-in automation, CAPTCHA solving or block bypassing
- [ ] Ownership is never inferred from a username, name, photo or location
- [ ] Tests and docs use fictional data only (`*.example`, `fictional-*`)
- [ ] No databases, logs, API keys or exports are committed
