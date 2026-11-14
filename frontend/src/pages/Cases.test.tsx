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
import { RegionProvider } from "../data/region";
import { CasesPage } from "./Cases";

afterEach(() => {
  cleanup();
  localStorage.clear();
});
it("sends the geographic scope and missing-only filter, and remembers list/grid across remounts", async () => {
  const source = new LocalDemoSource();
  const getCases = vi.spyOn(source, "getCases").mockResolvedValue({
    items: [
      {
        id: "case-1",
        title: "CLIENT-01 · Connection case",
        region: "BANAT",
        dueAt: "2026-11-15T00:00:00Z",
        status: "OPEN",
        documents: [
          { name: "Application", received: true },
          { name: "Approval", received: false },
        ],
      },
    ],
    page: 0,
    size: 6,
    totalElements: 1,
    totalPages: 1,
  });
  const show = () =>
    render(
      <QueryClientProvider
        client={
          new QueryClient({ defaultOptions: { queries: { retry: false } } })
        }
      >
        <SourceContext.Provider value={source}>
          <MemoryRouter
            initialEntries={["/cases?region=BANAT&segment=segment-1"]}
          >
            <RegionProvider>
              <CasesPage />
            </RegionProvider>
          </MemoryRouter>
        </SourceContext.Provider>
      </QueryClientProvider>,
    );
  const first = show();
  await screen.findByText("CLIENT-01 · Connection case");
  expect(getCases).toHaveBeenLastCalledWith(
    expect.objectContaining({
      region: "BANAT",
      segmentId: "segment-1",
      missingOnly: true,
    }),
  );
  expect(
    screen
      .getByRole("button", { name: "Grid view" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "List view" }));
  expect(
    screen.getByRole("table", { name: "Clients missing documents" })
      .textContent,
  ).toContain("Approval");
  expect(screen.getByRole("table").textContent).not.toContain("Application");
  first.unmount();
  show();
  await screen.findByRole("table", { name: "Clients missing documents" });
  expect(
    screen
      .getByRole("button", { name: "List view" })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "Grid view" }));
  await waitFor(() => expect(screen.queryByRole("table")).toBeNull());
  expect(screen.getByLabelText("Cases grid")).toBeTruthy();
});
