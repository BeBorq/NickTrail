"""Bounded HTTP with DNS pinning. No proxy environment, cookies, credentials or redirect bypass."""

import http.client
import ipaddress
import re
import threading
import socket
import ssl
import time
import json
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import urlsplit, urljoin, parse_qs
from .identity import normalize

PROCESS_COOLDOWNS = {}
MINIMUM_INTERVALS = {'codeforces.com': 2}
# Process-wide reading settings, loaded per database by nicktrail.settings.apply().
SETTINGS = {}


def setting(key):
    if key in SETTINGS:
        return SETTINGS[key]
    from .settings import DEFAULTS

    return DEFAULTS[key]


DEFINITIVE_ROBOTS = (
    'automatyczny odczyt zabroniony',
    'przekierowana do innej domeny',
    'wymagane wolniejsze tempo',
    'polityka robots niedostępna (HTTP',
)


def robots_decision(fetch, url, delay):
    """Robots.txt decision for one URL: (denial detail or None, required pause in seconds).

    Default behaviour is unchanged from 0.19 except that redirects of robots.txt
    are followed (RFC 9309 2.3.1.2).  Optional settings: a 4xx robots.txt is
    "unavailable" (RFC 9309 2.3.1.3) and Crawl-delay/Request-rate is honoured by
    slowing down for that host instead of skipping it.
    """
    from urllib.robotparser import RobotFileParser

    p = urlsplit(url)
    origin = p.scheme + '://' + p.netloc
    response = fetch(origin + '/robots.txt')
    state = response.get('state')
    if state == 'found':
        if (
            response.get('url')
            and urlsplit(response['url']).netloc != p.netloc
            and not setting('robots_follow_redirects')
        ):
            return 'ROBOTS_RESTRICTED: polityka przekierowana do innej domeny', 0
        text = response.get('text', '')
    elif state == 'not_found':
        text = ''
    else:
        match = re.search(r'HTTP (\d{3})', str(response.get('detail', '')))
        status = int(match.group(1)) if match else None
        if status and 400 <= status < 500 and status != 429 and setting('robots_4xx_allow'):
            text = ''
        elif status and status not in (429, 503):
            return 'ROBOTS_RESTRICTED: polityka robots niedostępna (HTTP ' + str(status) + ')', 0
        else:
            return 'ROBOTS_RESTRICTED: polityka robots niedostępna', 0
    policy = RobotFileParser()
    policy.parse(text.splitlines())
    if not policy.can_fetch('NickTrail', url):
        return 'ROBOTS_RESTRICTED: automatyczny odczyt zabroniony', 0
    rate = policy.request_rate('NickTrail')
    need = max(policy.crawl_delay('NickTrail') or 0, (rate.seconds / max(1, rate.requests)) if rate else 0)
    if need > delay:
        if not setting('crawl_delay_wait'):
            return 'ROBOTS_RESTRICTED: wymagane wolniejsze tempo; kontrola ręczna', 0
        # The declared pause is kept in full, never shortened; only the policy above the threshold differs.
        if need <= setting('crawl_delay_max') or setting('crawl_delay_long') == 'wait':
            return None, float(need)
        return (
            'ROBOTS_RESTRICTED: Crawl-delay '
            + format(need, 'g')
            + ' s powyżej progu '
            + str(setting('crawl_delay_max'))
            + ' s; źródło pominięte zgodnie z ustawieniem',
            0,
        )
    return None, 0


def profile_api_origin(url):
    """Structured profile endpoints must retain their selected HTTPS authority."""
    p = urlsplit(url)
    structured = (
        p.hostname
        in (
            'api.github.com',
            'api.launchpad.net',
            'api.steampowered.com',
            'public.api.bsky.app',
            'hacker-news.firebaseio.com',
        )
        or p.path.startswith(('/api/', '/wp-json/wp/v2/users', '/_/api/'))
        or p.path.startswith('/u/')
        and p.path.endswith('.json')
    )
    return (p.scheme, p.hostname, p.port or 443) if structured and p.scheme == 'https' else None


class Limit(Exception):
    pass


# Extra request headers an adapter may send, and where.  Anything else is refused,
# so a key can only ever travel to the service it belongs to.
ALLOWED_HEADERS = (
    ({'Authorization'}, None),  # Bearer tokens (X, Mastodon); host checked by redirect guard
    ({'hibp-api-key'}, 'haveibeenpwned.com'),
    ({'X-Subscription-Token'}, 'api.search.brave.com'),
    ({'Client-Id', 'Authorization'}, 'api.twitch.tv'),
    ({'X-Authorization', 'Accept'}, 'xbl.io'),
)


def headers_allowed(headers, scheme, host):
    names = set(headers)
    return any(
        names == allowed and (where is None or (scheme == 'https' and host == where))
        for allowed, where in ALLOWED_HEADERS
    )


def public_addresses(host, resolver=socket.getaddrinfo):
    addresses = list(dict.fromkeys(x[4][0] for x in resolver(host, 443, type=socket.SOCK_STREAM)))

    def safe(value):
        ip = ipaddress.ip_address(value)
        if not ip.is_global or ip.is_multicast or ip.is_unspecified or ip.is_reserved:
            return False
        if isinstance(ip, ipaddress.IPv6Address):
            if ip.teredo or ip.sixtofour or ip.ipv4_mapped:
                return False
            if ip in ipaddress.ip_network('64:ff9b::/96') or ip in ipaddress.ip_network('64:ff9b:1::/48'):
                return False
        return True

    if not addresses or any(not safe(x) for x in addresses):
        raise ValueError("Zablokowano adres niepubliczny")
    return addresses


class PinnedTLS(http.client.HTTPSConnection):
    def __init__(self, host, ip, timeout):
        super().__init__(host, timeout=timeout, context=ssl.create_default_context())
        self.ip = ip

    def connect(self):
        raw = socket.create_connection((self.ip, self.port), self.timeout)
        try:
            self.sock = self._context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


class Client:
    def __init__(
        self,
        queries=40,
        seconds=120,
        per_domain=15,
        delay=1,
        timeout=8,
        browser_resources=False,
        image_resources=False,
        xml_resources=False,
        exposure_catalog=False,
    ):
        self.exposure_catalog = exposure_catalog
        self.metrics_v2 = True
        self.xml_resources = xml_resources
        self.image_resources = image_resources
        self.browser_resources = browser_resources
        self.maximum, self.deadline, self.seconds = queries, time.monotonic() + seconds, seconds
        self.per_domain, self.delay, self.timeout = per_domain, delay, timeout
        self.count, self.domains, self.last, self.cache = 0, {}, {}, {}
        self.cooldowns = PROCESS_COOLDOWNS
        self.events = []
        self.events_truncated = 0
        self.cache_expiry = {}
        # Several different hosts may be read at once; one host is never read concurrently.
        self._lock = threading.RLock()
        self._host_locks = {}
        self.host_intervals = {}
        self.local = threading.local()
        self.robots_memory = None
        self.persist_queue = []

    def host_lock(self, host):
        with self._lock:
            return self._host_locks.setdefault(host, threading.RLock())

    def remember(self, key, result, ttl):
        if len(self.cache) >= 512 and key not in self.cache:
            oldest = next(iter(self.cache))
            self.cache.pop(oldest)
            self.cache_expiry.pop(oldest, None)
        self.cache[key] = result
        self.cache_expiry[key] = time.monotonic() + ttl
        return result

    def event(self, kind, **fields):
        # Bounded protocol accounting, never URLs, query text, headers or bodies.
        task = getattr(self.local, 'task', None) if hasattr(self, 'local') else None
        if task is not None:
            fields['task'] = task
        with self._lock if hasattr(self, '_lock') else _NoLock():
            if len(self.events) < 4096:
                self.events.append({'kind': kind, **fields})
            else:
                self.events_truncated += 1

    def defer_host(self, host, seconds):
        if type(seconds) not in (int, float) or seconds < 0:
            return
        self.cooldowns[host] = max(self.cooldowns.get(host, 0), time.monotonic() + seconds)

    def get(self, url, headers=None):
        return self.request(url, extra_headers=headers)

    def profile_get(self, url):
        return self.request(url, profile=True)

    def profile_policy(self, url):
        host = urlsplit(url).netloc.lower()
        memory = self.robots_memory if setting('robots_memory') else None
        if memory:
            remembered = memory('get', host)
            if remembered:
                self.event('policy_block', host=urlsplit(url).hostname)
                return remembered + ' (zapamiętana odmowa)'
        denied, interval = robots_decision(self.get, url, self.delay)
        if interval:
            with self._lock:
                self.host_intervals[urlsplit(url).hostname] = max(
                    self.host_intervals.get(urlsplit(url).hostname, 0), interval
                )
        if denied and memory and any(d in denied for d in DEFINITIVE_ROBOTS):
            memory('set', host, denied)
        return denied

    def post_json(self, url, payload):
        # Only a documented read-only Roblox username resolver is allowed to POST.
        if url != 'https://users.roblox.com/v1/usernames/users':
            raise ValueError('Niedozwolony endpoint POST')
        return self.request(url, json.dumps(payload).encode('utf-8'))

    def request(self, url, body=None, extra_headers=None, profile=False):
        url = normalize(url)
        api_origin = profile_api_origin(url)
        if not hasattr(self, '_lock'):
            self._lock = threading.RLock()
            self._host_locks = {}
            self.host_intervals = {}
            self.local = threading.local()
        if profile:
            denied = self.profile_policy(url)
            if denied:
                self.event('policy_block', host=urlsplit(url).hostname)
                return {"state": "blocked", "detail": denied}
        cache_key = (url, body, tuple(sorted((extra_headers or {}).items())), profile)
        if cache_key in self.cache and self.cache_expiry.get(cache_key, float('inf')) > time.monotonic():
            self.event('cache_hit', host=urlsplit(url).hostname)
            return self.cache[cache_key]
        for redirect in range(4):
            if profile and redirect:
                denied = self.profile_policy(url)
                if denied:
                    self.event('policy_block', host=urlsplit(url).hostname)
                    return {"state": "blocked", "detail": denied}
            for attempt in range(2):
                p = urlsplit(url)
                # One request at a time per host, pause included; other hosts may proceed in parallel.
                with self.host_lock(p.hostname):
                    if self.count >= self.maximum or time.monotonic() >= self.deadline:
                        self.event('budget_block', host=p.hostname)
                        raise Limit("Limit zapytań lub czasu")
                    if self.domains.get(p.hostname, 0) >= self.per_domain:
                        self.event('budget_block', host=p.hostname)
                        return {"state": "blocked", "detail": "Limit domeny"}
                    if self.cooldowns.get(p.hostname, 0) > time.monotonic():
                        self.event('rate_cooldown', host=p.hostname)
                        return {"state": "blocked", "detail": "Przerwa zalecona przez API"}
                    try:
                        addresses = public_addresses(p.hostname)
                    except ValueError:
                        self.event('policy_block', host=p.hostname)
                        raise
                    except OSError:
                        self.event('network_error', host=p.hostname)
                        raise
                    pause = max(
                        0,
                        self.last.get(p.hostname, 0)
                        + max(
                            self.delay,
                            MINIMUM_INTERVALS.get(p.hostname, 0),
                            self.host_intervals.get(p.hostname, 0),
                        )
                        - time.monotonic(),
                    )
                    if time.monotonic() + pause >= self.deadline:
                        interval = self.host_intervals.get(p.hostname, 0)
                        if interval and pause > 0:
                            # A service-requested pause must not end the round for every other service.
                            if interval > self.seconds:
                                self.event('policy_block', host=p.hostname)
                                return {
                                    'state': 'blocked',
                                    'detail': 'ROBOTS_RESTRICTED: Crawl-delay '
                                    + format(interval, 'g')
                                    + ' s dłuższy niż cała runda ('
                                    + str(self.seconds)
                                    + ' s); źródło pominięte',
                                }
                            self.defer_host(p.hostname, pause)
                            self.event('rate_cooldown', host=p.hostname)
                            return {
                                'state': 'blocked',
                                'detail': 'Przerwa zalecona przez API: Crawl-delay '
                                + format(interval, 'g')
                                + ' s; serwis wróci w kolejnej rundzie',
                            }
                        raise Limit("Limit czasu")
                    time.sleep(pause)
                    with self._lock:
                        if self.count >= self.maximum:
                            raise Limit("Limit zapytań lub czasu")
                        self.count += 1
                        self.domains[p.hostname] = self.domains.get(p.hostname, 0) + 1
                    self.local.count = getattr(self.local, 'count', 0) + 1
                    self.last[p.hostname] = time.monotonic()
                    remaining = max(0.05, min(self.timeout, self.deadline - time.monotonic()))
                    conn = (
                        PinnedTLS(p.hostname, addresses[0], remaining)
                        if p.scheme == "https"
                        else http.client.HTTPConnection(addresses[0], timeout=remaining)
                    )
                    try:
                        from . import __version__

                        headers = {
                            "Host": p.hostname,
                            "User-Agent": f"NickTrail/{__version__} (local public-footprint audit)",
                            "Accept": "application/json,text/html,text/plain",
                            "Accept-Encoding": "identity",
                        }
                        if extra_headers:
                            if not headers_allowed(extra_headers, p.scheme, p.hostname):
                                raise ValueError('Niedozwolone nagłówki adaptera')
                            headers.update(extra_headers)
                        if body is not None:
                            headers['Content-Type'] = 'application/json'
                        conn.request(
                            "POST" if body is not None else "GET",
                            p.path + ("?" + p.query if p.query else ""),
                            body=body,
                            headers=headers,
                        )
                        purpose = 'policy' if p.path == '/robots.txt' else 'content'
                        self.event('request_sent', host=p.hostname, purpose=purpose)
                        response = conn.getresponse()
                        status = response.status
                        self.event(
                            'response',
                            host=p.hostname,
                            status=status,
                            redirect=status in (301, 302, 303, 307, 308),
                            purpose=purpose,
                        )
                        if status in (301, 302, 303, 307, 308):
                            if body is not None:
                                return {'state': 'blocked', 'detail': 'Przekierowanie POST zablokowane'}
                            url = normalize(urljoin(url, response.getheader("Location", "")))
                            target = urlsplit(url)
                            if (
                                api_origin
                                and (
                                    target.scheme,
                                    target.hostname,
                                    target.port or (443 if target.scheme == 'https' else 80),
                                )
                                != api_origin
                            ):
                                self.event('policy_block', host=p.hostname)
                                return {
                                    'state': 'blocked',
                                    'detail': 'REDIRECT_POLICY_BLOCKED: structured API left selected HTTPS origin',
                                }
                            if (extra_headers or set(parse_qs(p.query)) & {'key', 'api_key'}) and (
                                urlsplit(url).scheme,
                                urlsplit(url).hostname,
                            ) != (p.scheme, p.hostname):
                                return {
                                    'state': 'blocked',
                                    'detail': 'Przekierowanie z tokenem do innego serwera zablokowane',
                                }
                            # Next connection resolves and validates this new target, then pins the IP.
                            break
                        if status == 429:
                            raw = response.getheader('Retry-After', '60')
                            try:
                                wait = float(raw)
                            except (ValueError, TypeError):
                                try:
                                    wait = (
                                        parsedate_to_datetime(raw) - datetime.now(timezone.utc)
                                    ).total_seconds()
                                except (ValueError, TypeError, OverflowError):
                                    wait = 60
                            import math

                            wait = max(60, wait) if math.isfinite(wait) else 60
                            self.defer_host(p.hostname, wait)
                            self.event('rate_limit', host=p.hostname, retry_after_seconds=wait)
                            return {
                                'state': 'blocked',
                                'detail': 'HTTP 429; RATE_LIMITED; backoff ' + str(round(wait)) + 's',
                            }
                        if status in (429, 503) and attempt == 0:
                            raw = response.getheader("Retry-After", "1")
                            try:
                                wait = float(raw)
                            except ValueError:
                                try:
                                    wait = (
                                        parsedate_to_datetime(raw) - datetime.now(timezone.utc)
                                    ).total_seconds()
                                except (ValueError, TypeError):
                                    wait = 1
                            if wait > 10 or time.monotonic() + max(0, wait) >= self.deadline:
                                self.defer_host(p.hostname, max(0, wait))
                                return {"state": "blocked", "detail": "Retry-After poza budżetem"}
                            time.sleep(max(0, wait))
                            continue
                        state = (
                            "found"
                            if status == 200
                            else (
                                "not_found"
                                if status in (404, 410)
                                else "blocked" if status in (401, 403, 429, 503) else "error"
                            )
                        )
                        if state != "found":
                            # Only two fixed public endpoints have documented JSON error semantics.
                            # Do not store raw error bodies, interpret generic 400s, or read auth errors.
                            if (
                                status == 400
                                and p.scheme == 'https'
                                and (p.hostname, p.path)
                                in (
                                    ('public.api.bsky.app', '/xrpc/app.bsky.actor.getProfile'),
                                    ('codeforces.com', '/api/user.info'),
                                )
                                and response.getheader('Content-Type', '').split(';')[0] == 'application/json'
                            ):
                                payload = bytearray()
                                while len(payload) <= 16384:
                                    if time.monotonic() >= self.deadline:
                                        raise Limit('Limit czasu')
                                    chunk = response.read1(16385 - len(payload))
                                    if not chunk:
                                        break
                                    payload.extend(chunk)
                                    self.event(
                                        'body_bytes', host=p.hostname, bytes=len(chunk), purpose=purpose
                                    )
                                from .apierrors import public_error

                                typed = public_error(url, status, 'application/json', payload)
                                if typed:
                                    if 'RATE_LIMITED' in typed['detail']:
                                        self.defer_host(p.hostname, 60)
                                        self.event('rate_limit', host=p.hostname, retry_after_seconds=60)
                                    return (
                                        self.remember(cache_key, typed, 60)
                                        if typed['state'] == 'not_found'
                                        else typed
                                    )
                            result = {"state": state, "detail": f"HTTP {status}"}
                            return self.remember(cache_key, result, 60) if state == 'not_found' else result
                        content_type = response.getheader("Content-Type", "").split(";")[0]
                        if (
                            content_type
                            not in (
                                "application/json",
                                "application/vnd.api+json",
                                "text/html",
                                "text/plain",
                                "application/xhtml+xml",
                            )
                            and not (self.xml_resources and content_type in ('application/xml', 'text/xml'))
                            and not (
                                self.browser_resources
                                and content_type in ('application/javascript', 'text/javascript', 'text/css')
                            )
                            and not (
                                self.image_resources
                                and content_type in ('image/png', 'image/jpeg', 'image/webp')
                            )
                        ):
                            return {"state": "unsupported", "detail": "Niedozwolony typ treści"}
                        data = bytearray()
                        maximum_bytes = (
                            262144
                            if self.image_resources and content_type.startswith('image/')
                            else (
                                4194304
                                if self.exposure_catalog
                                and p.hostname == 'haveibeenpwned.com'
                                and p.path == '/api/v3/breaches'
                                and content_type == 'application/json'
                                else 1048576
                            )
                        )
                        while True:
                            if time.monotonic() >= self.deadline:
                                raise Limit("Limit czasu")
                            chunk = response.read1(min(65536, maximum_bytes + 1 - len(data)))
                            if not chunk:
                                break
                            data.extend(chunk)
                            self.event('body_bytes', host=p.hostname, bytes=len(chunk), purpose=purpose)
                            if len(data) > maximum_bytes:
                                return {"state": "error", "detail": "Odpowiedź za duża"}
                        if self.image_resources and content_type.startswith('image/'):
                            result = {
                                'state': 'found',
                                'bytes': bytes(data),
                                'content_type': content_type,
                                'url': url,
                            }
                            return self.remember(cache_key, result, 300)
                        text = data.decode("utf-8", errors="replace")
                        if content_type in ('text/html', 'application/xhtml+xml') and any(
                            x in text.lower()
                            for x in (
                                'cf-chl-',
                                'verify you are human',
                                'g-recaptcha',
                                'h-captcha',
                                'challenges.cloudflare.com',
                            )
                        ):
                            return {"state": "blocked", "detail": "Wyzwanie dostępu"}
                        result = {"state": state, "text": text, "url": url, "content_type": content_type}
                        return self.remember(cache_key, result, 300)
                    except (OSError, http.client.HTTPException) as error:
                        if isinstance(error, TimeoutError):
                            self.event('timeout', host=p.hostname)
                        self.event('network_error', host=p.hostname)
                        if attempt == 1:
                            raise
                    finally:
                        conn.close()
            else:
                return {"state": "error", "detail": "Wyczerpane próby"}
        return {"state": "blocked", "detail": "Limit przekierowań"}


class _NoLock:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False
