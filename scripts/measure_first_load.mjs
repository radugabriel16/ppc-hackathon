#!/usr/bin/env node
// Executes the unchanged UI data source, including its pagination and 8-meter batches.
import { execFileSync } from "node:child_process";
import { mkdtemp, rm } from "node:fs/promises";
import { tmpdir } from "node:os";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath, pathToFileURL } from "node:url";
import { performance } from "node:perf_hooks";
import { build } from "../frontend/node_modules/esbuild/lib/main.js";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const config = JSON.parse(execFileSync("docker", [
  "compose", "exec", "-T", "api-files", "python", "-c",
  `import json
from app.core.settings import get_settings
s=get_settings()
print(json.dumps({"origin":str(s.app_origin).rstrip("/"),"password":s.storage_secret("operator_password")}))`,
], { cwd: root, encoding: "utf8" }));
process.env.NODE_TLS_REJECT_UNAUTHORIZED = "0";
globalThis.location = { origin: config.origin };
const cookies = new Map();
globalThis.document = { get cookie() {
  return [...cookies].map(([key, value]) => `${key}=${value}`).join("; ");
} };
const originalFetch = globalThis.fetch;
const requests = [];
let currentPage = "login";
globalThis.fetch = async (input, init) => {
  const request = new Request(input, init);
  request.headers.set("Cookie", document.cookie);
  if (!["GET", "HEAD"].includes(request.method)) request.headers.set("Origin", config.origin);
  const page = currentPage;
  const start = performance.now();
  const response = await originalFetch(request);
  const bytes = (await response.clone().arrayBuffer()).byteLength;
  const durationMs = performance.now() - start;
  for (const cookie of response.headers.getSetCookie()) {
    const [key, ...value] = cookie.split(";")[0].split("=");
    if (value.join("=")) cookies.set(key, value.join("=")); else cookies.delete(key);
  }
  if (page !== "login") requests.push({
    page, path: new URL(request.url).pathname + new URL(request.url).search,
    status: response.status, durationMs: Math.round(durationMs * 100) / 100, bytes,
  });
  return response;
};

const temporary = await mkdtemp(join(tmpdir(), "filegrid-first-load-"));
try {
  const output = join(temporary, "source.mjs");
  await build({
    absWorkingDir: root, entryPoints: ["frontend/src/data/api-source.ts"],
    bundle: true, platform: "node", format: "esm", outfile: output, logLevel: "silent",
  });
  const { ApiSource } = await import(pathToFileURL(output).href);
  const regions = ["MUNTENIA", "BANAT", "DOBROGEA"];
  const pages = {};
  for (const page of ["map", "overview", "files", "cases", "issues"]) {
    currentPage = "login";
    const source = new ApiSource(config.origin + "/api/v1");
    await source.login({ name: "operator", password: config.password });
    currentPage = page;
    const start = performance.now();
    const tasks = [source.getSession()];
    if (page === "map") tasks.push(
      source.getGeography(), source.getForecastThresholds(),
      ...regions.flatMap((region) => [source.getMap(region), source.getMapMeters(region)]),
    );
    if (page === "overview") tasks.push(
      source.getStorageBenchmark(), source.getStorageRecommendations(), source.getForecastThresholds(),
      ...regions.flatMap((region) => [
        source.getMeterConsumption(region), source.getOutageHotspots(region), source.getForecast(region),
      ]),
    );
    if (page === "files") tasks.push(source.getFiles({
      region: "MUNTENIA", search: "", page: 0, size: 10,
    }));
    if (page === "cases") tasks.push(source.getCases({
      search: "", page: 0, size: 6, missingOnly: true,
    }));
    if (page === "issues") tasks.push(source.getGeography(), source.getIssues({ page: 0, size: 20 }));
    await Promise.all(tasks);
    pages[page] = {
      dataReadyMs: Math.round((performance.now() - start) * 100) / 100,
      requests: requests.filter((request) => request.page === page).length,
    };
  }
  const durations = requests.map((r) => r.durationMs).sort((a, b) => a-b);
  console.log(JSON.stringify({
    measurement: "Unchanged ApiSource first-load requests over HTTPS; excludes browser rendering",
    pages, requestCount: requests.length,
    p50Ms: durations[Math.floor(durations.length * 0.5)],
    p95Ms: durations[Math.floor(durations.length * 0.95)],
    maximumMs: durations.at(-1),
    targetMet: requests.every((r) => r.status === 200 && r.durationMs < 300)
      && Object.values(pages).every((page) => page.dataReadyMs < 2000),
    requests,
  }, null, 2));
} finally {
  await rm(temporary, { recursive: true, force: true });
}
