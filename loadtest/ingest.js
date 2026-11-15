// Ingest + concurrent small-file uploads. PROFILE=normal|peak|storm  DURATION=60s
// Rates are multiples of BASE_RATE (default 2 req/s = "normal"): peak x5, storm x10. A single api-ingest
// replica saturates near 35 req/s on a dev laptop, so x10 of the default stays just under that.
// Concurrent small OUTAGE_RECORD uploads per second: normal 1, peak 3, storm 8.
import exec from 'k6/execution';
import { login, ingestOne, uploadOutage, summary } from './lib.js';

const BASE_RATE = Number(__ENV.BASE_RATE || 2);
const P = { normal: { rate: BASE_RATE, up: 1 }, peak: { rate: BASE_RATE * 5, up: 3 }, storm: { rate: BASE_RATE * 10, up: 8 } };
const profile = __ENV.PROFILE || 'normal';
const cfg = P[profile];
const duration = __ENV.DURATION || '60s';
const storm = profile === 'storm';

export const options = {
  insecureSkipTLSVerify: true,
  scenarios: {
    ingest: {
      executor: 'constant-arrival-rate', exec: 'ingest', rate: cfg.rate, timeUnit: '1s', duration,
      preAllocatedVUs: cfg.rate, maxVUs: cfg.rate * 6,
    },
    uploads: {
      executor: 'constant-arrival-rate', exec: 'uploads', rate: cfg.up, timeUnit: '1s', duration,
      preAllocatedVUs: Math.max(5, cfg.up), maxVUs: Math.max(10, cfg.up * 4),
    },
  },
  thresholds: {
    'http_req_duration{kind:ingest}': ['p(95)<250'],       // METER_READING SLO: 0.25 s
    'ingest_errors': ['rate<0.01'],
    // Under storm, uploads may be rejected (bulkhead 503); otherwise they must succeed.
    'upload_errors': [storm ? 'rate<1' : 'rate<0.01'],
    'http_req_duration{kind:upload}': ['p(95)<5000'],
  },
};

export function setup() { return login(); }
export function ingest(data) { ingestOne(data, exec.scenario.iterationInTest); }
export function uploads(data) { uploadOutage(data, 2048 + (exec.scenario.iterationInTest % 8) * 4096); }
export function handleSummary(data) { return summary(profile, data); }
