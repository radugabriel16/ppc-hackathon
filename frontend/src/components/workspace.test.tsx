// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "@mui/material";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { SourceContext } from "../data/context";
import { LocalDemoSource } from "../data/demo";
import { RegionProvider } from "../data/region";
import { Shell, ManagerOnly } from "./Shell";
import { Authenticated } from "./Authenticated";
import { MapPage } from "../pages/Map";
import { theme } from "../theme";
import type { GeographicArea, MapData, Role, Session } from "../data/models";
import type { GeographySelectionProps } from "./GeographyExplorer";
import type { ReactNode } from "react";

// WebGL and remote tiles require a real browser; keep interaction tests focused
// on the source/hooks/UI contract, using the actual demo source and query cache.
vi.mock("./NetworkMap", () => ({
  NetworkMap: ({ selectedId }: GeographySelectionProps) => (
    <div data-testid="network-map" data-selected-id={selectedId}>
      Map canvas
    </div>
  ),
}));
afterEach(() => {
  cleanup();
  sessionStorage.clear();
});
async function workspace(
  children: ReactNode,
  role: Role = "OPERATOR",
  mode: "demo" | "mock" | "api" = "demo",
  geography?: GeographicArea[],
) {
  const source = new LocalDemoSource();
  if (geography) Object.assign(source, { getGeography: async () => geography });
  if (mode !== "demo") Object.defineProperty(source, "kind", { value: mode });
  const session: Session = await source.login({ name: "Test User", role });
  const cache = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  cache.setQueryData(["session"], session);
  render(
    <ThemeProvider theme={theme}>
      <QueryClientProvider client={cache}>
        <SourceContext.Provider value={source}>
          <RegionProvider>
            <MemoryRouter>{children}</MemoryRouter>
          </RegionProvider>
        </SourceContext.Provider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { source, cache };
}
describe("role-aware workspace and issue conflicts", () => {
  it("syncs map selection, region/subregion filters and breadcrumb back navigation", async () => {
    const parent: GeographicArea = {
      id: "banat",
      code: "BANAT",
      name: "Banat",
      region: "BANAT",
      parentId: null,
      meterCount: 6,
      geometry: {
        type: "MultiPolygon",
        coordinates: [
          [
            [
              [20, 44],
              [22, 44],
              [22, 46],
              [20, 44],
            ],
          ],
        ],
      },
    };
    const child = {
      ...parent,
      id: "banat-1",
      code: "BANAT-1",
      name: "Banat 1",
      parentId: parent.id,
    };
    const { source } = await workspace(<MapPage />, "OPERATOR", "demo", [
      parent,
      child,
    ]);
    const getMap = vi.spyOn(source, "getMap");
    fireEvent.click(
      await screen.findByRole("button", { name: "Banat · 6 meters" }),
    );
    await waitFor(() =>
      expect(getMap).toHaveBeenCalledWith("BANAT", undefined),
    );
    fireEvent.click(screen.getByRole("button", { name: "Banat 1 · 6 meters" }));
    await waitFor(() =>
      expect(getMap).toHaveBeenCalledWith("BANAT", "banat-1"),
    );
    expect(
      screen.getByTestId("network-map").getAttribute("data-selected-id"),
    ).toBe("banat-1");
    fireEvent.keyDown(
      screen.getByRole("button", { name: "Banat 1 · 6 meters" }),
      { key: "Escape" },
    );
    await waitFor(() =>
      expect(
        screen.getByTestId("network-map").getAttribute("data-selected-id"),
      ).toBe("banat"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Romania" }));
    await screen.findByRole("list", { name: "Regions" });
    expect(
      screen.getByTestId("network-map").getAttribute("data-selected-id"),
    ).toBeNull();
  });
  it("redirects mounted authenticated routes after logout and clears private cached data", async () => {
    const { cache } = await workspace(
      <Routes>
        <Route element={<Authenticated />}>
          <Route path="/" element={<Shell />} />
        </Route>
        <Route path="/login" element={<div>Signed out route</div>} />
      </Routes>,
    );
    cache.setQueryData(["files", "private"], ["cached file"]);
    fireEvent.click(screen.getByRole("button", { name: "Sign out" }));
    await screen.findByText("Signed out route");
    expect(cache.getQueryData(["session"])).toBeNull();
    expect(cache.getQueryData(["files", "private"])).toBeUndefined();
  });
  it("disables status changes when the API has not supplied an issue version", async () => {
    const { cache } = await workspace(<MapPage />);
    await screen.findByTestId("network-map");
    cache.setQueryData<MapData>(["map", "ROMANIA"], (old) => ({
      ...old!,
      issueList: old!.issueList.map((issue) => ({ ...issue, version: null })),
    }));
    fireEvent.click(
      await screen.findByRole("button", { name: /ISS-100.*Thermal anomaly/ }),
    );
    expect(
      screen
        .getByRole("button", { name: "Take issue" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(
      screen.getByText(/The API map feature has no issue version/),
    ).toBeTruthy();
  });
  it("shows MOCK DATA only in mock mode", async () => {
    await workspace(<Shell />, "OPERATOR", "mock");
    expect(screen.getByText("MOCK DATA")).toBeTruthy();
    expect(screen.queryByText("DEMO DATA")).toBeNull();
  });
  it("shows neither mock nor demo banners in api mode", async () => {
    await workspace(<Shell />, "OPERATOR", "api");
    expect(screen.queryByText("MOCK DATA")).toBeNull();
    expect(screen.queryByText("DEMO DATA")).toBeNull();
  });
  it("shows the demo banner and hides Admin from operators", async () => {
    await workspace(
      <>
        <Shell />
        <ManagerOnly>
          <span>Manager secret</span>
        </ManagerOnly>
      </>,
    );
    expect(screen.getByText("DEMO DATA")).toBeTruthy();
    expect(screen.queryByRole("link", { name: "Admin" })).toBeNull();
    expect(screen.queryByText("Manager secret")).toBeNull();
    expect(
      screen.getByText("This workspace is available to managers only."),
    ).toBeTruthy();
  });
  it("shows Admin for managers", async () => {
    await workspace(<Shell />, "MANAGER");
    expect(screen.getByRole("link", { name: "Admin" })).toBeTruthy();
  });
  it("shows the required 409 message + requestId and refetches authoritative issue version", async () => {
    const { source, cache } = await workspace(<MapPage />);
    const getMap = vi.spyOn(source, "getMap");
    const issueButton = await screen.findByRole("button", {
      name: /ISS-100.*Thermal anomaly/,
    });
    const callsBeforeConflict = getMap.mock.calls.length;
    fireEvent.click(issueButton);
    fireEvent.click(
      screen.getByRole("checkbox", { name: /Simulate another operator/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Take issue" }));
    await screen.findByText(
      /someone else already took this issue.*Request ID: demo-conflict/,
    );
    await screen.findByText(/Version 2/);
    expect(getMap.mock.calls.length).toBeGreaterThan(callsBeforeConflict);
    const map = cache.getQueryData<{
      issueList: { id: string; status: string; version: number }[];
    }>(["map", "ROMANIA"]);
    expect(map?.issueList.find((x) => x.id === "ISS-100")).toMatchObject({
      version: 2,
      status: "IN_PROGRESS",
    });
    expect(screen.queryByRole("button", { name: "Resolve issue" })).toBeNull();
  });
  it("allows managers to resolve an issue with its version", async () => {
    const { source } = await workspace(<MapPage />, "MANAGER");
    const update = vi.spyOn(source, "updateIssue");
    fireEvent.click(
      await screen.findByRole("button", { name: /ISS-100.*Thermal anomaly/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Resolve issue" }));
    await waitFor(() =>
      expect(update).toHaveBeenCalledWith({
        id: "ISS-100",
        status: "RESOLVED",
        version: 1,
        simulateConflict: false,
      }),
    );
    await screen.findByText("Issue updated.");
  });
  it("creates issues and sends video offsets through the data hook", async () => {
    const { source } = await workspace(<MapPage />);
    const create = vi.spyOn(source, "createIssue");
    await screen.findByTestId("network-map");
    fireEvent.click(screen.getByRole("button", { name: "Create issue" }));
    fireEvent.change(screen.getByLabelText(/Description/), {
      target: { value: "Thermal damage on connector" },
    });
    fireEvent.change(screen.getByLabelText("Video ID (optional)"), {
      target: { value: "drone-123" },
    });
    fireEvent.change(screen.getByLabelText("Offset in seconds"), {
      target: { value: "12.5" },
    });
    const buttons = screen.getAllByRole("button", { name: "Create issue" });
    fireEvent.click(buttons.at(-1)!);
    await screen.findByText(
      "Issue created. The network map has been refreshed.",
    );
    expect(create).toHaveBeenCalledWith(
      expect.objectContaining({
        description: "Thermal damage on connector",
        videoId: "drone-123",
        offsetSeconds: 12.5,
      }),
    );
  });
});
