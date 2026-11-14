# FileGrid frontend

React + TypeScript + Vite, one MUI theme, React Router, TanStack Query, MapLibre/OpenFreeMap, and a framework-free resumable upload engine. Exact dependency versions and lockfile are included. Node 22+.

## Run

```sh
cd frontend
npm ci
npm run gen
# Choose a mode in .env.local; use .env.example as a reference.
VITE_API_MODE=mock npm run dev
```

Mock credentials: **operator/operator** or **manager/manager**. The role comes from the HTTP login response, never a role selected by the user. Mock login and the workspace visibly display **MOCK DATA**.

```sh
VITE_API_MODE=api npm run dev
```

API mode is the default when VITE_API_MODE is absent. It calls the actual backend and never falls back to mocks or LocalDemoSource. Unknown mode values fail at startup. Set VITE_API_BASE_URL (default `/api/v1`) for a different API URL. During development, the `/api` Vite proxy points to API_PROXY_TARGET (default `http://127.0.0.1:8080`), preserving same-origin cookies. A production server must provide that reverse proxy or a credentialed CORS configuration. `vite preview` does not provide the development API proxy.

Mock mode requires VITE_API_BASE_URL=/api/v1 and waits for MSW registration before rendering. If registration fails, startup fails visibly. On switching to API mode, a leftover MSW worker is deactivated and unregistered. Unimplemented API mock operations return an explicit 501; unrelated requests such as map tiles remain ordinary network traffic.

```sh
npm run gen
npm run typecheck
npm run lint
npm run vitest
npm run build
# Optional static mock artifact:
VITE_API_MODE=mock npm run build
```

The build mode is selected at build time. Serve mock builds over localhost or HTTPS so browsers permit service workers. `npm run mock:init` refreshes the checked-in public/mockServiceWorker.js from the pinned MSW package after an intentional MSW upgrade.

## Contract and generated client

`../contracts/openapi.yaml` and `../contracts/examples/` are read-only copies of the supplied input; the contract is not patched to fit the frontend. JSON attachments had shifted filenames; their original bytes were copied under the canonical names referenced by the contract. The regions example was not supplied. See [CONTRACT_ISSUES.md](CONTRACT_ISSUES.md) for exact provenance, missing input, backend blockers, and all mapping decisions.

`npm run gen` runs pinned @hey-api/openapi-ts with openapi-ts.config.ts and writes the SDK, types, and bundled fetch runtime to **src/api/gen/**. Do not edit generated files. Regenerate when the upstream contract changes; no generated DTOs escape src/data/ into view components.

## Architecture

- Components use hooks in src/data/. Query hooks call DataSource in src/data/source.ts; components never call fetch.
- ApiSource in src/data/api-source.ts calls generated SDK functions for auth, regions, all map layers, assets, files/verification, cases/checklists/reference types, issue mutations, and upload operations. ApiConnection configures `credentials: include`, normalizes the error envelope and Retry-After, and retains CSRF in memory. ApiUploadTransport sends raw Blob parts and forwards AbortSignal, X-Part-SHA256, and X-CSRF-Token.
- src/data/api-mapping.ts keeps UI models independent of generated types. It validates required display fields and strips unknown map properties. Missing issue versions stay null and disable status changes. Missing due dates stay null and display “No due date”. File actual hashes come from the verification endpoint, not stored sha256 metadata.
- src/mocks/handlers.ts intercepts HTTP with MSW and serves the supplied examples. Explicit supplemental mock records link examples where no fixture was supplied. API and mock modes use the exact same ApiSource and SDK. No LocalDemoSource is involved in mock mode.
- LocalDemoSource remains in src/data/demo.ts for isolated demos and existing tests. Its DEMO DATA banner remains distinct from MOCK DATA. It is not an automatic fallback or environment mode.
- src/upload/engine.ts has no React dependency. It takes transport, worker hashing, storage, clock, randomness and sleep dependencies. It uses three concurrent 1-based parts, incremental SHA-256, bounded retries with jitter/Retry-After, and pause/resume/cancel.

## Upload and mock behavior

Files are hashed incrementally in a dedicated hash-wasm Web Worker. Each part has a SHA-256 header and the final file checksum is sent at completion. Route changes pause transfers. After reload, reselect the original file: its name, size, lastModified and first-1-MB checksum must match, then GET status determines the missing parts to send.

Resume metadata is stored in localStorage under a namespace containing source mode, API URL and username. Old demo IDs are never resumed against a live backend. File payloads are not put in localStorage. In mock mode, IndexedDB is the fake server disk; it persists sessions and Blob parts across reloads and simulates 20% transient part failures, including lost acknowledgements. Verification moves uploads from VERIFYING to READY; the retained local demo also supports a corruption toggle. The fake server and engine fault tests cover corruption.

The API upload contract does not accept the existing UI-only region/simulation metadata. ApiUploadTransport omits the optional metadata rather than manufacturing required asset/case/timestamp fields. Mock uploads without asset metadata use the supplied file example's region. See CONTRACT_ISSUES.md before production ingestion.

Creation is not automatically retried because no create idempotency key is specified. Completion retries rely on idempotence; the contract needs to guarantee this or expose a recoverable completed file ID. Zero-byte uploads use zero parts. These protocol questions are documented rather than silently changing the supplied schema.

## Administration

Managers can open Admin to inspect every effective category policy, reload the server policy configuration, inspect/start/stop the smart-meter simulator, and backfill a local-time range with spike/zero/gap profiles. Simulator status, paginated scenario history, and recent alerts refresh every 10 seconds while the page is active. Operators cannot mount the page or request its data through the UI; MSW also enforces manager permissions on `/admin/*` and CSRF on all mutations.

The implementation uses DataSource hooks and generated SDK operations in both API and mock modes. LocalDemoSource retains independent in-memory controls. MSW records follow the contract schemas and persist simulator state/history in IndexedDB; they do not run an actual meter generator. Backfill anomaly names are sent as the schema's free-form `profile` field. These assumptions are detailed in CONTRACT_ISSUES.md.

## Known live integration blockers

- The auth contract requires CSRF for mutations but defines no token delivery. The adapter and MSW provisionally use an **X-CSRF-Token response header** on login/me. A real response without it allows reads but mutations fail explicitly. Confirm this extension or update the upstream contract.
- The supplied issue map feature has no optimistic-lock version and no issue GET exists. The issue is visible but cannot safely be changed until the API supplies a version.
- Region bounds, map feature properties, statistics, category-specific upload metadata, and some case fields need clarification. Correctness-preserving mappings and limitations are listed in CONTRACT_ISSUES.md. Local aggregation exhausts pages before filtering/sorting; large production datasets need server search/order and a typed summary endpoint.

Verification covers engine faults, IndexedDB durability, the generated HTTP client against MSW, error/CSRF/role/version behavior, and UI interaction tests. Real browser WebGL/service-worker behavior and a live backend require separate verification.

Implementation references: [Hey API fetch client](https://heyapi.dev/docs/openapi/typescript/clients/fetch), [MSW browser setup](https://mswjs.io/guides/integrations/browser), [OpenFreeMap quick start](https://openfreemap.org/quick_start/).
