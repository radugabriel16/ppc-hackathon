import type { ExpressionSpecification } from "maplibre-gl";
import { ISSUE_STATES } from "./issue-presentation";

export const issueColor: ExpressionSpecification = [
  "match",
  ["get", "status"],
  "OPEN",
  ISSUE_STATES.OPEN.color,
  "IN_PROGRESS",
  ISSUE_STATES.IN_PROGRESS.color,
  "RESOLVED",
  ISSUE_STATES.RESOLVED.color,
  "#68737d",
];

export const manualReportFilter: ExpressionSpecification = [
  "all",
  ["==", ["get", "type"], "OUTAGE_REPORT"],
  ["==", ["get", "status"], "OPEN"],
];
