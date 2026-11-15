// @vitest-environment jsdom
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, expect, it, vi } from "vitest";
import { IntakeWorkspace } from "./IntakeWorkspace";
import { SourceContext } from "../data/context";
import { LocalDemoSource } from "../data/demo";
import { DocumentIntakeApi, validCnp } from "../data/document-intake";
import { AppError } from "../data/errors";
import { ApiConnection } from "../data/api-client";

const cnp = "5010101400010";
afterEach(cleanup);
function setup(prefilled = false) {
  const api = new DocumentIntakeApi(new ApiConnection());
  const item = {
    id: "item-1",
    originalFileName: "misleading-name.pdf",
    status: "NEEDS_REVIEW" as const,
    reviewReason: "CNP_MISSING" as const,
    reviewQueue: "MANUAL" as const,
    version: 2,
    createdAt: "2026-11-15T00:00:00Z",
  };
  vi.spyOn(api, "reviews").mockImplementation(async (q) => ({
    items: q === "MANUAL" ? [item] : [],
    page: 0,
    size: 10,
    totalElements: q === "MANUAL" ? 1 : 0,
    totalPages: 1,
  }));
  const upload = vi
    .spyOn(api, "upload")
    .mockResolvedValue({ ...item, status: "AUTO_LINKED" });
  vi.spyOn(api, "lookup").mockResolvedValue({
    customerId: "client-1",
    customerName: "Demo client",
    cnpMasked: "5********0010",
  });
  const confirm = vi
    .spyOn(api, "confirm")
    .mockResolvedValue({ ...item, status: "CONFIRMED" });
  const source = Object.assign(new LocalDemoSource(), { documentIntake: api });
  render(
    <QueryClientProvider
      client={
        new QueryClient({ defaultOptions: { queries: { retry: false } } })
      }
    >
      <SourceContext.Provider value={source}>
        <IntakeWorkspace
          slot={
            prefilled
              ? {
                  customerId: "client-1",
                  customerName: "Demo client",
                  documentType: "REQUEST_FORM",
                }
              : null
          }
          clearSlot={() => {}}
          previewId={null}
          clearPreview={() => {}}
        />
      </SourceContext.Provider>
    </QueryClientProvider>,
  );
  return { api, upload, confirm };
}
it("validates CNP structure and checksum consistently", () => {
  expect(validCnp(cnp)).toBe(true);
  expect(validCnp("0000000000001")).toBe(false);
  expect(validCnp(cnp.slice(0, -1) + "3")).toBe(false);
});
it("keeps the missing-slot customer/type fixed and passes explicit manual confirmation", async () => {
  const { upload } = setup(true);
  expect((screen.getByLabelText("Customer") as HTMLInputElement).readOnly).toBe(
    true,
  );
  const file = new File(["%PDF-demo"], "unrelated-name.pdf", {
    type: "application/pdf",
  });
  fireEvent.change(screen.getByLabelText("Choose documents"), {
    target: { files: [file] },
  });
  fireEvent.click(screen.getByLabelText(/I checked this document/));
  fireEvent.click(screen.getByRole("button", { name: "Upload" }));
  await waitFor(() =>
    expect(upload).toHaveBeenCalledWith(file, "client-1", "REQUEST_FORM", true),
  );
});
it("requires validated customer preview before enabling review confirmation", async () => {
  const { confirm } = setup();
  fireEvent.click(screen.getByRole("button", { name: "Review documents" }));
  fireEvent.click(await screen.findByRole("tab", { name: /Needs review/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: "misleading-name.pdf" }),
  );
  expect(
    (screen.getByRole("button", { name: "Confirm" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
  fireEvent.change(screen.getByLabelText("Customer CNP"), {
    target: { value: cnp },
  });
  fireEvent.click(screen.getByRole("button", { name: "Find customer" }));
  await screen.findByText("Matched customer: Demo client");
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await waitFor(() =>
    expect(confirm).toHaveBeenCalledWith("item-1", {
      documentType: "ID",
      cnp,
      version: 2,
      replaceExisting: false,
    }),
  );
});

it("reloads the review queue on 409 and requires a new customer check", async () => {
  const { api, confirm } = setup();
  confirm.mockRejectedValueOnce(
    new AppError(409, {
      code: "VERSION_CONFLICT",
      message: "Reload",
      requestId: "test",
    }),
  );
  fireEvent.click(screen.getByRole("button", { name: "Review documents" }));
  fireEvent.click(await screen.findByRole("tab", { name: /Needs review/ }));
  fireEvent.click(
    await screen.findByRole("button", { name: "misleading-name.pdf" }),
  );
  fireEvent.change(screen.getByLabelText("Customer CNP"), {
    target: { value: cnp },
  });
  fireEvent.click(screen.getByRole("button", { name: "Find customer" }));
  await screen.findByText("Matched customer: Demo client");
  const previous = vi.mocked(api.reviews).mock.calls.length;
  fireEvent.click(screen.getByRole("button", { name: "Confirm" }));
  await screen.findByText(
    "This item changed. Reloaded; check it again before confirming.",
  );
  expect(vi.mocked(api.reviews).mock.calls.length).toBeGreaterThan(previous);
  expect(
    (screen.getByRole("button", { name: "Confirm" }) as HTMLButtonElement)
      .disabled,
  ).toBe(true);
});
