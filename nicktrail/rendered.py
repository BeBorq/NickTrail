"""Optional public JS rendering, fresh context, all HTTP through the pinned client."""

import os
import time
from .identity import normalize
from .network import Limit


def render(url, client, factory=None):
    url = normalize(url)
    if getattr(client, 'maximum', None) is not None and client.count >= client.maximum:
        return {'state': 'partial', 'detail': 'Brak budżetu na renderowanie; nie uruchomiono przeglądarki.'}
    if factory is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {
                'state': 'unsupported',
                'detail': 'Zainstaluj opcjonalny pakiet playwright i przeglądarkę Chromium lub ustaw NICKTRAIL_BROWSER_EXECUTABLE.',
            }
        factory = sync_playwright
    failures = []
    deadline = min(client.deadline, time.monotonic() + 25)

    def handle(route):
        request = route.request
        if request.method != 'GET' or request.resource_type not in (
            'document',
            'script',
            'stylesheet',
            'xhr',
            'fetch',
        ):
            route.abort()
            return
        try:
            # The page itself is a profile read and keeps the robots.txt check; its resources are not.
            fetch = (
                getattr(client, 'profile_get', client.get)
                if request.resource_type == 'document'
                else client.get
            )
            response = fetch(request.url)
            if response['state'] != 'found':
                failures.append(response['state'])
                route.abort()
                return
            if response.get('url', request.url) != request.url:
                # Navigation is not silently transplanted to an unrelated origin.
                failures.append('redirect')
                route.abort()
                return
            route.fulfill(
                status=200, content_type=response.get('content_type', 'text/html'), body=response['text']
            )
        except (OSError, ValueError, Limit):
            failures.append('blocked')
            route.abort()

    try:
        with factory() as runtime:
            executable = os.environ.get('NICKTRAIL_BROWSER_EXECUTABLE')
            config = {
                'headless': True,
                'timeout': max(1, int((deadline - time.monotonic()) * 1000)),
                'proxy': {'server': 'http://127.0.0.1:9', 'bypass': ''},
                'args': ['--force-webrtc-ip-handling-policy=disable_non_proxied_udp'],
            }
            if executable:
                config['executable_path'] = executable
            browser = runtime.chromium.launch(**config)
            try:
                context = browser.new_context(service_workers='block', accept_downloads=False)
                context.route('**/*', handle)
                context.route_web_socket('**/*', lambda socket: socket.close())
                context.add_init_script(
                    "Object.defineProperty(window,'RTCPeerConnection',{value:undefined});"
                )
                page = context.new_page()
                page.goto(
                    url,
                    wait_until='domcontentloaded',
                    timeout=max(1, int((deadline - time.monotonic()) * 1000)),
                )
                page.wait_for_load_state(
                    'networkidle', timeout=max(1, int((deadline - time.monotonic()) * 1000))
                )
                html = page.content()
                final = normalize(page.url)
                if final != url:
                    return {
                        'state': 'blocked',
                        'detail': 'Przeglądarka zmieniła adres. Dodaj nowy publiczny adres jawnie.',
                    }
                if failures:
                    return {
                        'state': 'partial',
                        'detail': 'Nie udało się pobrać wszystkich zasobów renderowania; poprzednie dowody zachowano.',
                    }
                if len(html.encode()) > 1048576:
                    return {'state': 'error', 'detail': 'Wyrenderowana strona przekracza limit 1 MiB'}
                return {'state': 'found', 'text': html, 'url': url, 'content_type': 'text/html'}
            finally:
                browser.close()
    except Exception as error:
        return {
            'state': 'error',
            'detail': 'Renderowanie nie powiodło się ('
            + type(error).__name__
            + '). Sprawdź instalację przeglądarki i budżet. Nie pominięto blokady dostępu.',
        }


def read(node, client):
    from .publicprofile import read as read_public

    result = render(node['url'], client)
    if result['state'] != 'found':
        return result
    from .publicprofile import ProfileHTML

    page = ProfileHTML()
    page.feed(result['text'])
    visible = ''.join(page.parts).lstrip()
    if visible.startswith(('{', '[')):
        return {
            'state': 'partial',
            'detail': 'Przeglądarka wyświetliła JSON zamiast profilu. Użyj zwykłego odczytu adaptera; nie importowano adresów technicznych.',
        }

    class Document:
        def get(self, url):
            return result

    parsed = read_public(node, Document())
    for edge in parsed.get('evidence', []):
        edge['method'] = 'rendered_public_page'
    return parsed
