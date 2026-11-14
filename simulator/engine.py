import asyncio
import hashlib
import json
import logging
import math
import os
import random
import time
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram

from store import Store, iso

log = logging.getLogger('simulator')


def retry_delay(attempt, retry_after=None):
    delay = random.uniform(0.5, 1.0) * min(60, 2 ** min(attempt, 6))
    if retry_after:
        try:
            minimum = float(retry_after)
        except ValueError:
            try:
                minimum = parsedate_to_datetime(retry_after).timestamp() - time.time()
            except (ValueError, TypeError, OverflowError):
                minimum = 0
        if math.isfinite(minimum):
            delay = max(delay, minimum)
    return delay


class Engine:
    def __init__(self, path=None, client=None):
        self.store = Store(path or os.getenv('SIM_DB_PATH', '/data/outbox.sqlite3'))
        self.client = client or httpx.AsyncClient(timeout=10, limits=httpx.Limits(max_connections=2))
        self.ingest = os.getenv('SIM_INGEST_URL', 'http://api-ingest:8000/api/v1/meter-readings/ingest')
        self.files = os.getenv('SIM_FILES_URL', 'http://api-files:8000/api/v1')
        self.secret_dir = Path(os.getenv('SIM_SECRETS_DIR', '/run/secrets'))
        self.cap = int(os.getenv('SIM_MAX_OUTBOX', '10000'))
        self.max_rate = float(os.getenv('SIM_MAX_RPS', '20'))
        self.speed = float(os.getenv('SIM_SPEED_FACTOR', '1'))
        if self.cap < 1 or not 0 < self.max_rate <= 100 or not 0 < self.speed <= 100:
            raise ValueError('Invalid simulator safety limits')
        self.meters = json.loads(Path(__file__).with_name('meters.json').read_text())
        self.source = 'fallback'
        self.control = self.store.get('control', dict(running=False, profile=None, readingsPerSecond=None))
        self.registry = CollectorRegistry()
        self.sent = Counter('filegrid_sim_sent_total', 'Ingest outcomes', ['result'], registry=self.registry)
        for result in ('created', 'duplicate', 'conflict', 'retry'):
            self.sent.labels(result)
        self.queue = Gauge('filegrid_sim_outbox_size', 'Pending readings', registry=self.registry)
        self.duration = Histogram('filegrid_sim_send_duration_seconds', 'Ingest latency', registry=self.registry)
        self.error = None
        self.tasks = []

    async def load_meters(self):
        try:
            password = (self.secret_dir / 'operator_password').read_text().strip()
            response = await self.client.post(f'{self.files}/auth/login',
                json={'username': 'operator', 'password': password},
                headers={'Origin': os.getenv('APP_ORIGIN', 'https://localhost')})
            response.raise_for_status()
            # The real API marks cookies Secure. Forward the returned session explicitly
            # only to this fixed internal files endpoint, never to the ingest endpoint.
            cookies = '; '.join(f'{c.name}={c.value}' for c in response.cookies.jar)
            headers = {'Cookie': cookies}
            async def pages(resource):
                items, page = [], 0
                while True:
                    res = await self.client.get(f'{self.files}/{resource}',
                        params={'page': page, 'size': 100}, headers=headers)
                    res.raise_for_status()
                    body = res.json()
                    items.extend(body['items'])
                    page += 1
                    if page >= body['totalPages']:
                        return items
            meters = await pages('meters')
            if not meters:
                raise ValueError('No meters available')
            try:
                types = {c['id']: c['clientType'] for c in await pages('clients')}
            except (httpx.HTTPError, KeyError, ValueError):
                types = {}
            for meter in meters:
                meter['clientType'] = types.get(meter.get('clientId'), 'RESIDENTIAL')
            self.meters, self.source = meters, 'api'
        except (OSError, httpx.HTTPError, ValueError, KeyError):
            log.warning('Meter discovery unavailable; using local fixtures')

    def status(self):
        base = self.control.get('readingsPerSecond') or len(self.meters) / 5
        factor = {'normal': 1, 'peak': 5, 'storm': 10}.get(self.control.get('profile'), 1)
        job = self.store.get('backfill')
        status = {k: self.control.get(k) for k in ('running', 'profile', 'readingsPerSecond')}
        if job and not job.get('paused'):
            status.update(running=True, profile=job['profile'])
        return status | {
            'meterCount': len(self.meters), 'meterSource': self.source,
            'outboxSize': self.store.count(), 'generationPaused': self.store.count() >= self.cap,
            'effectiveReadingsPerSecond': min(self.max_rate, base * factor * self.speed),
            'lastError': self.error, 'backfillActive': self.store.get('backfill') is not None}

    def new_run(self, kind, profile):
        run = dict(id=str(uuid.uuid4()), kind=kind, profile=profile,
                   startedAt=iso(datetime.now(timezone.utc)), endedAt=None, counters={})
        self.store.run(run)
        return run

    def start(self, profile, rate):
        if not self.control['running']:
            self.control['runId'] = self.new_run('live', profile)['id']
        job = self.store.get('backfill')
        if job:
            job['paused'] = False
            self.store.set('backfill', job)
        self.control.update(running=True, profile=profile, readingsPerSecond=rate)
        self.store.set('control', self.control)
        return self.status()

    def stop(self):
        self.control['running'] = False
        job = self.store.get('backfill')
        if job:
            job['paused'] = True
            self.store.set('backfill', job)
        for run in self.store.runs():
            if run['id'] == self.control.get('runId') and run['endedAt'] is None:
                run['endedAt'] = iso(datetime.now(timezone.utc))
                self.store.run(run)
        self.store.set('control', self.control)
        return self.status()

    def energy(self, meter, start):
        local = start.astimezone(ZoneInfo('Europe/Bucharest'))
        hour = local.hour + local.minute / 60
        kind = meter.get('clientType', 'RESIDENTIAL')
        if kind == 'INDUSTRIAL':
            kw = 60 * (1 if local.weekday() < 5 else 0.7)
        elif kind == 'COMMERCIAL':
            kw = (12 if 8 <= hour < 20 else 2) * (1 if local.weekday() < 5 else 0.6)
        else:
            kw = 0.35 + 1.5 * math.exp(-((hour - 19) / 2.5) ** 2) + 0.7 * math.exp(-((hour - 7) / 1.5) ** 2)
            kw *= 1.15 if local.weekday() >= 5 else 1
        seed = hashlib.sha256(f"{meter['externalCode']}:{iso(start)}".encode()).digest()
        return round(kw / 4 * random.Random(seed).uniform(0.85, 1.15), 6)

    def live_tick(self, index):
        meter = self.meters[index % len(self.meters)]
        row = self.store.db.execute('SELECT next_start FROM meters WHERE code=?', (meter['externalCode'],)).fetchone()
        now = datetime.now(timezone.utc)
        start = datetime.fromisoformat(row[0]) if row else now.replace(
            minute=now.minute // 15 * 15, second=0, microsecond=0)
        self.store.enqueue(meter, self.energy(meter, start), self.control.get('runId'), start=start)

    def backfill_tick(self, job):
        start = datetime.fromisoformat(job['cursor'])
        if start >= datetime.fromisoformat(job['to']):
            for run in self.store.runs():
                if run['id'] == job['runId']:
                    run['endedAt'] = iso(datetime.now(timezone.utc))
                    self.store.run(run)
            self.store.set('backfill', None)
            return
        meter = job['meters'][job['index']]
        energy = self.energy(meter, start)
        # Repeatable, visible anomaly windows; a gap intentionally emits no reading.
        anomaly = job['anomalies'][(start.hour // 3) % len(job['anomalies'])] if job['anomalies'] else None
        if anomaly == 'spike':
            energy *= 5
        elif anomaly == 'zero':
            energy = 0
        job['index'] += 1
        if job['index'] == len(job['meters']):
            job['index'] = 0
            job['cursor'] = iso(start + timedelta(minutes=15))
        self.store.enqueue(meter, energy, job['runId'], start, gap=anomaly == 'gap', job=job)

    async def generate(self):
        index = 0
        while True:
            job = self.store.get('backfill')
            if job and job.get('paused'):
                job = None
            if (self.control['running'] or job) and self.store.count() < self.cap:
                if job:
                    self.backfill_tick(job)
                else:
                    self.live_tick(index)
                    index += 1
                rate = self.control.get('readingsPerSecond') or len(self.meters) / 5
                profile = self.control.get('profile') if not job else job['profile']
                factor = 5 if profile == 'peak' else (10 if profile == 'storm' and time.monotonic() % 10 < 2 else 1)
                await asyncio.sleep(1 / min(self.max_rate, rate * factor * self.speed))
            else:
                await asyncio.sleep(0.1)
            self.queue.set(self.store.count())

    async def send_one(self):
        row = self.store.next(time.time())
        if row is None:
            return False
        started = time.monotonic()
        retry_after = None
        try:
            token = (self.secret_dir / 'simulator_token').read_text().strip()
            response = await self.client.post(self.ingest, content=row['payload'].encode(),
                headers={'Authorization': f'Bearer {token}', 'Content-Type': 'application/json'})
            code = response.status_code
            result = {201: 'created', 200: 'duplicate', 409: 'conflict'}.get(code)
            if result:
                self.store.ack(row, result)
                self.sent.labels(result).inc()
                self.error = None if code != 409 else 'READING_CONFLICT'
                return True
            retry_after = response.headers.get('Retry-After')
            self.error = f'HTTP_{code}'
        except (OSError, httpx.HTTPError):
            self.error = 'INGEST_UNAVAILABLE'
        finally:
            self.duration.observe(time.monotonic() - started)
            self.queue.set(self.store.count())
        self.sent.labels('retry').inc()
        delay = retry_delay(row['attempts'], retry_after)
        self.store.retry(row, time.time() + delay)
        # Apply backpressure to all outgoing requests, including other queued rows.
        self.store.set('sendNotBefore', time.time() + delay)
        return False

    async def send(self):
        while True:
            wait = self.store.get('sendNotBefore', 0) - time.time()
            if wait > 0:
                await asyncio.sleep(min(wait, 0.2))
                continue
            sent = await self.send_one()
            await asyncio.sleep(1 / self.max_rate if sent else 0.1)

    async def open(self):
        await self.load_meters()
        self.tasks = [asyncio.create_task(self.generate()), asyncio.create_task(self.send())]

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)
        await self.client.aclose()
        self.store.db.close()
