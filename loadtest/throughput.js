// Closed-model ingest throughput (constant VUs, no think time). Used by the scale_up demo.
import exec from 'k6/execution';
import { login, ingestOne, summary } from './lib.js';

export const options = {
  insecureSkipTLSVerify: true,
  scenarios: { t: { executor: 'constant-vus', vus: Number(__ENV.VUS || 40), duration: __ENV.DURATION || '30s' } },
  thresholds: { ingest_errors: ['rate<0.01'], 'http_req_duration{kind:ingest}': ['max>=0'] },
};
export function setup() { return login(); }
export default function (data) { ingestOne(data, exec.scenario.iterationInTest); }
export function handleSummary(data) { return summary(__ENV.NAME || 'throughput', data); }
