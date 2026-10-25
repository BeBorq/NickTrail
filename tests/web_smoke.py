"""Opt-in local HTTP integration test; starts a disposable server and fictional DB."""

import http.client
import json
from pathlib import Path
import re
import socket
import subprocess
import sys
import tempfile
import time
import unittest


class WebTests(unittest.TestCase):
    def test_local_workflow_and_csrf(self):
        with tempfile.TemporaryDirectory(dir=Path.cwd()) as directory:
            with socket.socket() as s:
                s.bind(('127.0.0.1', 0))
                port = s.getsockname()[1]
            process = subprocess.Popen(
                [
                    sys.executable,
                    '-m',
                    'nicktrail',
                    '--db',
                    str(Path(directory) / 'test.sqlite3'),
                    'serve',
                    '--port',
                    str(port),
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE,
            )

            def request(method, path, data=None, headers=None):
                conn = http.client.HTTPConnection('127.0.0.1', port, timeout=2)
                try:
                    conn.request(
                        method,
                        path,
                        body=json.dumps(data) if data is not None else None,
                        headers=headers or {},
                    )
                    response = conn.getresponse()
                    return response.status, response.read().decode()
                finally:
                    conn.close()

            try:
                for _ in range(40):
                    try:
                        status, html = request('GET', '/')
                        break
                    except OSError:
                        time.sleep(0.1)
                else:
                    self.fail('Serwer nie wystartował')
                self.assertEqual(status, 200)
                self.assertIn('NickTrail', html)
                self.assertIn('lang="en"', html)
                for language, label in {'en': 'My accounts', 'pl': 'Moje konta'}.items():
                    status, localized = request('GET', '/?lang=' + language)
                    self.assertEqual(status, 200)
                    self.assertIn('lang="' + language + '"', localized)
                    self.assertIn(label, localized)
                    self.assertIn('id="languageSelect"', localized)
                self.assertIn('lang="en"', request('GET', '/?lang=invalid')[1])

                original_settings = json.loads(request('GET', '/api/settings')[1])
                english_settings = json.loads(
                    request('GET', '/api/settings', headers={'X-NickTrail-Language': 'en'})[1]
                )
                self.assertEqual(original_settings['values'], english_settings['values'])
                self.assertNotEqual(original_settings['labels'], english_settings['labels'])
                self.assertEqual(
                    original_settings,
                    json.loads(request('GET', '/api/settings', headers={'X-NickTrail-Language': 'pl'})[1]),
                )

                health = json.loads(request('GET', '/api/health-report?source=Maigret&limit=1')[1])
                self.assertEqual(health['matched'], 500)
                self.assertEqual(len(health['rows']), 1)
                self.assertEqual(sum(health['health_counts'].values()), health['total_definitions'])
                self.assertEqual(request('GET', '/api/health-report?min_age=-1')[0], 400)
                token = re.search(r'nonce="([^"]+)"', html)[1]
                for tag in re.findall(r'<script\b[^>]*>', html):
                    self.assertIn('nonce="' + token + '"', tag)
                status, capabilities = request('GET', '/api/exposure-capabilities')
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(capabilities)['PUBLIC_BREACH_CATALOG'], 'AVAILABLE')
                self.assertEqual(request('POST', '/api/create', {'name': 'Fikcyjny'})[0], 403)
                headers = {'Content-Type': 'application/json', 'X-NickTrail-Token': token}
                self.assertEqual(
                    request('POST', '/api/exposure-provider', {'operation': 'arbitrary-url'}, headers)[0], 400
                )
                status, result = request('POST', '/api/create', {'name': 'Fikcyjny'}, headers)
                self.assertEqual(status, 200)
                project = json.loads(result)['result']
                state = json.loads(request('GET', '/api/state?project=' + str(project))[1])
                self.assertTrue(
                    any(c['id'] == 'Keybase' and c['outbound_links'] for c in state['discovery_coverage'])
                )
                self.assertTrue(any(c['id'] == 'SearXNG' for c in state['providers']))
                status, result = request(
                    'POST',
                    '/api/context-plan',
                    {
                        'nickname': 'fictional',
                        'criteria': {'first_name': 'Żaneta', 'birth_date': '2000-02-29'},
                    },
                    headers,
                )
                self.assertEqual(status, 200)
                self.assertGreaterEqual(len(json.loads(result)['result']['queries']), 50)
                self.assertNotIn('2000-02-29', json.dumps(json.loads(result)['result']['queries']))
                self.assertEqual(
                    request('POST', '/api/context-plan', {'criteria': {'birth_date': '2023-02-29'}}, headers)[
                        0
                    ],
                    400,
                )
                self.assertEqual(
                    request(
                        'POST',
                        '/api/exposure',
                        {'project': project, 'account': 'self@example.org', 'consent': False},
                        headers,
                    )[0],
                    400,
                )
                self.assertEqual(
                    request(
                        'POST',
                        '/api/discover',
                        {'project': project, 'nickname': 'fictional', 'verify_top': True},
                        headers,
                    )[0],
                    400,
                )
                status, result = request(
                    'POST',
                    '/api/add',
                    {'project': project, 'value': 'https://github.com/fictional-nicktrail'},
                    headers,
                )
                root = json.loads(result)['result']
                self.assertEqual(
                    request(
                        'POST', '/api/bridges', {'project': project, 'root': root, 'preview': True}, headers
                    )[0],
                    200,
                )
                self.assertEqual(
                    request(
                        'POST',
                        '/api/bridges',
                        {'project': project, 'root': root, 'options': {'queries': 999}},
                        headers,
                    )[0],
                    400,
                )
                self.assertEqual(
                    request(
                        'POST',
                        '/api/bridges',
                        {'project': project, 'root': root, 'platforms': ['Free']},
                        headers,
                    )[0],
                    400,
                )
                self.assertEqual(status, 200)
                node = json.loads(result)['result']
                self.assertEqual(
                    request('POST', '/api/decide', {'id': node, 'decision': 'mine'}, headers)[0], 200
                )
                snapshot = json.loads(request('GET', f'/api/state?project={project}')[1])['snapshot']
                self.assertEqual(snapshot['nodes'][0]['ownership'], 'mine')
                status, plan = request(
                    'POST',
                    '/api/historical',
                    {'project': project, 'node': node, 'date': '2020-01-01', 'preview': True},
                    headers,
                )
                self.assertEqual(status, 200)
                self.assertEqual(json.loads(plan)['result']['network_calls'], 0)
                self.assertEqual(
                    request(
                        'POST',
                        '/api/historical',
                        {'project': project, 'node': node, 'date': '2020-01-01', 'consent': False},
                        headers,
                    )[0],
                    400,
                )
                history = json.loads(request('GET', f'/api/profile-history?project={project}&node={node}')[1])
                self.assertEqual(history['node'], node)
                self.assertEqual(request('GET', f'/api/profile-history?project=0&node={node}')[0], 400)
                self.assertEqual(
                    request(
                        'POST',
                        '/api/discover',
                        {'project': project, 'nickname': 'synthetic', 'variants': 'yes'},
                        headers,
                    )[0],
                    400,
                )
                dashboard = json.loads(request('GET', f'/api/state?project={project}')[1])
                self.assertEqual(len(dashboard['service_catalog']), 100)
                self.assertTrue(next(p for p in dashboard['providers'] if p['id'] == 'Free')['available'])
                self.assertEqual(dashboard['history_window']['scans'], 25)
                self.assertIn('percent', dashboard['progress'])
                self.assertEqual(request('GET', f'/api/export?project={project}&omit_email=1')[0], 200)
                self.assertEqual(request('GET', '/', headers={'Host': 'attacker.example'})[0], 403)
                self.assertEqual(
                    request(
                        'POST', '/api/create', {'name': 'X'}, headers | {'Origin': 'http://attacker.example'}
                    )[0],
                    403,
                )
                self.assertEqual(
                    request('POST', '/api/search', {'project': project, 'nickname': '../settings'}, headers)[
                        0
                    ],
                    400,
                )
                self.assertEqual(
                    request(
                        'POST',
                        '/api/discover',
                        {'project': project, 'nickname': 'fictional', 'aliases': ['a', 'b', 'c', 'd', 'e']},
                        headers,
                    )[0],
                    400,
                )
                status, body = request(
                    'POST',
                    '/api/discover',
                    {'project': project, 'nickname': 'fictional', 'platforms': ['GitHub', 'NoSuchSource']},
                    headers,
                )
                self.assertEqual(status, 400)
                self.assertIn('NoSuchSource', body)
                self.assertEqual(
                    request(
                        'POST',
                        '/api/discover',
                        {
                            'project': project,
                            'nickname': 'fictional',
                            'related': True,
                            'options': {'candidates': True},
                        },
                        headers,
                    )[0],
                    400,
                )
                status, result = request(
                    'POST', '/api/add', {'project': project, 'value': 'https://x.com/fictional_nt'}, headers
                )
                candidate = json.loads(result)['result']
                self.assertEqual(
                    request('POST', '/api/check', {'project': project, 'ids': [candidate]}, headers)[0], 200
                )
                for _ in range(50):
                    state = json.loads(request('GET', f'/api/state?project={project}')[1])
                    if not state['job']['running']:
                        break
                    time.sleep(0.05)
                self.assertFalse(state['job']['running'])
                self.assertEqual(state['job']['error'], '')
                n = next(n for n in state['snapshot']['nodes'] if n['id'] == candidate)
                self.assertEqual(n['ownership'], 'unknown')
                self.assertEqual(n['state'], 'unsupported')
                caps = json.loads(request('GET', '/api/capabilities')[1])
                self.assertEqual(caps['counts']['imported_definitions'], 883)
                self.assertNotIn('Extended', caps['presets']['STANDARD']['platforms'])
                self.assertEqual(
                    request(
                        'POST',
                        '/api/diagnose',
                        {'project': project, 'url': 'https://x.com/fictional_nt'},
                        headers,
                    )[0],
                    200,
                )
                bench = json.loads(
                    request(
                        'POST',
                        '/api/golden',
                        {'project': project, 'benchmark': {'true_profiles': ['https://x.com/fictional_nt']}},
                        headers,
                    )[1]
                )
                self.assertEqual(bench['result']['found_known_true'], 0)
                status, packet = request(
                    'POST', '/api/ai-packet', {'project': project, 'ids': [root, candidate]}, headers
                )
                self.assertEqual(status, 200)
                self.assertFalse(json.loads(packet)['result']['packet']['privacy']['external_submission'])
                status, formatted = request(
                    'POST',
                    '/api/ai-packet',
                    {'project': project, 'ids': [root, candidate], 'format': 'markdown'},
                    headers,
                )
                self.assertEqual(status, 200)
                self.assertTrue(
                    json.loads(formatted)['result']['rendered'].startswith('# Pakiet do samodzielnego audytu')
                )
                self.assertEqual(
                    request(
                        'POST',
                        '/api/discover',
                        {'project': project, 'nickname': 'fictional', 'scan_mode': 'UNKNOWN'},
                        headers,
                    )[0],
                    400,
                )
                self.assertEqual(
                    request('POST', '/api/local-ai-preview', {'project': project}, headers)[0], 404
                )
                self.assertEqual(
                    json.loads(request('POST', '/api/planner-preview', {'project': project}, headers)[1])[
                        'result'
                    ]['network_calls'],
                    0,
                )
                self.assertEqual(
                    request('POST', '/api/focus', {'project': project, 'id': candidate}, headers)[0], 200
                )
                state = json.loads(request('GET', f'/api/state?project={project}')[1])
                self.assertEqual(state['snapshot']['focus'][0]['node'], candidate)
                self.assertEqual(state['focusResults']['root'], candidate)
                self.assertTrue(state['ranking']['nodes'][str(candidate)]['selected'])
                self.assertEqual(request('POST', '/api/focused-scan', {'project': project}, headers)[0], 200)
                for _ in range(50):
                    state = json.loads(request('GET', f'/api/state?project={project}')[1])
                    if not state['job']['running']:
                        break
                    time.sleep(0.05)
                self.assertEqual(state['focusResults']['scans'][-1]['status'], 'completed')
                self.assertEqual(json.loads(state['focusResults']['scans'][-1]['visited']), [candidate])
                self.assertIn(candidate, state['focusResults']['unread'])
                self.assertEqual(
                    request(
                        'POST',
                        '/api/manual-link',
                        {
                            'source': candidate,
                            'url': 'https://hackerone.com/fictional',
                            'note': 'Link widoczny w polu strony — fikcyjny test',
                        },
                        headers,
                    )[0],
                    200,
                )
                state = json.loads(request('GET', f'/api/state?project={project}')[1])
                self.assertEqual(state['focusResults']['links'][0]['method'], 'manual_observation')
                self.assertEqual(state['focusResults']['links'][0]['decision'], 'unknown')
                self.assertEqual(
                    request(
                        'POST',
                        '/api/browser-check',
                        {'project': project, 'ids': [candidate], 'options': {'queries': 0, 'seconds': 1}},
                        headers,
                    )[0],
                    200,
                )
                for _ in range(50):
                    state = json.loads(request('GET', f'/api/state?project={project}')[1])
                    if not state['job']['running']:
                        break
                    time.sleep(0.05)
                self.assertEqual(
                    next(n for n in state['snapshot']['nodes'] if n['id'] == candidate)['state'], 'partial'
                )
                self.assertEqual(state['exposure'], [])
                self.assertEqual(
                    request(
                        'POST',
                        '/api/branches',
                        {'project': project, 'roots': [candidate], 'options': {'queries': 2, 'seconds': 5}},
                        headers,
                    )[0],
                    200,
                )
                for _ in range(50):
                    state = json.loads(request('GET', f'/api/state?project={project}')[1])
                    if not state['job']['running']:
                        break
                    time.sleep(0.05)
                self.assertEqual(state['branches'][0]['run']['status'], 'completed')
                self.assertEqual(state['branches'][0]['nodes'][0]['node'], candidate)
                self.assertEqual(state['labels'][str(candidate)]['color'], 'gray')
                self.assertEqual(
                    request('GET', f'/api/avatar?node={candidate}')[0], 204
                )  # rc18: cached empty answer, no console error
                self.assertEqual(request('GET', '/favicon.ico')[0], 204)
                self.assertEqual(
                    request(
                        'GET',
                        '/api/state?project=0',
                        headers={'Host': '127.0.0.1:' + str(port), 'Sec-Fetch-Site': 'cross-site'},
                    )[0],
                    403,
                )
                self.assertEqual(
                    request(
                        'POST',
                        '/api/discover',
                        {
                            'project': project,
                            'nickname': 'fictional',
                            'platforms': ['YouTube'],
                            'aliases': ['old-fictional'],
                            'related': True,
                        },
                        headers,
                    )[0],
                    200,
                )
                for _ in range(50):
                    state = json.loads(request('GET', f'/api/state?project={project}')[1])
                    if not state['job']['running']:
                        break
                    time.sleep(0.05)
                self.assertEqual(state['searches'][0]['run']['status'], 'completed')
                self.assertTrue(all(s['state'] == 'unsupported' for s in state['searches'][0]['sources']))
                self.assertEqual(
                    request(
                        'POST',
                        '/api/posts',
                        {
                            'project': project,
                            'source': candidate,
                            'entries': [
                                {
                                    'text': 'Mój GitHub to https://github.com/fictional-other',
                                    'author': 'Fikcja',
                                }
                            ],
                        },
                        headers,
                    )[0],
                    200,
                )
                self.assertEqual(
                    request('GET', f'/api/export?project={project}&format=html&omit_email=1')[0], 200
                )
            finally:
                process.terminate()
                process.wait(timeout=10)
                if process.stderr:
                    process.stderr.close()


if __name__ == '__main__':
    unittest.main()
