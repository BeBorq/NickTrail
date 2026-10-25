"""Explicit self-audit criteria; no inferred identity or age."""

import datetime
import re
import unicodedata
from urllib.parse import quote
from .identity import normalize

SITES = [
    'github.com',
    'gitlab.com',
    'bsky.app',
    'dev.to',
    'roblox.com',
    'steamcommunity.com',
    'youtube.com',
    'twitch.tv',
    'instagram.com',
    'facebook.com',
    'x.com',
    'reddit.com',
    'linkedin.com',
    'pinterest.com',
    'tiktok.com',
    'soundcloud.com',
    'bandcamp.com',
    'spotify.com',
    'last.fm',
    'flickr.com',
    'vimeo.com',
    'behance.net',
    'dribbble.com',
    'artstation.com',
    'medium.com',
    'substack.com',
    'tumblr.com',
    'wordpress.com',
    'about.me',
    'linktr.ee',
    'carrd.co',
    'ko-fi.com',
    'buymeacoffee.com',
    'patreon.com',
    'itch.io',
    'codeberg.org',
    'sourceforge.net',
    'stackoverflow.com',
    'stackexchange.com',
    'kaggle.com',
    'huggingface.co',
    'keybase.io',
    'goodreads.com',
    'strava.com',
    'chess.com',
    'lichess.org',
    'replit.com',
    'npmjs.com',
    'pypi.org',
    'researchgate.net',
    'orcid.org',
    'hackerone.com',
    'bugcrowd.com',
    'intigriti.com',
    'yeswehack.com',
    'openbugbounty.org',
    'h1.community',
    'hackthebox.com',
    'tryhackme.com',
    'root-me.org',
    'picoctf.org',
    'leetcode.com',
    'hackerrank.com',
    'codewars.com',
    'exercism.org',
    'topcoder.com',
    'codeforces.com',
    'atcoder.jp',
    'codingame.com',
    'freecodecamp.org',
    'codecademy.com',
    'codesandbox.io',
    'stackblitz.com',
    'glitch.com',
    'observablehq.com',
    'codepen.io',
    'jsfiddle.net',
    'glitch.me',
    'bitbucket.org',
    'gitea.com',
    'sr.ht',
    'launchpad.net',
    'rubygems.org',
    'crates.io',
    'packagist.org',
    'nuget.org',
    'docker.com',
    'hub.docker.com',
    'libraries.io',
    'opensource.org',
    'openhub.net',
    'discourse.org',
    'discuss.python.org',
    'lobste.rs',
    'news.ycombinator.com',
    'producthunt.com',
    'indiehackers.com',
    'wellfound.com',
    'crunchbase.com',
    'f6s.com',
    'wikidata.org',
    'wikipedia.org',
    'wikimedia.org',
    'wikifur.com',
    'fandom.com',
    'archive.org',
    'openlibrary.org',
    'librarything.com',
    'bookwyrm.social',
    'storygraph.com',
    'thestorygraph.com',
    'letterboxd.com',
    'trakt.tv',
    'imdb.com',
    'themoviedb.org',
    'myanimelist.net',
    'anilist.co',
    'anime-planet.com',
    'kitsu.app',
    'boardgamegeek.com',
    'rpggeek.com',
    'speedrun.com',
    'osu.ppy.sh',
    'faceit.com',
    'esea.net',
    'tracker.gg',
    'fortnitetracker.com',
    'minecraft.net',
    'namemc.com',
    'planetminecraft.com',
    'modrinth.com',
    'curseforge.com',
    'nexusmods.com',
    'moddb.com',
    'gamebanana.com',
    'gamejolt.com',
    'newgrounds.com',
    'kongregate.com',
    'armorgames.com',
    'scratch.mit.edu',
    'instructables.com',
    'hackaday.io',
    'makerworld.com',
    'printables.com',
    'thingiverse.com',
    'cults3d.com',
    'thangs.com',
    'sketchfab.com',
    'blendermarket.com',
    'blenderartists.org',
    'polycount.com',
    'cgtrader.com',
    'turbosquid.com',
    '500px.com',
    'unsplash.com',
    'pexels.com',
    'pixabay.com',
    'vsco.co',
    'viewbug.com',
    'gurushots.com',
    'redbubble.com',
    'society6.com',
    'etsy.com',
    'gumroad.com',
    'creativefabrica.com',
    'designspiration.com',
    'are.na',
    'cargo.site',
    'adobe.com',
    'displate.com',
    'furaffinity.net',
    'toyhou.se',
    'cara.app',
    'pixiv.net',
    'skeb.jp',
    'opensea.io',
    'foundation.app',
    'objkt.com',
    'superrare.com',
    'audius.co',
]


def criteria(value=None):
    value = {} if value is None else value
    keys = {'first_name', 'last_name', 'location', 'keywords', 'birth_date', 'known_urls'}
    if not isinstance(value, dict) or set(value) - keys:
        raise ValueError('Nieprawidłowe kryteria')
    out = {}
    for key in keys - {'known_urls'}:
        text = value.get(key, '')
        if not isinstance(text, str) or len(text) > 160 or any(ord(c) < 32 for c in text):
            raise ValueError('Nieprawidłowe kryterium: ' + key)
        out[key] = text.strip()
    if out['birth_date']:
        if not re.fullmatch(r'\d{4}-\d{2}-\d{2}', out['birth_date']):
            raise ValueError('Data: RRRR-MM-DD')
        date = datetime.date.fromisoformat(out['birth_date'])
        if date > datetime.date.today():
            raise ValueError('Data urodzenia jest w przyszłości')
    urls = value.get('known_urls', [])
    if (
        not isinstance(urls, list)
        or len(urls) > 10
        or any(not isinstance(u, str) or len(u) > 2000 for u in urls)
    ):
        raise ValueError('Najwyżej 10 adresów')
    out['known_urls'] = list(dict.fromkeys(normalize(u) for u in urls))
    return out


def terms(value):
    c = criteria(value)
    name = ' '.join(filter(None, [c['first_name'], c['last_name']]))
    return list(
        dict.fromkeys(
            t
            for t in [
                name,
                c['keywords'],
                (' '.join([name, c['location']]) if name and c['location'] else ''),
            ]
            if t
        )
    )


def plan(nickname, value):
    c = criteria(value)
    if not isinstance(nickname, str) or len(nickname) > 160 or any(ord(ch) < 32 for ch in nickname):
        raise ValueError('Nieprawidłowy nick do planu')
    if not nickname.strip() and not any(c[k] for k in ('first_name', 'last_name', 'location', 'keywords')):
        raise ValueError('Podaj nick lub słowa do wyszukania')
    base = (
        ' '.join(
            '"' + s.replace('"', ' ') + '"'
            for s in [c['first_name'], c['last_name'], c['location'], c['keywords']]
            if s
        )
        or '"' + nickname.replace('"', ' ') + '"'
    )
    return [
        {
            'site': site,
            'query': 'site:' + site + ' ' + base,
            'url': 'https://www.google.com/search?q=' + quote('site:' + site + ' ' + base, safe=''),
            'mode': 'manual',
        }
        for site in SITES
    ]


def compare(data, value):
    c = criteria(value)
    # A person's name must come from fields describing the account owner. A name
    # in a bio or description ("fan of Jan Kowalski") names someone else as often
    # as the owner, so it never counts as the owner's name; topical keywords may.
    owner = ' '.join(str(data.get(k) or '') for k in ('alias', 'display', 'title')).casefold()
    text = ' '.join(
        str(data.get(k) or '') for k in ('alias', 'display', 'bio', 'description', 'title')
    ).casefold()

    def contains(needle, haystack):
        needle = unicodedata.normalize('NFKC', needle).casefold()
        haystack = unicodedata.normalize('NFKC', haystack).casefold()
        return bool(needle and re.search(r'(?<!\w)' + re.escape(needle) + r'(?!\w)', haystack))

    matched = [key for key in ('first_name', 'last_name') if contains(c[key], owner)]
    if contains(c['keywords'], text):
        matched.append('keywords')
    if contains(c['location'], str(data.get('declared_location') or '')):
        matched.append('location')
    # Only an explicitly provided structured public field; never parse ages or account creation dates.
    if c['birth_date'] and data.get('declared_birth_date') == c['birth_date']:
        matched.append('birth_date')
    return matched
