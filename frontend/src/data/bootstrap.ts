import { ApiSource } from "./api-source";

export interface ApiEnvironment {
  VITE_API_MODE?: string;
  VITE_API_BASE_URL?: string;
}
export function apiConfiguration(env: ApiEnvironment): {
  mode: "mock" | "api";
  baseUrl: string;
} {
  const mode = env.VITE_API_MODE ?? "api";
  if (mode !== "mock" && mode !== "api")
    throw new Error(`Invalid VITE_API_MODE "${mode}". Use mock or api.`);
  const baseUrl = env.VITE_API_BASE_URL ?? "/api/v1";
  if (mode === "mock" && baseUrl !== "/api/v1")
    throw new Error(
      "Mock mode requires VITE_API_BASE_URL=/api/v1; no requests will be sent to a real API.",
    );
  return { mode, baseUrl };
}
export async function prepareSource(env: ApiEnvironment) {
  const config = apiConfiguration(env);
  if (import.meta.env.VITE_API_MODE !== "api" && config.mode === "mock") {
    const { startMockWorker } = await import("../mocks/browser");
    await startMockWorker(); // A worker failure is fatal, never a fallback to demo/live data.
  } else if (typeof navigator !== "undefined" && "serviceWorker" in navigator) {
    if (
      navigator.serviceWorker.controller?.scriptURL.endsWith(
        "/mockServiceWorker.js",
      )
    )
      navigator.serviceWorker.controller.postMessage("MOCK_DEACTIVATE");
    for (const registration of await navigator.serviceWorker.getRegistrations()) {
      const script =
        registration.active?.scriptURL ??
        registration.waiting?.scriptURL ??
        registration.installing?.scriptURL;
      if (script?.endsWith("/mockServiceWorker.js"))
        await registration.unregister();
    }
  }
  return new ApiSource(config.baseUrl, config.mode);
}
