"""Run from repository root with Docker running; restores storage-db in finally."""
import json
import subprocess
import time

import httpx


def compose(*args):
    return subprocess.check_output(['docker', 'compose', *args], text=True).strip()


def internal(path):
    return json.loads(compose('exec', '-T', 'simulator', 'python', '-c',
        f"import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8080{path}').read().decode())"))


def main():
    compose('up', '-d', '--build')
    password = compose('exec', '-T', 'api-files', 'python', '-c',
                       "from pathlib import Path; print(Path('/run/secrets/manager_password').read_text().strip())")
    with httpx.Client(base_url='https://localhost', verify=False, timeout=15,
                      headers={'Origin': 'https://localhost'}) as client:
        response = client.post('/api/v1/auth/login', json={'username': 'manager', 'password': password})
        response.raise_for_status()
        client.headers['X-CSRF-Token'] = client.cookies['filegrid_csrf']

        def api(method, path, **kwargs):
            r = client.request(method, '/api/v1/' + path, **kwargs)
            r.raise_for_status()
            return r.json()

        def count_readings():
            return api('GET', 'meter-readings', params={'size': 1})['totalElements']

        api('POST', 'admin/simulator/stop')
        status = api('GET', 'admin/simulator/status')
        assert status['outboxSize'] == 0, 'Drain existing queue before this test'
        before = count_readings()
        api('POST', 'admin/simulator/start', json={'profile': 'normal',
            'readingsPerSecond': status['meterCount'] / 5})
        try:
            time.sleep(60)
            assert count_readings() > before, 'No readings visible after 60 seconds'
            compose('stop', 'storage-db')
            queued_before = api('GET', 'admin/simulator/status')['outboxSize']
            time.sleep(30)
            status = api('GET', 'admin/simulator/status')
            assert status['outboxSize'] > queued_before, 'Queue did not grow during outage'
        finally:
            # Always restore the shared stack, including if an assertion fails.
            compose('start', 'storage-db')
            api('POST', 'admin/simulator/stop')
        deadline = time.monotonic() + 180
        while api('GET', 'admin/simulator/status')['outboxSize']:
            assert time.monotonic() < deadline, 'Queue did not drain'
            time.sleep(2)
        run = next(r for r in internal('/runs?size=100')['items'] if r['kind'] == 'live')
        counters = run['counters']
        assert counters.get('conflict', 0) == 0, counters
        assert counters['generated'] == counters.get('created', 0) + counters.get('duplicate', 0), counters
        assert count_readings() - before == counters.get('created', 0), counters
        print('PASS: admin API, 60s generation, 30s storage outage, durable drain, counts match')
        print('Manual check still required: map/admin UI Start, speed selector, Stop')


if __name__ == '__main__':
    main()
