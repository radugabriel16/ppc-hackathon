import { describe, expect, it, vi } from "vitest";
import { apiConfiguration, prepareSource } from "./bootstrap";

describe("API mode selection", () => {
  it("defaults to api and rejects unknown modes or a remote mock target", () => {
    expect(apiConfiguration({})).toEqual({ mode: "api", baseUrl: "/api/v1" });
    expect(apiConfiguration({ VITE_API_MODE: "mock" }).mode).toBe("mock");
    expect(() => apiConfiguration({ VITE_API_MODE: "demo" })).toThrow(
      "Invalid VITE_API_MODE",
    );
    expect(() =>
      apiConfiguration({
        VITE_API_MODE: "mock",
        VITE_API_BASE_URL: "https://real.example/api/v1",
      }),
    ).toThrow("Mock mode requires");
  });
  it("deactivates only stale MSW workers in api mode without starting mocks", async () => {
    const unregister = vi.fn(async () => true);
    const other = vi.fn(async () => true);
    const postMessage = vi.fn();
    vi.stubGlobal("navigator", {
      serviceWorker: {
        controller: {
          scriptURL: "http://127.0.0.1/mockServiceWorker.js",
          postMessage,
        },
        getRegistrations: async () => [
          {
            active: { scriptURL: "http://127.0.0.1/mockServiceWorker.js" },
            unregister,
          },
          {
            active: { scriptURL: "http://127.0.0.1/other-worker.js" },
            unregister: other,
          },
        ],
      },
    });
    expect((await prepareSource({ VITE_API_MODE: "api" })).kind).toBe("api");
    expect(postMessage).toHaveBeenCalledWith("MOCK_DEACTIVATE");
    expect(unregister).toHaveBeenCalledOnce();
    expect(other).not.toHaveBeenCalled();
  });
});
