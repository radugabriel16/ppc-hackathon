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
import { AppError } from "../data/errors";
import type {
  GeographicArea,
  MapData,
  MeterMarker,
  Role,
  Session,
} from "../data/models";
import { geographicAreas } from "../data/api-mapping";
import { mockRegions } from "../mocks/fixtures";
import { pointAssetFixtures } from "./test-fixtures/point-assets";
import type { ComponentProps } from "react";
import type { ReactNode } from "react";
import { flushSync } from "react-dom";

// WebGL and remote tiles require a real browser; keep interaction tests focused
// on the source/hooks/UI contract, using the actual demo source and query cache.
vi.mock("./NetworkMap", () => ({
  NetworkMap: ({
    selectedId,
    data,
    onStation,
    station,
  }: ComponentProps<typeof import("./NetworkMap").NetworkMap>) => (
    <div
      data-testid="network-map"
      data-selected-id={selectedId}
      data-meter-ids={data.meters?.map((meter) => meter.id).join(",") ?? ""}
      data-station-id={station?.id ?? ""}
      data-asset-ids={data.assetList.map((asset) => asset.id).join(",")}
      data-highlighted-meters={
        data.meters?.filter((meter) => meter.assetId === station?.id).length ??
        0
      }
      data-issue-status={
        data.issues.features.find(
          (feature) => feature.properties?.id === "ISS-100",
        )?.properties?.status
      }
    >
      Map canvas
      {data.assetList.map((asset) => (
        <button key={asset.id} onClick={() => onStation(asset)}>
          Select station {asset.id}
        </button>
      ))}
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
          <MemoryRouter>
            <RegionProvider>{children}</RegionProvider>
          </MemoryRouter>
        </SourceContext.Provider>
      </QueryClientProvider>
    </ThemeProvider>,
  );
  return { source, cache };
}
describe("role-aware workspace and issue conflicts", () => {
  it("loads eight meters only at segment scope, highlights any linked asset without fetching again, and clears on navigation", async () => {
    const areas = geographicAreas(mockRegions);
    const segment = areas.find((area) => area.name === "Muntenia 5")!;
    const nextSegment = areas.find((area) => area.name === "Muntenia 1")!;
    const { source } = await workspace(<MapPage />, "OPERATOR", "demo", areas);
    const realMap = source.getMap.bind(source);
    const getMap = vi
      .spyOn(source, "getMap")
      .mockImplementation(
        async (region, segmentId?: string): Promise<MapData> => {
          const map = await realMap(region);
          const assets = pointAssetFixtures.filter(
            (asset) =>
              asset.region === region &&
              (!segmentId || asset.segmentId === segmentId),
          );
          return {
            ...map,
            assetList: assets,
            assets: {
              type: "FeatureCollection",
              features: assets.map((asset) => ({
                type: "Feature",
                id: asset.id,
                geometry: { type: "Point", coordinates: asset.coordinates },
                properties: {
                  id: asset.id,
                  type: asset.type,
                  name: asset.name,
                },
              })),
            },
          };
        },
      );
    const getMeters = vi.fn(
      async (_region: string, segmentId: string): Promise<MeterMarker[]> => {
        const assets = pointAssetFixtures.filter(
          (asset) => asset.segmentId === segmentId,
        );
        return Array.from({ length: 8 }, (_, index) => ({
          id: `${segmentId}-meter-${index}`,
          assetId: assets[index % assets.length].id,
          segmentId,
          code: `METER-${index}`,
          coordinates: assets[0].coordinates,
          clientType: null,
          lastReading: null,
        }));
      },
    );
    Object.assign(source, { getMapMeters: getMeters });
    const parent = areas.find((area) => area.id === segment.parentId)!;
    fireEvent.click(
      await screen.findByRole("button", {
        name: `${parent.name} · ${parent.meterCount} meters`,
      }),
    );
    await screen.findByRole("button", {
      name: `${segment.name} · ${segment.meterCount} meters`,
    });
    expect(getMeters).not.toHaveBeenCalled();
    fireEvent.click(
      screen.getByRole("button", {
        name: `${segment.name} · ${segment.meterCount} meters`,
      }),
    );
    await waitFor(() =>
      expect(
        screen
          .getByTestId("network-map")
          .getAttribute("data-meter-ids")!
          .split(","),
      ).toHaveLength(8),
    );
    expect(getMeters).toHaveBeenCalledExactlyOnceWith("MUNTENIA", segment.id);
    const firstAssets = pointAssetFixtures.filter(
      (asset) => asset.segmentId === segment.id,
    );
    await screen.findByRole("button", {
      name: `Select station ${firstAssets[0].id}`,
    });
    const mapCalls = getMap.mock.calls.length;
    const assetIds = screen
      .getByTestId("network-map")
      .getAttribute("data-asset-ids");
    for (const type of ["SUBSTATION", "TRANSFORMER", "LINE_SEGMENT"]) {
      const asset = firstAssets.find((asset) => asset.type === type)!;
      fireEvent.click(
        screen.getByRole("button", { name: `Select station ${asset.id}` }),
      );
      expect(
        screen.getByTestId("network-map").getAttribute("data-station-id"),
      ).toBe(asset.id);
      expect(
        Number(
          screen
            .getByTestId("network-map")
            .getAttribute("data-highlighted-meters"),
        ),
      ).toBeGreaterThan(0);
      expect(
        screen
          .getByTestId("network-map")
          .getAttribute("data-meter-ids")!
          .split(","),
      ).toHaveLength(8);
      expect(
        screen.getByTestId("network-map").getAttribute("data-asset-ids"),
      ).toBe(assetIds);
    }
    expect(getMeters).toHaveBeenCalledTimes(1);
    expect(getMap).toHaveBeenCalledTimes(mapCalls);
    // Native events can flush capture updates before the page handles bubbling.
    const flushCapture = () => flushSync(() => {});
    document.addEventListener("keydown", flushCapture, true);
    try {
      fireEvent.keyDown(screen.getByTestId("network-map"), { key: "Escape" });
    } finally {
      document.removeEventListener("keydown", flushCapture, true);
    }
    expect(
      screen.getByTestId("network-map").getAttribute("data-selected-id"),
    ).toBe(segment.id);
    expect(
      screen.getByTestId("network-map").getAttribute("data-station-id"),
    ).toBe("");
    expect(
      screen
        .getByTestId("network-map")
        .getAttribute("data-meter-ids")!
        .split(","),
    ).toHaveLength(8);
    fireEvent.click(
      screen.getByRole("button", {
        name: `Select station ${firstAssets[0].id}`,
      }),
    );
    fireEvent.click(
      screen.getByRole("button", { name: /ISS-100.*Thermal anomaly/ }),
    );
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
    await waitFor(() =>
      expect(
        screen.getByTestId("network-map").getAttribute("data-station-id"),
      ).toBe(""),
    );
    expect(
      screen
        .getByTestId("network-map")
        .getAttribute("data-meter-ids")!
        .split(","),
    ).toHaveLength(8);
    let finish: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      finish = resolve;
    });
    getMeters.mockImplementationOnce(async () => {
      await gate;
      return Array.from({ length: 8 }, (_, index) => ({
        id: `next-meter-${index}`,
        assetId: pointAssetFixtures.find(
          (asset) => asset.segmentId === nextSegment.id,
        )!.id,
        segmentId: nextSegment.id,
        code: `M2-${index}`,
        coordinates: [26, 44],
        clientType: null,
        lastReading: null,
      }));
    });
    fireEvent.click(
      screen.getByRole("button", {
        name: `${nextSegment.name} · ${nextSegment.meterCount} meters`,
      }),
    );
    await waitFor(() => expect(getMeters).toHaveBeenCalledTimes(2));
    expect(
      screen.getByTestId("network-map").getAttribute("data-meter-ids"),
    ).toBe("");
    finish();
    await waitFor(() =>
      expect(
        screen
          .getByTestId("network-map")
          .getAttribute("data-meter-ids")!
          .split(","),
      ).toHaveLength(8),
    );
    fireEvent.click(screen.getByRole("button", { name: "Romania" }));
    await waitFor(() =>
      expect(
        screen.getByTestId("network-map").getAttribute("data-meter-ids"),
      ).toBe(""),
    );
  });
  it("optimistically updates map feature status after Take with the dialog closed, then refetches", async () => {
    const { source, cache } = await workspace(<MapPage />);
    await screen.findByRole("button", { name: /ISS-100.*Thermal anomaly/ });
    const perform = source.updateIssue.bind(source);
    const initial = cache.getQueryData<MapData>(["map", "ROMANIA"])!;
    cache.setQueryDefaults(["map", "MUNTENIA"], { gcTime: Infinity });
    cache.setQueryDefaults(["issues"], { gcTime: Infinity });
    cache.setQueryData(["map", "MUNTENIA"], initial);
    cache.setQueryData(["issues", { page: 0 }], {
      items: initial.issueList,
      page: 0,
      size: 20,
      totalPages: 1,
      totalElements: initial.issueList.length,
    });
    let finish: () => void = () => {};
    const gate = new Promise<void>((resolve) => {
      finish = resolve;
    });
    vi.spyOn(source, "updateIssue").mockImplementation(async (input) => {
      await gate;
      return perform(input);
    });
    const refetch = vi.spyOn(source, "getMap");
    fireEvent.click(
      screen.getByRole("button", { name: /ISS-100.*Thermal anomaly/ }),
    );
    fireEvent.click(screen.getByRole("button", { name: "Take issue" }));
    await waitFor(() =>
      expect(
        screen.getByTestId("network-map").getAttribute("data-issue-status"),
      ).toBe("IN_PROGRESS"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(
      cache
        .getQueryData<MapData>(["map", "ROMANIA"])
        ?.issues.features.find(
          (feature) => feature.properties?.id === "ISS-100",
        )?.properties?.status,
    ).toBe("IN_PROGRESS");
    expect(refetch).not.toHaveBeenCalled();
    expect(
      cache
        .getQueryData<MapData>(["map", "MUNTENIA"])
        ?.issues.features.find(
          (feature) => feature.properties?.id === "ISS-100",
        )?.properties?.status,
    ).toBe("IN_PROGRESS");
    expect(
      cache
        .getQueryData<{
          items: { id: string; status: string }[];
        }>(["issues", { page: 0 }])
        ?.items.find((issue) => issue.id === "ISS-100")?.status,
    ).toBe("IN_PROGRESS");
    finish();
    await waitFor(() => expect(refetch).toHaveBeenCalled());
    await waitFor(() =>
      expect(
        cache
          .getQueryData<MapData>(["map", "ROMANIA"])
          ?.issueList.find((issue) => issue.id === "ISS-100")?.version,
      ).toBe(2),
    );
    expect(
      screen.getByTestId("network-map").getAttribute("data-issue-status"),
    ).toBe("IN_PROGRESS");
    expect(screen.queryByRole("dialog")).toBeNull();
  });
  it("rolls back a failed Take and surfaces its error even after closing the popup", async () => {
    const { source } = await workspace(<MapPage />);
    const button = await screen.findByRole("button", {
      name: /ISS-100.*Thermal anomaly/,
    });
    let fail: (error: Error) => void = () => {};
    vi.spyOn(source, "updateIssue").mockImplementation(
      () =>
        new Promise((_resolve, reject) => {
          fail = reject;
        }),
    );
    fireEvent.click(button);
    fireEvent.click(screen.getByRole("button", { name: "Take issue" }));
    await waitFor(() =>
      expect(
        screen.getByTestId("network-map").getAttribute("data-issue-status"),
      ).toBe("IN_PROGRESS"),
    );
    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    fail(
      new AppError(500, {
        code: "UPDATE_FAILED",
        message: "Taking issue failed",
        requestId: "failed-take",
      }),
    );
    await screen.findByText(/Taking issue failed.*failed-take/);
    await waitFor(() =>
      expect(
        screen.getByTestId("network-map").getAttribute("data-issue-status"),
      ).toBe("OPEN"),
    );
    expect(screen.queryByRole("dialog")).toBeNull();
  });
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
