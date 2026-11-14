// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  QueryClient,
  QueryClientProvider,
  focusManager,
} from "@tanstack/react-query";
import { ThemeProvider } from "@mui/material";
import type { ReactNode } from "react";
import { SourceContext } from "../data/context";
import { LocalDemoSource } from "../data/demo";
import { AppError } from "../data/errors";
import { ADMIN_REFRESH_MS, useRecentAlerts } from "../data/admin-hooks";
import type { Role } from "../data/models";
import { theme } from "../theme";
import { AdminPage } from "./Admin";

afterEach(() => {
  cleanup();
  sessionStorage.clear();
  focusManager.setFocused(undefined);
  vi.useRealTimers();
});
async function workspace(role: Role = "MANAGER") {
  const source = new LocalDemoSource();
  const session = await source.login({ name: "Admin test", role });
  const cache = new QueryClient({
    defaultOptions: {
      queries: { retry: false, gcTime: 0 },
      mutations: { retry: false },
    },
  });
  cache.setQueryData(["session"], session);
  function Wrapper({ children }: { children: ReactNode }) {
    return (
      <ThemeProvider theme={theme}>
        <QueryClientProvider client={cache}>
          <SourceContext.Provider value={source}>
            {children}
          </SourceContext.Provider>
        </QueryClientProvider>
      </ThemeProvider>
    );
  }
  return { source, cache, Wrapper };
}
describe("manager administration page", () => {
  it("blocks direct operator access without requesting admin data", async () => {
    const { source, Wrapper } = await workspace("OPERATOR");
    const policies = vi.spyOn(source, "getPolicies");
    const simulator = vi.spyOn(source, "getSimulatorStatus");
    const runs = vi.spyOn(source, "getScenarioRuns");
    const alerts = vi.spyOn(source, "getRecentAlerts");
    render(<AdminPage />, { wrapper: Wrapper });
    expect(
      screen.getByText("This workspace is available to managers only."),
    ).toBeTruthy();
    expect(
      screen.queryByRole("button", { name: "Start simulator" }),
    ).toBeNull();
    for (const call of [policies, simulator, runs, alerts])
      expect(call).not.toHaveBeenCalled();
  });
  it("starts/stops with the selected profile and rate, then submits backfill and refreshes runs and alerts", async () => {
    const { source, Wrapper } = await workspace();
    const start = vi.spyOn(source, "startSimulator");
    const stop = vi.spyOn(source, "stopSimulator");
    const backfill = vi.spyOn(source, "backfillSimulator");
    render(<AdminPage />, { wrapper: Wrapper });
    expect(
      await screen.findByRole("table", { name: "Effective storage policies" }),
    ).toBeTruthy();
    await screen.findByText("Stopped");
    fireEvent.change(screen.getByLabelText("Simulator profile"), {
      target: { value: "storm" },
    });
    fireEvent.change(screen.getByLabelText("Readings per second"), {
      target: { value: "42.5" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Start simulator" }));
    await screen.findByText("Running");
    expect(start).toHaveBeenCalledWith({
      profile: "storm",
      readingsPerSecond: 42.5,
    });
    expect(
      screen
        .getByRole("button", { name: "Start simulator" })
        .hasAttribute("disabled"),
    ).toBe(true);
    fireEvent.click(screen.getByRole("button", { name: "Stop simulator" }));
    await screen.findByText("Stopped");
    expect(stop).toHaveBeenCalledOnce();
    fireEvent.change(screen.getByLabelText("Anomaly"), {
      target: { value: "gap" },
    });
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2026-11-01T08:00" },
    });
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "2026-11-02T08:00" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Run backfill" }));
    await screen.findByText(/Backfill accepted. Run ID:/);
    expect(backfill).toHaveBeenCalledWith({
      anomaly: "gap",
      from: new Date("2026-11-01T08:00").toISOString(),
      to: new Date("2026-11-02T08:00").toISOString(),
    });
    expect(
      within(
        await screen.findByRole("table", { name: "Scenario runs" }),
      ).getByText("BACKFILL"),
    ).toBeTruthy();
    expect(
      await screen.findByText("Demo gap anomaly in historical readings."),
    ).toBeTruthy();
  });
  it("disables invalid rates and backfill intervals before sending a command", async () => {
    const { source, Wrapper } = await workspace();
    const start = vi.spyOn(source, "startSimulator");
    const backfill = vi.spyOn(source, "backfillSimulator");
    render(<AdminPage />, { wrapper: Wrapper });
    await screen.findByText("Stopped");
    fireEvent.change(screen.getByLabelText("Readings per second"), {
      target: { value: "-1" },
    });
    expect(
      screen
        .getByRole("button", { name: "Start simulator" })
        .hasAttribute("disabled"),
    ).toBe(true);
    fireEvent.change(screen.getByLabelText("From"), {
      target: { value: "2026-11-03T08:00" },
    });
    fireEvent.change(screen.getByLabelText("To"), {
      target: { value: "2026-11-02T08:00" },
    });
    expect(
      screen
        .getByRole("button", { name: "Run backfill" })
        .hasAttribute("disabled"),
    ).toBe(true);
    expect(screen.getByText("From must be earlier than To.")).toBeTruthy();
    expect(start).not.toHaveBeenCalled();
    expect(backfill).not.toHaveBeenCalled();
  });
  it("retains policies after failed reload, shows the request ID, then displays the successful replacement", async () => {
    const { source, Wrapper } = await workspace();
    const policies = await source.getPolicies();
    const reload = vi
      .spyOn(source, "reloadPolicies")
      .mockRejectedValueOnce(
        new AppError(422, {
          code: "POLICY_INVALID",
          message: "Old policies remain active.",
          requestId: "req-policy",
        }),
      )
      .mockResolvedValueOnce([
        { ...policies[0], backend: "db", maxConcurrency: 9 },
      ]);
    render(<AdminPage />, { wrapper: Wrapper });
    const table = await screen.findByRole("table", {
      name: "Effective storage policies",
    });
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "Reload policies" }));
    expect(
      await screen.findByText(
        "Old policies remain active. · Request ID: req-policy",
      ),
    ).toBeTruthy();
    expect(within(table).getAllByRole("row")).toHaveLength(5);
    fireEvent.click(screen.getByRole("button", { name: "Reload policies" }));
    await screen.findByText("Policies reloaded.");
    expect(within(table).getByText("db")).toBeTruthy();
    expect(within(table).getByText("9")).toBeTruthy();
    expect(within(table).getAllByRole("row")).toHaveLength(2);
    expect(reload).toHaveBeenCalledTimes(2);
  });
  it("requests the next scenario page with the selected page size", async () => {
    const { source, Wrapper } = await workspace();
    const runs = vi
      .spyOn(source, "getScenarioRuns")
      .mockImplementation(async (page, size) => ({
        items: [
          {
            id: `run-${page}`,
            kind: "BACKFILL",
            profile: "zero",
            startedAt: null,
            endedAt: null,
            counters: {},
          },
        ],
        page,
        size,
        totalElements: 6,
        totalPages: 2,
      }));
    render(<AdminPage />, { wrapper: Wrapper });
    await screen.findByText("run-0");
    fireEvent.click(screen.getByRole("button", { name: "Go to next page" }));
    await screen.findByText("run-1");
    expect(runs).toHaveBeenLastCalledWith(1, 5);
  });
  it("polls alerts every ten seconds and stops polling after unmount", async () => {
    const { source, Wrapper } = await workspace();
    const alerts = vi
      .spyOn(source, "getRecentAlerts")
      .mockResolvedValue([
        {
          id: "alert-1",
          severity: "ERROR",
          message: "Fresh automated alert",
          occurredAt: null,
        },
      ]);
    vi.useFakeTimers();
    focusManager.setFocused(true);
    const hook = renderHook(() => useRecentAlerts(), { wrapper: Wrapper });
    await act(async () => {
      await vi.advanceTimersByTimeAsync(1);
    });
    expect(alerts).toHaveBeenCalledTimes(1);
    expect(hook.result.current.data?.[0].message).toBe("Fresh automated alert");
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ADMIN_REFRESH_MS);
    });
    expect(alerts).toHaveBeenCalledTimes(2);
    hook.unmount();
    await act(async () => {
      await vi.advanceTimersByTimeAsync(ADMIN_REFRESH_MS);
    });
    expect(alerts).toHaveBeenCalledTimes(2);
  });
  it("shows alert query failures with request IDs and allows retry", async () => {
    const { source, Wrapper } = await workspace();
    vi.spyOn(source, "getRecentAlerts")
      .mockRejectedValueOnce(
        new AppError(503, {
          code: "DOWN",
          message: "Alerts unavailable",
          requestId: "req-alerts",
        }),
      )
      .mockResolvedValueOnce([]);
    render(<AdminPage />, { wrapper: Wrapper });
    await screen.findByText("Alerts unavailable · Request ID: req-alerts");
    fireEvent.click(screen.getByRole("button", { name: "Retry" }));
    await screen.findByText("No recent alerts");
    await waitFor(() =>
      expect(screen.queryByText(/Alerts unavailable/)).toBeNull(),
    );
  });
});
