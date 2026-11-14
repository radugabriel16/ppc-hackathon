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
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { LocalDemoSource } from "../data/demo";
import { SourceContext } from "../data/context";
import type { DataSource } from "../data/source";
import type { ForecastRun, GeographicArea, Role } from "../data/models";
import { RegionProvider } from "../data/region";
import { ForecastPanel } from "./ForecastPanel";
import type { SegmentForecastDay } from "../api/gen/types.gen";

vi.mock("./StatisticsChart", () => ({
  StatisticsChart: ({ label }: { label: string }) => (
    <div role="img" aria-label={label} />
  ),
}));
afterEach(cleanup);
const geography: GeographicArea[] = [
  {
    id: "region-1",
    code: "BANAT",
    name: "Banat",
    region: "BANAT",
    parentId: null,
    geometry: { type: "MultiPolygon", coordinates: [] },
    meterCount: 8,
  },
  {
    id: "segment-1",
    code: "BANAT-1",
    name: "Banat 1",
    region: "BANAT",
    parentId: "region-1",
    geometry: { type: "MultiPolygon", coordinates: [] },
    meterCount: 8,
  },
];
const forecastDay = (horizon: number): SegmentForecastDay => ({
  date: `2026-11-${14 + horizon}`,
  horizon,
  predictedEnergyKwh: horizon === 3 ? null : 120,
  referenceEnergyKwh: 100,
  changeVsReferencePct: horizon === 3 ? null : 20,
  status: horizon === 3 ? "INSUFFICIENT_DATA" : "READY",
  fallbackUsed: horizon === 1,
  bridged: true,
  thresholdKwh: 100,
  excessKwh: horizon === 3 ? null : 20,
  expectedMeters: 8,
  eligibleMeters: horizon === 3 ? 7 : 8,
});
const run: ForecastRun = {
  id: "run-1",
  scope: "segment",
  regionId: "region-1",
  segmentId: "segment-1",
  status: "COMPLETED",
  segments: [
    {
      segmentId: "segment-1",
      segment: "Banat 1",
      region: "BANAT",
      regionId: "region-1",
      schemaVersion: "1",
      predictionKind: "DAILY_ENERGY_FORECAST",
      units: "kWh/day",
      dataSource: "CATALOG_METER_READINGS",
      origin: "2026-11-15T00:00:00Z",
      asOf: "2026-11-14T20:00:00Z",
      lastCompletedDay: "2026-11-13",
      horizonDays: 3,
      method: "model",
      modelTrainingCutoff: "2026-05-14T00:00:00Z",
      modelVersion: "v2",
      uncertaintyIntervalsAvailable: false,
      predictsOutageProbability: false,
      fallbackUsed: true,
      bridged: true,
      generatedAt: "2026-11-14T20:00:00Z",
      thresholdKwh: 100,
      forecasts: [forecastDay(1), forecastDay(2), forecastDay(3)],
    },
  ],
  createdIssues: [
    {
      id: "issue-1",
      type: "ML_FORECAST",
      segmentId: "segment-1",
      title: "Banat 1 expected to exceed on 2026-11-15 by 20 kWh",
    },
  ],
};

function workspace(
  search = "?region=BANAT&segment=segment-1",
  role: Role = "OPERATOR",
) {
  const source: DataSource = new LocalDemoSource();
  Object.defineProperty(source, "kind", { value: "api" });
  vi.spyOn(source, "getGeography").mockResolvedValue(geography);
  vi.spyOn(source, "getSession").mockResolvedValue({
    user: { name: "Test", role },
    csrfToken: "test",
  });
  source.getForecastThresholds = vi.fn().mockResolvedValue([
    {
      segmentId: "segment-1",
      regionId: "region-1",
      dailyEnergyKwh: 100,
      source: "MANUAL",
    },
  ]);
  source.createForecastRun = vi.fn().mockResolvedValue(run);
  source.getForecastRun = vi.fn().mockResolvedValue(run);
  source.updateForecastThreshold = vi
    .fn()
    .mockResolvedValue({ segmentId: "segment-1", dailyEnergyKwh: 90 });
  const cache = new QueryClient({
    defaultOptions: {
      queries: { retry: false, staleTime: Infinity },
      mutations: { retry: false },
    },
  });
  const show = () =>
    render(
      <QueryClientProvider client={cache}>
        <SourceContext.Provider value={source}>
          <MemoryRouter initialEntries={[`/statistics${search}`]}>
            <RegionProvider>
              <ForecastPanel />
            </RegionProvider>
          </MemoryRouter>
        </SourceContext.Provider>
      </QueryClientProvider>,
    );
  return { source, cache, show };
}

describe("scoped forecast run flow", () => {
  it.each([
    ["", { scope: "country" }],
    ["?region=BANAT", { scope: "region", regionId: "region-1" }],
    [
      "?region=BANAT&segment=segment-1",
      { scope: "segment", regionId: "region-1", segmentId: "segment-1" },
    ],
  ] as const)(
    "generates exactly the URL scope %s with progress, results and issue/map invalidation",
    async (search, expected) => {
      const { source, cache, show } = workspace(search);
      let finish!: (value: ForecastRun) => void;
      vi.mocked(source.createForecastRun!).mockReturnValue(
        new Promise((resolve) => {
          finish = resolve;
        }),
      );
      const invalidate = vi.spyOn(cache, "invalidateQueries");
      show();
      const button = screen.getByRole("button", {
        name: "Generate predictions",
      });
      await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
      fireEvent.click(button);
      expect(
        await screen.findByRole("progressbar", {
          name: "Forecast run progress",
        }),
      ).toBeTruthy();
      expect(button.hasAttribute("disabled")).toBe(true);
      expect(source.createForecastRun).toHaveBeenCalledExactlyOnceWith(
        expected,
      );
      finish({ ...run, ...expected });
      const table = await screen.findByRole("table", {
        name: "Forecast totals for Banat 1",
      });
      expect(within(table).getAllByRole("row")).toHaveLength(4);
      expect(within(table).getByText("Insufficient data")).toBeTruthy();
      expect(screen.getAllByText("BASELINE").length).toBeGreaterThan(0);
      expect(
        screen.getAllByLabelText("today's missing intervals estimated").length,
      ).toBeGreaterThan(0);
      expect(
        screen.getByRole("img", {
          name: "Three-day forecast vs threshold for Banat 1",
        }),
      ).toBeTruthy();
      expect(
        screen
          .getByRole("link", {
            name: /expected to exceed on 2026-11-15 by 20 kWh/,
          })
          .getAttribute("href"),
      ).toContain("issue=issue-1");
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["map"] });
      expect(invalidate).toHaveBeenCalledWith({ queryKey: ["issues"] });
      expect(screen.queryByRole("progressbar")).toBeNull();
      expect(
        screen.queryByRole("button", { name: /Edit threshold/ }),
      ).toBeNull();
    },
  );
  it("shows failed generation explicitly, stops progress, and allows an intentional retry", async () => {
    const { source, show } = workspace();
    vi.mocked(source.createForecastRun!).mockRejectedValueOnce(
      new Error("Forecast model unavailable"),
    );
    show();
    const button = screen.getByRole("button", { name: "Generate predictions" });
    await waitFor(() => expect(button.hasAttribute("disabled")).toBe(false));
    fireEvent.click(button);
    await screen.findByText("Forecast model unavailable");
    expect(screen.queryByRole("progressbar")).toBeNull();
    expect(screen.queryByRole("img")).toBeNull();
    expect(button.hasAttribute("disabled")).toBe(false);
    fireEvent.click(button);
    await screen.findByRole("table", { name: "Forecast totals for Banat 1" });
    expect(source.createForecastRun).toHaveBeenCalledTimes(2);
  });
  it("restores a persisted run by URL and lets only a manager edit positive thresholds", async () => {
    const { source, show } = workspace(
      "?region=BANAT&segment=segment-1&run=run-1",
      "MANAGER",
    );
    show();
    await screen.findByRole("table", { name: "Forecast totals for Banat 1" });
    expect(source.getForecastRun).toHaveBeenCalledWith("run-1");
    fireEvent.click(
      await screen.findByRole("button", { name: "Edit threshold for Banat 1" }),
    );
    fireEvent.change(
      screen.getByLabelText(/Daily energy threshold \(kWh\/day\)/),
      { target: { value: "0" } },
    );
    fireEvent.submit(
      screen.getByRole("button", { name: "Save threshold" }).closest("form")!,
    );
    expect(
      await screen.findByText("Use a positive finite daily threshold."),
    ).toBeTruthy();
    expect(source.updateForecastThreshold).not.toHaveBeenCalled();
    fireEvent.change(
      screen.getByLabelText(/Daily energy threshold \(kWh\/day\)/),
      { target: { value: "90" } },
    );
    fireEvent.click(screen.getByRole("button", { name: "Save threshold" }));
    await waitFor(() =>
      expect(source.updateForecastThreshold).toHaveBeenCalledWith(
        "segment-1",
        90,
      ),
    );
    await waitFor(() => expect(screen.queryByRole("dialog")).toBeNull());
    expect(source.getForecastThresholds).toHaveBeenCalledTimes(2);
  });
});
