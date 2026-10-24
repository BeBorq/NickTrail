# FAQ

**Is NickTrail a tool for finding information about other people?**
No. It is built for auditing your own footprint (or one you are explicitly authorised to audit).
It does not use leaked data, does not bypass sign-ins or blocks, and never decides who owns an account.
See [SECURITY.md](../SECURITY.md).

**Does anything leave my computer?**
Only the requests a search needs: your username (and aliases you declared) goes to the public sites
and APIs being checked. Email addresses are never sent to search services. The optional Have I Been
Pwned check sends one email address you type, only after you tick the consent box. The mailbox and
password imports never use the network.

**Why did it not find an account I know exists?**
Common reasons: the site blocks automated reads or shows profiles only to logged-in visitors; the
profile address contains a number or tag that cannot be built from the nickname; the site was not
in the chosen scope; the search budget ran out. Paste the address into **Why was this profile not
found?** for an explanation, try **DEEP**, or add the address yourself under **My accounts**.

**Why is an account marked "blocked" or "manual check"?**
The site refused the request, rate-limited it, asked for a CAPTCHA or a sign-in, or `robots.txt`
does not allow it. NickTrail does not try to get around that. Open the address yourself.

**A result has my username but it is not me. What now?**
Mark it **Not mine**. Matching usernames are common; NickTrail treats them as leads only and will not
put such an account in a group with yours without independent evidence.

**What is the difference between "found", "linked" and "mine"?**
*Found* means a profile exists at that address. *Linked* means public evidence connects it to
another account. *Mine* is your decision and only you can set it.

**How long does a search take?**
QUICK about a minute, STANDARD a few minutes, DEEP 10–30 minutes depending on how many sites respond.
You can stop and resume at any time.

**Do I need API keys?**
No. Keys only add optional sources (Brave Search, Have I Been Pwned, Steam, Twitch, Xbox, Mastodon,
X and others). They are stored in your user config folder, never in the database or exports.

**Can I use the results with ChatGPT, Claude or another AI assistant?**
Yes, through **AI analysis package — export only**. It prepares a redacted package and a prompt for you
to copy. NickTrail itself never sends data to any AI service.

**Where is my data stored and how do I delete it?**
In the SQLite file you passed with `--db`. **Delete project and data** removes one project; deleting the
file removes everything. API keys live in `%APPDATA%\NickTrail\` on Windows or `~/.config/NickTrail/`
elsewhere.

**Does it work on Windows, macOS and Linux?**
Yes. It needs Python 3.11 or newer and a modern browser. Tests run on Linux and Windows.

**Why are adult sites hidden?**
Checks for adult platforms exist only so you can find and remove your own profiles. They are off by
default, hidden in lists unless you show them, and left out of exports and the AI package.
