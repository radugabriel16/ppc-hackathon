import http from 'k6/http';
import { Counter, Rate } from 'k6/metrics';

export const BASE = __ENV.BASE_URL || 'https://nginx';
export const ORIGIN = __ENV.ORIGIN || 'https://localhost';
export const ingestErrors = new Rate('ingest_errors');
export const uploadErrors = new Rate('upload_errors');
export const uploadRejected = new Counter('upload_rejected_503');
export const ingestRejected = new Counter('ingest_rejected_503');

// One login per run (login is rate-limited); VUs reuse the session cookie + CSRF token.
export function login() {
  const res = http.post(`${BASE}/api/v1/auth/login`,
    JSON.stringify({ username: 'operator', password: __ENV.OPERATOR_PASSWORD }),
    { headers: { 'Content-Type': 'application/json', Origin: ORIGIN } });
  if (res.status !== 200) throw new Error(`login failed: ${res.status}`);
  const session = res.cookies['filegrid_session'][0].value;
  const csrf = res.cookies['filegrid_csrf'][0].value;
  const auth = { Cookie: `filegrid_session=${session}; filegrid_csrf=${csrf}`, Origin: ORIGIN, 'X-CSRF-Token': csrf };
  const meters = http.get(`${BASE}/api/v1/meters?size=100`, { headers: auth }).json('items').map((m) => m.externalCode);
  const asset = http.get(`${BASE}/api/v1/assets`, { headers: auth }).json('items')[0];
  // Unique per run: random start inside the last 60 days, 1-second granularity.
  const t0 = Math.floor(Date.now() / 1000) - 86400 * 60 + Math.floor(Math.random() * 86400 * 50);
  return { auth, meters, asset, t0 };
}

const iso = (s) => new Date(s * 1000).toISOString().replace('.000Z', 'Z');

export function ingestOne(data, i) {
  const code = data.meters[i % data.meters.length];
  const start = data.t0 + 900 * Math.floor(i / data.meters.length);
  const body = JSON.stringify({
    meterExternalCode: code, readingKey: `${code}:${iso(start)}`, seq: i,
    intervalStart: iso(start), intervalEnd: iso(start + 900), energyKwh: 1.25,
  });
  const res = http.post(`${BASE}/api/v1/meter-readings/ingest`, body, {
    headers: { 'Content-Type': 'application/json', Authorization: `Bearer ${__ENV.SIMULATOR_TOKEN}` },
    tags: { kind: 'ingest' },
    responseCallback: http.expectedStatuses(200, 201),
  });
  ingestErrors.add(res.status !== 200 && res.status !== 201, { kind: 'ingest' });
  if (res.status === 503) ingestRejected.add(1);
  return res;
}

export function uploadOutage(data, size) {
  const meta = JSON.stringify({
    category: 'OUTAGE_RECORD', assetId: data.asset.id, regionId: data.asset.regionId,
    startedAt: '2026-01-01T10:00:00Z', severity: 'HIGH',
  });
  const content = 'x'.repeat(size);
  const res = http.post(`${BASE}/api/v1/files`, {
    metadata: http.file(meta, 'metadata.json', 'application/json'),
    file: http.file(content, `loadtest-${__VU}-${__ITER}.bin`, 'application/octet-stream'),
  }, { headers: data.auth, tags: { kind: 'upload' }, responseCallback: http.expectedStatuses(201, 503) });
  uploadErrors.add(res.status !== 201, { kind: 'upload' });
  if (res.status === 503) uploadRejected.add(1);
  return res;
}

export function summary(name, data) {
  const out = `${__ENV.RESULT_DIR || '/tmp'}/${name}.json`;
  const m = data.metrics;
  const line = (k, f) => (m[k] ? f(m[k].values) : 'n/a');
  const text = `\n${name}: ingest p95=${line('http_req_duration{kind:ingest}', (v) => v['p(95)'].toFixed(1) + 'ms')}`
    + ` rps=${line('http_reqs', (v) => v.rate.toFixed(1))}`
    + ` ingest_errors=${line('ingest_errors', (v) => (v.rate * 100).toFixed(2) + '%')}`
    + ` upload_errors=${line('upload_errors', (v) => (v.rate * 100).toFixed(2) + '%')}`
    + ` upload_503=${line('upload_rejected_503', (v) => v.count)}\n`;
  return { [out]: JSON.stringify(data, null, 2), stdout: text };
}
