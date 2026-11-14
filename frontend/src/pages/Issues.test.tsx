// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter } from "react-router-dom";
import { SourceContext } from "../data/context";
import { LocalDemoSource } from "../data/demo";
import type { DataSource } from "../data/source";
import { RegionProvider } from "../data/region";
import { IssuesPage } from "./Issues";

afterEach(cleanup);
it("combines scope/type/status/date/client filters and links readable findings to selected map details", async () => {
  const source: DataSource = new LocalDemoSource();
  source.getIssues = vi.fn().mockResolvedValue({
    items: [
      {
        id: "issue-1",
        region: "BANAT",
        segmentId: "segment-1",
        type: "ML_FORECAST",
        title: "Banat 1 expected to exceed on 2026-11-15 by 20 kWh",
        description: "Expected consumption",
        assetId: "asset-1",
        coordinates: [21, 45],
        severity: "HIGH",
        status: "OPEN",
        version: 1,
        createdAt: "2026-11-14T20:00:00Z",
      },
    ],
    page: 0,
    size: 20,
    totalPages: 1,
    totalElements: 1,
  });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SourceContext.Provider value={source}>
        <MemoryRouter
          initialEntries={["/issues?region=BANAT&segment=segment-1"]}
        >
          <RegionProvider>
            <IssuesPage />
          </RegionProvider>
        </MemoryRouter>
      </SourceContext.Provider>
    </QueryClientProvider>,
  );
  const link = await screen.findByRole("link", {
    name: /expected to exceed on/,
  });
  expect(link.getAttribute("href")).toBe(
    "/map?region=BANAT&issue=issue-1&segment=segment-1",
  );
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "Issue type" }));
  fireEvent.click(screen.getByRole("option", { name: "ML forecast" }));
  fireEvent.mouseDown(screen.getByRole("combobox", { name: "Issue status" }));
  fireEvent.click(screen.getByRole("option", { name: "OPEN" }));
  fireEvent.change(screen.getByLabelText("From date (UTC)"), {
    target: { value: "2026-11-14" },
  });
  fireEvent.change(screen.getByLabelText("Through date (UTC)"), {
    target: { value: "2026-11-14" },
  });
  const clientId = "11111111-1111-4111-8111-111111111111";
  fireEvent.change(screen.getByLabelText("Client ID"), {
    target: { value: clientId },
  });
  await waitFor(() =>
    expect(source.getIssues).toHaveBeenLastCalledWith({
      region: "BANAT",
      segmentId: "segment-1",
      type: "ML_FORECAST",
      status: "OPEN",
      clientId,
      from: "2026-11-14T00:00:00Z",
      to: "2026-11-15T00:00:00.000Z",
      page: 0,
      size: 20,
    }),
  );
  const calls = vi.mocked(source.getIssues).mock.calls.length;
  fireEvent.change(screen.getByLabelText("Client ID"), {
    target: { value: "incomplete" },
  });
  expect(screen.getByText("Enter the complete client UUID.")).toBeTruthy();
  expect(source.getIssues).toHaveBeenCalledTimes(calls);
});
