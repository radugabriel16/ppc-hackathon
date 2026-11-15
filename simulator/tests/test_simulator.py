import asyncio
import json
import os
import random
import tempfile
import threading
import time
import unittest
from datetime import datetime, timedelta, timezone
from email.utils import format_datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import patch

import httpx

from app import create_app
from engine import Engine, retry_delay
from store import Store


class FakeIngest:
    def __init__(self):
        self.until = 0
        self.retry_after = '1'
        self.records = {}
        self.requests = []
        self.codes = []
        self.random = random.Random(7)
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                raw = self.rfile.read(int(self.headers['Content-Length']))
                payload = json.loads(raw)
                owner.requests.append((time.monotonic(), raw, self.headers.get('Authorization')))
                key = payload['readingKey']
                if time.monotonic() < owner.until:
                    code = 503
                else:
                    code = owner.random.choice([201, 200, 409, 503])
                    if code != 503:
                        owner.records[key] = raw
                owner.codes.append(code)
                self.send_response(code)
                if code == 503:
                    self.send_header('Retry-After', owner.retry_after)
                self.send_header('Content-Length', '2')
                self.end_headers()
                self.wfile.write(b'{}')

            def log_message(self, *_):
                pass

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.url = f'http://127.0.0.1:{self.server.server_port}/api/v1/meter-readings/ingest'

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join()


class SimulatorTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name)
        (self.path / 'simulator_token').write_text('test-token')
        self.env = patch.dict(os.environ, {'SIM_SECRETS_DIR': self.tmp.name})
        self.env.start()
        self.e = Engine(str(self.path / 'outbox.db'))

    async def asyncTearDown(self):
        await self.e.close()
        self.env.stop()
        self.tmp.cleanup()

    async def test_outage_30_seconds_restart_and_no_loss(self):
        fake = FakeIngest()
        self.e.ingest = fake.url
        fake.until = time.monotonic() + 30
        fake.retry_after = '30'
        self.e.start('normal', 2.4)
        self.e.tasks = [asyncio.create_task(self.e.generate()), asyncio.create_task(self.e.send())]
        try:
            await asyncio.sleep(15)
            first_size = self.e.store.count()
            self.assertGreater(first_size, 20)
            # Restart midway through the outage, preserving both control and outbox.
            await self.e.close()
            self.e = Engine(str(self.path / 'outbox.db'))
            self.e.ingest = fake.url
            self.assertEqual(self.e.store.count(), first_size)
            self.assertTrue(self.e.control['running'])
            self.e.tasks = [asyncio.create_task(self.e.generate()), asyncio.create_task(self.e.send())]
            await asyncio.sleep(15.2)
            self.e.stop()
            generated = self.e.store.db.execute('SELECT count(*) FROM generated').fetchone()[0]
            self.assertGreater(generated, first_size)
            self.assertGreater(self.e.store.count(), 0)
            fake.retry_after = '1'
            deadline = time.monotonic() + 90
            while self.e.store.count() and time.monotonic() < deadline:
                await asyncio.sleep(0.1)
            self.assertEqual(self.e.store.count(), 0)
            self.assertEqual(len(fake.records), generated)
            self.assertGreaterEqual(fake.requests[1][0] - fake.requests[0][0], 29.9)
            self.assertTrue({200, 201, 409, 503}.issubset(set(fake.codes)))
            self.assertTrue(all(r[2] == 'Bearer test-token' for r in fake.requests))
            payloads = {}
            for _, raw, _ in fake.requests:
                key = json.loads(raw)['readingKey']
                self.assertEqual(payloads.setdefault(key, raw), raw)
            counters = self.e.store.runs()[0]['counters']
            self.assertEqual(sum(counters.get(k, 0) for k in ['created', 'duplicate', 'conflict']), generated)
        finally:
            fake.close()

    async def test_control_contract_limits_stop_and_metrics(self):
        app = create_app(self.e)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://sim') as client:
            for payload in ({}, {'profile': 'normal', 'readingsPerSecond': 1.2},
                            {'profile': 'peak', 'rate': 1}, {'intervalSeconds': 10}):
                response = await client.post('/start', json=payload)
                self.assertEqual(response.status_code, 200)
                self.assertTrue(response.json()['running'])
            for payload in ({'intervalSeconds': 1}, {'readingsPerSecond': 1000},
                            {'profile': 'bad'}, {'rate': 1, 'readingsPerSecond': 1}):
                self.assertEqual((await client.post('/start', json=payload)).status_code, 422)
            self.assertFalse((await client.post('/stop')).json()['running'])
            self.assertEqual((await client.get('/runs')).json()['totalElements'], 1)
            self.assertEqual((await client.get('/health/live')).status_code, 200)
            metrics = (await client.get('/metrics')).text
            for name in ['filegrid_sim_sent_total', 'filegrid_sim_outbox_size', 'filegrid_sim_send_duration_seconds']:
                self.assertIn(name, metrics)

    async def test_cap_stop_and_backfill_resume(self):
        self.e.cap = 3
        self.e.start('normal', 20)
        task = asyncio.create_task(self.e.generate())
        self.e.tasks = [task]
        await asyncio.sleep(0.3)
        self.assertEqual(self.e.store.count(), 3)
        self.assertTrue(self.e.status()['generationPaused'])
        self.e.stop()
        self.e.store.db.execute('DELETE FROM outbox')
        self.e.store.db.commit()
        await asyncio.sleep(0.2)
        self.assertEqual(self.e.store.count(), 0)
        app = create_app(self.e)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url='http://sim') as c:
            body = {'from': '2025-01-01T00:00:00Z', 'to': '2025-01-01T00:30:00Z', 'anomalies': ['zero']}
            self.assertEqual((await c.post('/backfill', json=body)).status_code, 202)
            await asyncio.sleep(0.3)
            await c.post('/stop')
            count = self.e.store.count()
            await asyncio.sleep(0.2)
            self.assertEqual(self.e.store.count(), count)
            self.assertTrue(self.e.store.get('backfill')['paused'])
            self.assertEqual((await c.post('/backfill', json=body)).status_code, 409)

    async def test_discovery_login_secure_cookie_pagination_types(self):
        (self.path / 'operator_password').write_text('test-password')
        def handler(req):
            if req.url.path.endswith('/auth/login'):
                self.assertEqual(req.headers['Origin'], 'https://localhost')
                return httpx.Response(200, json={}, headers={'Set-Cookie': 'filegrid_session=abc; Secure; HttpOnly; Path=/'})
            self.assertIn('filegrid_session=abc', req.headers['Cookie'])
            if req.url.path.endswith('/clients'):
                return httpx.Response(200, json={'items': [{'id': 'c', 'clientType': 'INDUSTRIAL'}], 'totalPages': 1})
            page = int(req.url.params['page'])
            return httpx.Response(200, json={'items': [{'externalCode': f'API-{page}', 'clientId': 'c'}], 'totalPages': 2})
        await self.e.client.aclose()
        self.e.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        await self.e.load_meters()
        self.assertEqual(self.e.source, 'api')
        self.assertEqual(len(self.e.meters), 2)
        self.assertEqual(self.e.meters[1]['clientType'], 'INDUSTRIAL')

    async def test_retry_after_formats_and_invalid_payload_retained(self):
        self.assertGreaterEqual(retry_delay(0, '12'), 12)
        self.assertGreater(retry_delay(0, format_datetime(datetime.now(timezone.utc) + timedelta(seconds=20))), 18)
        self.assertLessEqual(retry_delay(100), 60)
        self.e.live_tick(0)
        await self.e.client.aclose()
        self.e.client = httpx.AsyncClient(transport=httpx.MockTransport(lambda req: httpx.Response(422)))
        await self.e.send_one()
        self.assertEqual(self.e.store.count(), 1)
        self.assertEqual(self.e.error, 'HTTP_422')

    async def test_lost_response_retries_identical_bytes_as_duplicate(self):
        seen = []
        def handler(req):
            seen.append(req.content)
            if len(seen) == 1:
                # Server saved the payload, but the response was lost.
                raise httpx.ReadTimeout('Response lost', request=req)
            return httpx.Response(200)
        await self.e.client.aclose()
        self.e.client = httpx.AsyncClient(transport=httpx.MockTransport(handler))
        self.e.start('normal', 1)
        self.e.live_tick(0)
        await self.e.send_one()
        self.assertEqual(self.e.store.count(), 1)
        deadline = self.e.store.get('sendNotBefore')
        with patch('engine.time.time', return_value=deadline + 1):
            await self.e.send_one()
        self.assertEqual(self.e.store.count(), 0)
        self.assertEqual(seen[0], seen[1])
        self.assertEqual(self.e.store.runs()[0]['counters']['duplicate'], 1)

    async def test_backfill_progress_survives_restart(self):
        meter = self.e.meters[0]
        run = self.e.new_run('backfill', 'normal')
        job = dict(runId=run['id'], profile='normal', cursor='2025-01-01T00:00:00Z',
                   to='2025-01-01T00:30:00Z', meters=[meter], index=0, anomalies=[])
        self.e.store.set('backfill', job)
        self.e.backfill_tick(job)
        await self.e.close()
        self.e = Engine(str(self.path / 'outbox.db'))
        restored = self.e.store.get('backfill')
        self.assertEqual(restored['cursor'], '2025-01-01T00:15:00Z')
        self.assertTrue(self.e.status()['running'])
        self.e.backfill_tick(restored)
        self.e.backfill_tick(self.e.store.get('backfill'))
        self.assertIsNone(self.e.store.get('backfill'))
        self.assertEqual(self.e.store.count(), 2)
        self.assertEqual(self.e.store.runs()[0]['counters']['generated'], 2)
        self.assertIsNotNone(self.e.store.runs()[0]['endedAt'])

    async def test_overlap_preserves_bytes_sequence_and_anomalies(self):
        meter = self.e.meters[0]
        start = datetime(2025, 1, 1, tzinfo=timezone.utc)
        first = self.e.store.enqueue(meter, 1, None, start)
        again = self.e.store.enqueue(meter, 99, None, start)
        self.assertEqual(first, again)
        self.assertEqual(self.e.store.count(), 1)
        second = json.loads(self.e.store.enqueue(meter, 2, None))
        self.assertEqual(second['seq'], 2)
        self.assertEqual(datetime.fromisoformat(second['intervalEnd']) - datetime.fromisoformat(second['intervalStart']), timedelta(minutes=15))
        for anomaly, expected in [('zero', 0), ('spike', None), ('gap', None)]:
            run = self.e.new_run('backfill', 'normal')
            begin = start + timedelta(days=len(self.e.store.runs()))
            job = dict(cursor=begin.isoformat(), to=(begin + timedelta(minutes=15)).isoformat(),
                       index=0, meters=[meter], runId=run['id'], anomalies=[anomaly])
            before = self.e.store.count()
            self.e.backfill_tick(job)
            if anomaly == 'gap':
                self.assertEqual(before, self.e.store.count())
            else:
                raw = self.e.store.db.execute('SELECT payload FROM outbox ORDER BY id DESC').fetchone()[0]
                value = json.loads(raw)['energyKwh']
                self.assertEqual(value, 0 if anomaly == 'zero' else self.e.energy(meter, begin) * 5)


if __name__ == '__main__':
    unittest.main()
