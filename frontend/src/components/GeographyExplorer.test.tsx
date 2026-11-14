// @vitest-environment jsdom
import {
  fireEvent,
  render,
  screen,
  within,
  cleanup,
} from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { useState } from "react";
import { GeographyExplorer } from "./GeographyExplorer";
import { areaBounds, areaFeatures } from "./map-geography";
import type { GeographicArea } from "../data/models";

afterEach(cleanup);
const area: GeographicArea = {
  id: "region",
  code: "BANAT",
  name: "Banat",
  region: "BANAT",
  parentId: null,
  meterCount: 12,
  geometry: {
    type: "MultiPolygon",
    coordinates: [
      [
        [
          [20, 44],
          [22, 44],
          [22, 46],
          [20, 46],
          [20, 44],
        ],
      ],
    ],
  },
};
const areas = [
  area,
  ...Array.from({ length: 6 }, (_, index) => ({
    ...area,
    id: `sub-${index}`,
    parentId: area.id,
    code: `BANAT-${index + 1}`,
    name: `Banat ${index + 1}`,
    meterCount: 2,
  })),
];

function Explorer() {
  const [selected, select] = useState<GeographicArea>();
  const back = () => select(selected?.parentId ? area : undefined);
  return (
    <div
      onKeyDown={(event) => {
        if (event.key === "Escape") back();
      }}
    >
      <GeographyExplorer
        areas={areas}
        selectedId={selected?.id}
        onSelect={select}
      />
      <output>{selected?.id ?? "ROMANIA"}</output>
    </div>
  );
}

it("selects the same region/subregion IDs as map features and navigates back", () => {
  render(<Explorer />);
  fireEvent.click(screen.getByRole("button", { name: "Banat · 12 meters" }));
  expect(screen.getByRole("status").textContent).toBe("region");
  expect(
    within(screen.getByRole("list", { name: "Subregions" })).getAllByRole(
      "button",
    ),
  ).toHaveLength(6);
  const sub = screen.getByRole("button", { name: "Banat 3 · 2 meters" });
  fireEvent.click(sub);
  expect(sub.getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("status").textContent).toBe(
    areaFeatures(areas).features[3].id,
  );
  const breadcrumb = screen.getByRole("navigation", {
    name: "Geography breadcrumb",
  });
  expect(breadcrumb.textContent).toContain("Romania>Banat>Banat 3");
  fireEvent.keyDown(sub, { key: "Escape" });
  expect(screen.getByRole("status").textContent).toBe("region");
  fireEvent.click(within(breadcrumb).getByRole("button", { name: "Romania" }));
  expect(screen.getByRole("status").textContent).toBe("ROMANIA");
  expect(screen.getByRole("list", { name: "Regions" })).toBeTruthy();
});

it("computes fitBounds from polygon coordinates rather than old square constants", () => {
  expect(areaBounds([area])).toEqual([
    [20, 44],
    [22, 46],
  ]);
});
