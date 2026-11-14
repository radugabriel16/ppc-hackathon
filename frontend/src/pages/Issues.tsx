import { useState } from "react";
import { Link } from "react-router-dom";
import {
  Button,
  Chip,
  MenuItem,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TablePagination,
  TextField,
} from "@mui/material";
import { useIssues } from "../data/hooks";
import { useRegion } from "../data/region-context";
import type { IssueStatus, IssueType } from "../data/models";
import {
  ErrorNotice,
  Empty,
  Loading,
  PageHeading,
  StatusChip,
} from "../components/common";
import {
  ISSUE_TYPES,
  issueMapUrl,
  issueTitle,
} from "../components/issue-presentation";

export function IssuesPage() {
  const { selectedRegion, subregionId } = useRegion();
  return <ScopedIssues key={`${selectedRegion}:${subregionId}`} />;
}

function ScopedIssues() {
  const { selectedRegion, subregionId } = useRegion();
  const [type, setType] = useState<IssueType | "">("");
  const [status, setStatus] = useState<IssueStatus | "">("");
  const [client, setClient] = useState("");
  const [from, setFrom] = useState("");
  const [to, setTo] = useState("");
  const [page, setPage] = useState(0);
  const invalidDate = !!from && !!to && from > to;
  const validClient =
    !client ||
    /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
      client,
    );
  const query = useIssues(
    {
      region: selectedRegion ?? undefined,
      segmentId: subregionId,
      type: type || undefined,
      status: status || undefined,
      clientId: validClient ? client || undefined : undefined,
      from: from ? `${from}T00:00:00Z` : undefined,
      to:
        to && !invalidDate
          ? new Date(Date.parse(`${to}T00:00:00Z`) + 86400000).toISOString()
          : undefined,
      page,
      size: 20,
    },
    !invalidDate && validClient,
  );
  return (
    <>
      <PageHeading
        eyebrow="OPERATIONAL FINDINGS"
        title="Issues"
        detail="Operational issues only. Region and segment follow the workspace scope."
      />
      <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
        <Stack direction="row" gap={2} flexWrap="wrap">
          <TextField
            select
            label="Issue type"
            value={type}
            sx={{ minWidth: 180 }}
            onChange={(e) => {
              setType(e.target.value as IssueType | "");
              setPage(0);
            }}
          >
            <MenuItem value="">All types</MenuItem>
            {Object.entries(ISSUE_TYPES).map(([key, info]) => (
              <MenuItem key={key} value={key}>
                {info.label}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Issue status"
            value={status}
            sx={{ minWidth: 160 }}
            onChange={(e) => {
              setStatus(e.target.value as IssueStatus | "");
              setPage(0);
            }}
          >
            <MenuItem value="">All statuses</MenuItem>
            {["OPEN", "IN_PROGRESS", "RESOLVED"].map((key) => (
              <MenuItem key={key} value={key}>
                {key.replaceAll("_", " ")}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            label="From date (UTC)"
            type="date"
            value={from}
            slotProps={{ inputLabel: { shrink: true } }}
            onChange={(e) => {
              setFrom(e.target.value);
              setPage(0);
            }}
          />
          <TextField
            label="Through date (UTC)"
            type="date"
            value={to}
            error={invalidDate}
            helperText={
              invalidDate ? "End date must not precede start date." : undefined
            }
            slotProps={{ inputLabel: { shrink: true } }}
            onChange={(e) => {
              setTo(e.target.value);
              setPage(0);
            }}
          />
          <TextField
            label="Client ID"
            value={client}
            error={!validClient}
            helperText={
              !validClient
                ? "Enter the complete client UUID."
                : "Optional client filter"
            }
            onChange={(e) => {
              setClient(e.target.value);
              setPage(0);
            }}
          />
        </Stack>
      </Paper>
      {query.isPending && <Loading />}
      {query.error && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {query.data && !invalidDate && validClient && (
        <Paper variant="outlined">
          <TableContainer>
            <Table aria-label="Operational issues">
              <TableHead>
                <TableRow>
                  {["Issue", "Type", "Status", "Created (UTC)"].map((name) => (
                    <TableCell key={name}>{name}</TableCell>
                  ))}
                </TableRow>
              </TableHead>
              <TableBody>
                {query.data.items.map((issue) => (
                  <TableRow key={issue.id} hover>
                    <TableCell>
                      <Button
                        component={Link}
                        to={issueMapUrl(issue)}
                        sx={{ textAlign: "left", justifyContent: "start" }}
                      >
                        {issueTitle(issue)}
                      </Button>
                    </TableCell>
                    <TableCell>
                      <Chip
                        size="small"
                        label={ISSUE_TYPES[issue.type ?? "OUTAGE_REPORT"].label}
                      />
                    </TableCell>
                    <TableCell>
                      <StatusChip status={issue.status} />
                    </TableCell>
                    <TableCell>
                      {issue.createdAt
                        ? new Date(issue.createdAt)
                            .toISOString()
                            .replace("T", " ")
                            .slice(0, 19)
                        : "Not supplied"}
                    </TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
          {!query.data.items.length && (
            <Empty title="No issues match these filters" />
          )}
          <TablePagination
            component="div"
            count={query.data.totalElements}
            page={page}
            rowsPerPage={20}
            rowsPerPageOptions={[20]}
            onPageChange={(_, p) => setPage(p)}
          />
        </Paper>
      )}
    </>
  );
}
