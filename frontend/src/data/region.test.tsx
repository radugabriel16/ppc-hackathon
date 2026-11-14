// @vitest-environment jsdom
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import { Link, MemoryRouter, useLocation, useNavigate } from "react-router-dom";
import { RegionProvider } from "./region";
import { useRegion } from "./region-context";

afterEach(cleanup);
function Controls() {
  const { selectedRegion, subregionId, setScope, clearRegion } = useRegion();
  const location = useLocation();
  const navigate = useNavigate();
  return (
    <>
      <output>
        {selectedRegion ?? "ROMANIA"}:{subregionId ?? "ALL"}
      </output>
      <span data-testid="url">
        {location.pathname}
        {location.search}
      </span>
      <button onClick={() => setScope("BANAT", "segment-2")}>
        Select segment
      </button>
      <button onClick={clearRegion}>Romania</button>
      <button onClick={() => navigate(-1)}>Back</button>
      <Link to={{ pathname: "/cases", search: location.search }}>Cases</Link>
    </>
  );
}
it("restores deep links, keeps scope across tabs and responds to browser back", () => {
  render(
    <MemoryRouter initialEntries={["/map?region=MUNTENIA&segment=segment-1"]}>
      <RegionProvider>
        <Controls />
      </RegionProvider>
    </MemoryRouter>,
  );
  expect(screen.getByRole("status").textContent).toBe("MUNTENIA:segment-1");
  fireEvent.click(screen.getByText("Select segment"));
  fireEvent.click(screen.getByText("Cases"));
  expect(screen.getByTestId("url").textContent).toBe(
    "/cases?region=BANAT&segment=segment-2",
  );
  fireEvent.click(screen.getByText("Romania"));
  expect(screen.getByRole("status").textContent).toBe("ROMANIA:ALL");
  fireEvent.click(screen.getByText("Back"));
  expect(screen.getByRole("status").textContent).toBe("BANAT:segment-2");
});
