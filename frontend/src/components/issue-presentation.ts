import type { Issue, IssueStatus, IssueType } from "../data/models";

export const ISSUE_STATES: Record<
  IssueStatus,
  { label: string; color: string }
> = {
  OPEN: { label: "Open", color: "#bc473e" },
  IN_PROGRESS: { label: "Taken", color: "#f1cf41" },
  RESOLVED: { label: "Resolved", color: "#6e9e8a" },
};

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
  if (issue.type === "MISSING_DOCUMENTS") return issueDocumentsUrl(issue);
  const params = new URLSearchParams({ region: issue.region, issue: issue.id });
  if (issue.segmentId) params.set("segment", issue.segmentId);
  return `/map?${params}`;
}

export function issueDocumentsUrl(issue: Issue) {
  const params = new URLSearchParams({ region: issue.region });
  if (issue.segmentId) params.set("segment", issue.segmentId);
  if (issue.clientId) params.set("clientId", issue.clientId);
  if (issue.caseId) params.set("caseId", issue.caseId);
  return `/documents?${params}`;
}
