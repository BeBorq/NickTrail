# Security and responsible use

## Intended use

NickTrail is for auditing **your own** public footprint, or one you are explicitly authorised to audit. Do not use
it to investigate, track or profile other people. Keep the project database private: it contains your searches.

## What the tool will not do

- bypass authentication, CAPTCHAs, paywalls, `robots.txt` or rate limits;
- use breached data, stolen credentials or session cookies;
- send your email address or names to services unless you explicitly start a check that needs them
  (for example Have I Been Pwned for your own email, with a consent checkbox);
- decide account ownership automatically.

## Local security model

- The panel binds to `127.0.0.1` only and checks the `Host`/`Origin` headers; state-changing requests need a
  per-session token; cross-site browser requests are refused.
- Outgoing requests go through one client that resolves DNS once, refuses private/reserved addresses, pins the
  IP, limits size, time and redirects, and only sends API keys to the host they belong to.
- API keys are stored outside the project database and never appear in exports.

## Reporting a vulnerability

Please open a private security advisory on GitHub (Security → Report a vulnerability) instead of a public issue.
Include steps to reproduce with fictional data only.
