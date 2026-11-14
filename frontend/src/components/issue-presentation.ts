import type { Issue, IssueType } from "../data/models";

export const ISSUE_TYPES: Record<
  IssueType,
  { label: string; color: string; symbol: string }
> = {
  OUTAGE_REPORT: { label: "Manual report", color: "#bc473e", symbol: "!" },
  OUTAGE_VIDEO: { label: "Outage video", color: "#8e427b", symbol: "V" },
  DRONE_DETECTED: { label: "Drone detected", color: "#3657a0", symbol: "D" },
  ML_FORECAST: { label: "ML forecast", color: "#ad691a", symbol: "F" },
  MISSING_DOCUMENTS: {
    label: "Missing documents",
    color: "#5c6e43",
    symbol: "P",
  },
};

export const issueTitle = (issue: Issue) =>
  issue.title ||
  `${ISSUE_TYPES[issue.type ?? "OUTAGE_REPORT"].label}: ${issue.description}`;

export function issueMapUrl(issue: Issue) {
  const params = new URLSearchParams({ region: issue.region, issue: issue.id });
  if (issue.segmentId) params.set("segment", issue.segmentId);
  return `/map?${params}`;
}
