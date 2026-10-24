# NickTrail

**Find your own forgotten accounts and see what the internet shows about you.**

NickTrail is a local, open-source tool for auditing **your own** public digital footprint. Give it your
nicknames, names or profile links; it checks public sources, reads the public profiles it finds and shows the
evidence that connects them, so you can decide which accounts are yours and which ones to delete or lock.

![NickTrail panel with fictional data](docs/images/account-groups.png)

Everything runs on your computer. Your results live in a single SQLite file that never leaves your machine, and
there is no account, telemetry or cloud service. A search only sends the nicknames you enter to the public sites and
APIs being checked; email addresses are never used as search terms, and imported mail or password files are
processed locally.

> **Finding an account, finding a link between accounts and knowing who owns an account are three different
> things.** NickTrail never decides ownership for you: a matching nickname, photo or name is a lead, not proof.
> Scores are heuristics, not probabilities.

## What it does

- **Searches public sources by nickname**: public APIs (GitHub, GitLab, Bluesky, Roblox, Codeberg, Stack
  Exchange, Lichess, Keybase, forums and more), ~100 strict profile-address templates and an optional imported
  catalog (Sherlock/Maigret definitions) in deep mode.
- **Reads your confirmed accounts first** and follows only public links (bios, “website” fields, `rel=me`,
  Linktree-style pages) to build an evidence graph and suggested account groups.
- **Finds forgotten accounts in your own data**: imports a mailbox export (`.mbox` from Google Takeout,
  `.eml`, `.zip`) — headers only — and password-manager CSV exports — only the website and login of each entry are kept; passwords are never stored.
- **Internet Archive search** for profile addresses that contain a number or tag
  (e.g. `example.com/user/123456-nick`).
- **Optional keyed sources** you add yourself: Brave Search, Have I Been Pwned (your own email), Steam, Twitch,
  Xbox (OpenXBL), Mastodon, X.
- **Explainable results**: every connection shows its source URL and snippet; you can mark accounts as mine /
  not mine, reject links and declare that two accounts belong to different people.
- **Exports** (JSON, Markdown, HTML) and a redacted packet you can paste into an AI assistant yourself.
- English (default) and Polish interface.

## What it deliberately does not do

- No bypassing of sign-in, CAPTCHAs, paywalls, `robots.txt` or rate limits. Blocked sites become manual-check items.
- No breached-password databases, no stolen or private data, no session cookies.
- No automatic ownership decisions and no profiling of other people.
- Adult-site checks exist only so you can find and remove your own profiles; they are **off by default**,
  hidden in lists and excluded from exports and the AI packet.

See [SECURITY.md](SECURITY.md) for the responsible-use policy.

## Quick start

Requirements: Python 3.11 or newer. The core has no third-party dependencies.

```bash
git clone https://github.com/BeBorq/NickTrail.git
cd NickTrail
python -m nicktrail --db my-footprint.sqlite3 serve --port 8770
```

Open <http://127.0.0.1:8770/>, create a project and:

1. In **My accounts and known addresses**, paste links to accounts you know are yours (tick “These are my accounts”).
2. Optionally import your mailbox or password export to find services you forgot about.
3. Enter your nickname(s) and press **Find candidates** (start with *Standard*; *Deep* checks far more sites and takes longer).
4. Review candidates, mark what is yours, and use the link map and account groups to see how things connect.

The panel only listens on `127.0.0.1`. Keep the `.sqlite3` file private: it contains your search results.

Optional extras:

```bash
python -m pip install .                 # installs the `nicktrail` package
python -m pip install ".[browser]"      # optional JavaScript rendering (Playwright + Chromium)
```

Command-line help: `python -m nicktrail --help`. CLI messages are English by default; set `NICKTRAIL_LANG=pl` for Polish.

## API keys

All keys are optional. Add them in the panel under **More tools → API keys**; they are stored in your user config folder
(`%APPDATA%\NickTrail\api-keys.json` on Windows, `~/.config/NickTrail/` elsewhere), never in the project
database or exports. Environment variables such as `NICKTRAIL_BRAVE_KEY` take precedence.

## Screenshots

All screenshots use fictional data.

| Forgotten accounts from your mailbox | Link map |
| --- | --- |
| ![Forgotten accounts](docs/images/forgotten-accounts.png) | ![Link map](docs/images/link-map.png) |
| **Search** | **Profiles and evidence** |
| ![Search](docs/images/search.png) | ![Profiles](docs/images/profiles.png) |

## Documentation

- [User guide](docs/USER-GUIDE.md): a full audit step by step
- [How it works](docs/HOW-IT-WORKS.md): architecture, technologies, search pipeline, security model
- [Sources](docs/SOURCES.md): which services are checked and how
- [FAQ](docs/FAQ.md)
- [Contributing](CONTRIBUTING.md) and [Security](SECURITY.md)

## Built with

Python 3.11+ standard library (`http.server`, `sqlite3`, `ssl`, `email`, …), SQLite, and a single-file
HTML/CSS/JavaScript panel with a strict Content-Security-Policy. No frameworks, no CDN, no telemetry.
Optional: Playwright for JavaScript-only pages. Site definitions partly come from
[Sherlock](https://github.com/sherlock-project/sherlock) and [Maigret](https://github.com/soxoj/maigret) (MIT).

## Development

```bash
python -m unittest discover -s tests -q
for f in tests/test_panel_*.js; do node "$f"; done
python tests/web_smoke.py
```

Tests never contact real websites. See [CONTRIBUTING.md](CONTRIBUTING.md) before adding a source.

## Status

0.20 is a release candidate. Detection quality varies by site and changes over time; a missing result
never proves an account does not exist. Bug reports and new sources are welcome — see
[CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE). Bundled third-party data and its licences are listed in [NOTICE](NOTICE).
