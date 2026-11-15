import {
  createExpression,
  featureFilter,
} from "@maplibre/maplibre-gl-style-spec";
import { expect, it } from "vitest";
import { issueColor, manualReportFilter } from "./issue-map-style";
import { ISSUE_STATES, ISSUE_TYPES } from "./issue-presentation";

it("evaluates marker colors from status for every issue type, regardless of selection", () => {
  const color = createExpression(issueColor);
  if (color.result !== "success")
    throw new Error("Invalid issue color expression");
  for (const type of Object.keys(ISSUE_TYPES))
    for (const [status, state] of Object.entries(ISSUE_STATES))
      for (const selected of [true, false])
        expect(
          color.value.evaluate(
            { zoom: 8 },
            { type: "Point", properties: { type, status } },
            { selected },
          ),
        ).toBe(state.color);
});

it("includes only open manual reports in the single pulse layer", () => {
  const pulse = featureFilter(manualReportFilter);
  for (const type of Object.keys(ISSUE_TYPES))
    for (const status of Object.keys(ISSUE_STATES))
      expect(
        pulse.filter(
          { zoom: 8 },
          { type: "Point", properties: { type, status } },
        ),
      ).toBe(type === "OUTAGE_REPORT" && status === "OPEN");
});
