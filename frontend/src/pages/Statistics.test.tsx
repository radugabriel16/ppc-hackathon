// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ThemeProvider } from "@mui/material";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import type { EChartsOption } from "echarts";
import { SourceContext } from "../data/context";
import { LocalDemoSource } from "../data/demo";
import type { DataSource } from "../data/source";
import { RegionProvider } from "../data/region";
import { useRegion } from "../data/region-context";
import { REGIONS, type Region } from "../data/models";
import { AppError } from "../data/errors";
import { createStatsFixtures } from "../mocks/stats";
import * as mapping from "../data/stats-mapping";
import { theme } from "../theme";
import { StatisticsPage } from "./Overview";

// Exercise hook/cache/filter behavior here. Separate tests render the actual
// ECharts SVG engine; WebGL and tile loading require a browser.
vi.mock("../components/StatisticsChart", () => ({
  StatisticsChart: ({
    label,
    option,
  }: {
    label: string;
    option: EChartsOption;
  }) => (
    <div role="img" aria-label={label}>
      {JSON.stringify(option.series)}
    </div>
  ),
}));
vi.mock("../components/HotspotMap", () => ({
  HotspotMap: ({ region, mode }: { region: Region; mode: string }) => (
    <div data-testid="hotspot-map" data-region={region} data-mode={mode}>
      Hotspot canvas
    </div>
  ),
}));
afterEach(() => cleanup());
const fixtures = createStatsFixtures(Date.parse("2026-11-14T12:00:00Z"));
function RegionControl() {
  const { region, setRegion } = useRegion();
  return (
    <select
      aria-label="Test region"
      value={region}
      onChange={(event) => setRegion(event.target.value as Region)}
    >
      {REGIONS.map((region) => (
        <option key={region}>{region}</option>
      ))}
    </select>
  );
}
function workspace(withData = true, mode: "api" | "mock" = "api") {
  const source: DataSource = new LocalDemoSource();
  Object.defineProperty(source, "kind", { value: mode });
  if (withData) {
    vi.spyOn(source, "getStorageBenchmark").mockResolvedValue(
      mapping.storageBenchmark(fixtures.benchmark),
    );
    vi.spyOn(source, "getStorageRecommendations").mockResolvedValue(
      mapping.storageRecommendations(fixtures.recommendations),
    );
    vi.spyOn(source, "getMeterConsumption").mockImplementation(async (region) =>
      mapping.meterConsumption(fixtures.meters, region),
    );
    vi.spyOn(source, "getOutageHotspots").mockImplementation(async (region) =>
      mapping.outageHotspots(fixtures.hotspots, region),
    );
    vi.spyOn(source, "getForecast").mockImplementation(async (region) =>
      mapping.forecast(fixtures.forecast, region),
    );
  }
  const cache = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  const show = () =>
    render(
      <ThemeProvider theme={theme}>
        <QueryClientProvider client={cache}>
          <SourceContext.Provider value={source}>
            <RegionProvider>
              <MemoryRouter>
                <RegionControl />
                <StatisticsPage />
              </MemoryRouter>
            </RegionProvider>
          </SourceContext.Provider>
        </QueryClientProvider>
      </ThemeProvider>,
    );
  return { source, cache, show };
}
describe("statistics workspace", () => {
  it("shows all matrix metrics, switches normal/peak and selects a heatmap metric", async () => {
    const { show } = workspace();
    show();
    const normal = await screen.findByRole("table", {
      name: "Normal storage benchmark matrix",
    });
    expect(within(normal).getAllByText(/p50.*p95.*p99/)).toHaveLength(12);
    expect(within(normal).getAllByText(/MiB\/s.*% errors/)).toHaveLength(12);
    fireEvent.click(screen.getByRole("button", { name: "Peak" }));
    const peak = screen.getByRole("table", {
      name: "Peak storage benchmark matrix",
    });
    expect(
      within(peak).getByText(/p50 26.6 \/ p95 47.88 \/ p99 82.46 ms/),
    ).toBeTruthy();
    fireEvent.change(screen.getByLabelText("Heatmap metric"), {
      target: { value: "throughputMiBps" },
    });
    expect(
      screen.getByRole("img", {
        name: "Peak load: Throughput (MiB/s) by category and storage",
      }),
    ).toBeTruthy();
    expect(
      await screen.findByText(fixtures.recommendations.items[0].reason),
    ).toBeTruthy();
  });
  it("changes meter and region, preserves gap labels, and toggles hotspot layers", async () => {
    const { source, show } = workspace();
    show();
    await screen.findByRole("img", {
      name: /Consumption for Muntenia meter 1/,
    });
    expect(
      screen.getByText(
        "15-minute intervals · 2 anomalies · 3 missing readings",
      ),
    ).toBeTruthy();
    expect(
      within(
        screen.getByRole("table", { name: "Meter readings", hidden: true }),
      ).getAllByText("Missing"),
    ).toHaveLength(3);
    fireEvent.change(screen.getByLabelText("Meter"), {
      target: { value: "MUN-M2" },
    });
    expect(
      screen.getByRole("img", { name: /Consumption for Muntenia meter 2/ }),
    ).toBeTruthy();
    expect(screen.getByTestId("hotspot-map").getAttribute("data-mode")).toBe(
      "heat",
    );
    fireEvent.click(screen.getByRole("button", { name: "Clusters" }));
    expect(screen.getByTestId("hotspot-map").getAttribute("data-mode")).toBe(
      "clusters",
    );
    fireEvent.change(screen.getByLabelText("Test region"), {
      target: { value: "BANAT" },
    });
    await screen.findByRole("img", { name: /Consumption for Banat meter 1/ });
    await screen.findByRole("img", {
      name: /forecast for Banat, three UTC days/,
    });
    await waitFor(() =>
      expect(
        screen.getByTestId("hotspot-map").getAttribute("data-region"),
      ).toBe("BANAT"),
    );
    expect(source.getMeterConsumption).toHaveBeenLastCalledWith("BANAT");
    expect(source.getOutageHotspots).toHaveBeenLastCalledWith("BANAT");
    expect(source.getForecast).toHaveBeenLastCalledWith("BANAT");
  });
  it("shows no data yet for all empty API endpoints without charts or synthesized metrics", async () => {
    const { source, show } = workspace(false);
    const legacy = vi.spyOn(source, "getStatistics");
    show();
    await waitFor(() =>
      expect(screen.getAllByText("No data yet")).toHaveLength(5),
    );
    expect(screen.queryAllByRole("img")).toHaveLength(0);
    expect(screen.queryByTestId("hotspot-map")).toBeNull();
    expect(screen.queryByText("MOCK FORECAST")).toBeNull();
    expect(legacy).not.toHaveBeenCalled();
  });
  it("keeps errors local to their endpoint and retries without displaying fallback values", async () => {
    const { source, show } = workspace();
    vi.mocked(source.getForecast)
      .mockRejectedValueOnce(
        new AppError(404, {
          code: "NOT_FOUND",
          message: "Forecast endpoint unavailable",
          requestId: "forecast-404",
        }),
      )
      .mockResolvedValueOnce([]);
    show();
    await screen.findByText(
      "Forecast endpoint unavailable · Request ID: forecast-404",
    );
    expect(
      await screen.findByRole("table", {
        name: "Normal storage benchmark matrix",
      }),
    ).toBeTruthy();
    expect(
      screen.queryByRole("img", { name: /Regional consumption forecast/ }),
    ).toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("No data yet");
    expect(
      screen.queryByRole("img", { name: /Regional consumption forecast/ }),
    ).toBeNull();
  });
  it("labels the synthetic forecast and displays three UTC days without uncertainty claims", async () => {
    const { show } = workspace(true, "mock");
    show();
    expect(screen.getByText("MOCK FORECAST")).toBeTruthy();
    const values = await screen.findByRole("table", {
      name: "Forecast values",
      hidden: true,
    });
    expect(within(values).getAllByRole("row", { hidden: true })).toHaveLength(
      4,
    );
    expect(within(values).getByText("2026-11-14 UTC")).toBeTruthy();
    expect(within(values).getByText("Status")).toBeTruthy();
    expect(screen.queryByText("80% lower")).toBeNull();
  });

  it("shows baseline provenance and missing totals instead of plotting zero", async () => {
    const { source, show } = workspace();
    const points = mapping.forecast(fixtures.forecast, "MUNTENIA");
    points[0] = {
      ...points[0],
      estimate: null,
      status: "INSUFFICIENT_DATA",
      fallbackUsed: true,
    };
    vi.mocked(source.getForecast).mockResolvedValue(points);
    show();
    await screen.findByText(/BASELINE FALLBACK/);
    expect(screen.getByText(/As of.*mock-hgb_smooth/)).toBeTruthy();
    expect(
      within(
        screen.getByRole("table", { name: "Forecast values", hidden: true }),
      ).getByText("Insufficient data"),
    ).toBeTruthy();
    expect(
      screen.getByRole("img", { name: /Regional consumption forecast/ })
        .textContent,
    ).toContain("null");
  });
});
