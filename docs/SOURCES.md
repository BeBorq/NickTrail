# Sources and access rules

NickTrail reads public data only, through documented APIs where they exist. Availability and limits
change over time; a source that cannot be read is reported as *unsupported* or *blocked*, never as
"no account".

## Public APIs used without a key

| Service | Endpoint and documentation | Notes |
| --- | --- | --- |
| GitHub | [Users](https://docs.github.com/en/rest/users/users), [Search users](https://docs.github.com/en/rest/search/search#search-users) | Public profile and stable numeric ID. Unauthenticated search allows about 10 requests per minute. No private email API. |
| GitLab | [Users API](https://docs.gitlab.com/api/users/) | `username=` is exact, `search=` is fuzzy. GitLab.com only. |
| Bluesky | [public.api.bsky.app](https://docs.bsky.app/) `getProfile`, `searchActors` | One page, up to 10 results. |
| DEV / Forem | [API v0](https://developers.forem.com/api/v0) `/api/users/by_username` | Numeric ID used once known. |
| Roblox | [Users](https://create.roblox.com/docs/cloud/reference/domains/users) | Public resolver without cookies. |
| Codeberg and Gitea instances | `/api/v1/users/{name}` | Strict profile validation. |
| Stack Exchange | [API 2.3](https://api.stackexchange.com/docs) | User search on chosen sites. |
| Lichess, Chess.com | public player APIs | Exact username only. |
| Keybase, Hacker News | lookup and official Firebase API | Identity proofs are recorded as evidence. |
| Discourse forums (Python, Rust, Julia, KDE, GNOME, Godot, Mozilla, Blender, …) | public `/u/{name}.json` | Anonymous public profiles only. |
| Hugging Face, crates.io, RubyGems, Modrinth, Codeforces, Codewars, Speedrun.com, Launchpad, Lemmy | documented public user endpoints | Exact username, public fields only. |
| Internet Archive | [CDX API](https://archive.org/developers/wayback-cdx-server.html) | Only the nickname is sent; results are unverified archived addresses. |

Around 100 further sites are checked with strict profile-address templates that require a positive
sign of a real profile (an HTTP 200 alone is not enough). In **DEEP** mode an optional catalog of 883
routes normalized from Sherlock and Maigret (MIT) is added; those results are treated as untested leads
until a profile is actually read.

## Optional sources with your own key

| Service | Used for | Variable |
| --- | --- | --- |
| Brave Search API | web index and the 180-domain catalog | `NICKTRAIL_BRAVE_KEY` |
| Mojeek, Google Programmable Search, SearXNG | additional web indexes | see the **API keys** panel |
| Have I Been Pwned | breach names for your own email, with consent | `NICKTRAIL_HIBP_KEY` |
| Steam Web API | public profile by vanity URL | see the **API keys** panel |
| Twitch, Xbox (OpenXBL) | public channel or gamertag profile | see the **API keys** panel |
| Mastodon | account lookup on your own instance | see the **API keys** panel |
| X API | bio and website field of a chosen profile | see the **API keys** panel |

Keys are only sent to the host they belong to and are never stored in the project database or exports.

## Rules every source follows

- Public, logged-out data only. No cookies, no sign-in, no private endpoints.
- `robots.txt`, `Retry-After` and documented rate limits are respected.
- A refusal (401/403/429, CAPTCHA, challenge page) becomes a manual check. No retries with other
  headers, proxies or mirrors.
- Search-engine and index results are leads, never evidence of identity.
- Similar usernames never create an identity link.
