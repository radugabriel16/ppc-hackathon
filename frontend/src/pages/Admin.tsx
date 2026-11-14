import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  LinearProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TablePagination,
  TableRow,
  TextField,
  Typography,
} from "@mui/material";
import { ManagerOnly } from "../components/Shell";
import { Empty, ErrorNotice, Loading, PageHeading } from "../components/common";
import {
  usePolicies,
  useRecentAlerts,
  useReloadPolicies,
  useScenarioRuns,
  useSimulatorControls,
  useSimulatorStatus,
} from "../data/admin-hooks";
import {
  BACKFILL_ANOMALIES,
  bytes,
  label,
  SIMULATOR_PROFILES,
  type SimulatorBackfill,
  type SimulatorStart,
} from "../data/models";

const dateTime = (value: string | null) =>
  value ? new Date(value).toLocaleString() : "—";
const sizeLabel = (value: number | null) =>
  value === null ? "—" : bytes(value);
const localDateTime = (value: Date) =>
  new Date(value.getTime() - value.getTimezoneOffset() * 60000)
    .toISOString()
    .slice(0, 16);

function Policies() {
  const query = usePolicies();
  const reload = useReloadPolicies();
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        mb={2}
      >
        <Typography variant="h6" component="h2">
          Effective policies
        </Typography>
        <Button
          variant="outlined"
          disabled={reload.isPending || query.isPending}
          onClick={() => reload.mutate()}
        >
          {reload.isPending ? "Reloading…" : "Reload policies"}
        </Button>
      </Stack>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Current storage policy for every configured category. Reload applies the
        server configuration after validation.
      </Typography>
      {query.isPending && <Loading label="Loading policies…" />}
      {query.error && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {reload.error && <ErrorNotice error={reload.error} />}
      {reload.isSuccess && <Alert severity="success">Policies reloaded.</Alert>}
      {query.data?.length === 0 && (
        <Empty
          title="No effective policies"
          detail="No category policies were returned."
        />
      )}
      {!!query.data?.length && (
        <TableContainer>
          <Table size="small" aria-label="Effective storage policies">
            <TableHead>
              <TableRow>
                {[
                  "Category",
                  "Backend",
                  "Fallback",
                  "Max size",
                  "Concurrency",
                  "Encryption",
                  "Resumable",
                  "Chunk size",
                ].map((name) => (
                  <TableCell key={name}>{name}</TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {query.data.map((policy) => (
                <TableRow key={policy.category}>
                  <TableCell component="th" scope="row">
                    {label(policy.category)}
                  </TableCell>
                  <TableCell>{policy.backend ?? "—"}</TableCell>
                  <TableCell>{policy.fallback ?? "—"}</TableCell>
                  <TableCell>{sizeLabel(policy.maxSizeBytes)}</TableCell>
                  <TableCell>{policy.maxConcurrency ?? "—"}</TableCell>
                  <TableCell>{policy.encryption ?? "Not specified"}</TableCell>
                  <TableCell>
                    {policy.resumable === null
                      ? "—"
                      : policy.resumable
                        ? "Yes"
                        : "No"}
                  </TableCell>
                  <TableCell>{sizeLabel(policy.chunkSizeBytes)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
    </Paper>
  );
}

function Simulator() {
  const query = useSimulatorStatus();
  const { start, stop, backfill } = useSimulatorControls();
  const [profile, setProfile] = useState<SimulatorStart["profile"]>("normal");
  const [rate, setRate] = useState("10");
  const [anomaly, setAnomaly] = useState<SimulatorBackfill["anomaly"]>("spike");
  const [from, setFrom] = useState(() =>
    localDateTime(new Date(Date.now() - 86400000)),
  );
  const [to, setTo] = useState(() => localDateTime(new Date()));
  const validRate =
    rate.trim() !== "" && Number.isFinite(Number(rate)) && Number(rate) > 0;
  const validRange =
    Number.isFinite(Date.parse(from)) &&
    Number.isFinite(Date.parse(to)) &&
    Date.parse(from) < Date.parse(to);
  const busy = start.isPending || stop.isPending || backfill.isPending;
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Stack direction="row" gap={2} alignItems="center" mb={2}>
        <Typography variant="h6" component="h2">
          Smart-meter simulator
        </Typography>
        {query.data && (
          <Chip
            size="small"
            color={query.data.running ? "success" : "default"}
            label={query.data.running ? "Running" : "Stopped"}
          />
        )}
      </Stack>
      {query.isPending && <Loading label="Loading simulator status…" />}
      {query.isFetching && !query.isPending && (
        <LinearProgress aria-label="Refreshing simulator status" />
      )}
      {query.error && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {query.data && (
        <Typography variant="body2" color="text.secondary" mb={3}>
          Active profile: {query.data.profile ?? "—"} · Rate:{" "}
          {query.data.readingsPerSecond ?? "—"} readings/s
        </Typography>
      )}
      <Box
        component="form"
        onSubmit={(event) => {
          event.preventDefault();
          if (
            validRate &&
            !busy &&
            query.data &&
            !query.error &&
            !query.data.running
          )
            start.mutate({ profile, readingsPerSecond: Number(rate) });
        }}
      >
        <Stack
          direction={{ xs: "column", sm: "row" }}
          gap={2}
          alignItems={{ sm: "flex-start" }}
        >
          <TextField
            select
            label="Simulator profile"
            value={profile}
            onChange={(event) =>
              setProfile(event.target.value as SimulatorStart["profile"])
            }
            slotProps={{ select: { native: true } }}
            sx={{ minWidth: 160 }}
          >
            {SIMULATOR_PROFILES.map((value) => (
              <option key={value} value={value}>
                {label(value)}
              </option>
            ))}
          </TextField>
          <TextField
            label="Readings per second"
            type="number"
            value={rate}
            onChange={(event) => setRate(event.target.value)}
            error={!validRate}
            helperText={
              !validRate
                ? "Enter a positive, finite rate."
                : "Readings generated each second"
            }
            slotProps={{ htmlInput: { min: 0, step: "any" } }}
          />
          <Button
            type="submit"
            variant="contained"
            disabled={
              busy ||
              !validRate ||
              !query.data ||
              !!query.error ||
              query.data.running
            }
          >
            Start simulator
          </Button>
          <Button
            variant="outlined"
            disabled={
              busy || !query.data || !!query.error || !query.data.running
            }
            onClick={() => stop.mutate()}
          >
            Stop simulator
          </Button>
        </Stack>
      </Box>
      {start.error && <ErrorNotice error={start.error} />}
      {stop.error && <ErrorNotice error={stop.error} />}
      <Typography variant="subtitle1" component="h3" mt={3} mb={1}>
        Backfill historical readings
      </Typography>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Choose an anomaly and a time range. Times use your local timezone.
      </Typography>
      <Box
        component="form"
        onSubmit={(event) => {
          event.preventDefault();
          if (validRange && !busy)
            backfill.mutate({
              anomaly,
              from: new Date(from).toISOString(),
              to: new Date(to).toISOString(),
            });
        }}
      >
        <Stack
          direction={{ xs: "column", md: "row" }}
          gap={2}
          alignItems={{ md: "flex-start" }}
        >
          <TextField
            select
            label="Anomaly"
            value={anomaly}
            onChange={(event) =>
              setAnomaly(event.target.value as SimulatorBackfill["anomaly"])
            }
            slotProps={{ select: { native: true } }}
            sx={{ minWidth: 140 }}
          >
            {BACKFILL_ANOMALIES.map((value) => (
              <option key={value} value={value}>
                {label(value)}
              </option>
            ))}
          </TextField>
          <TextField
            label="From"
            type="datetime-local"
            value={from}
            onChange={(event) => setFrom(event.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
          />
          <TextField
            label="To"
            type="datetime-local"
            value={to}
            onChange={(event) => setTo(event.target.value)}
            slotProps={{ inputLabel: { shrink: true } }}
            error={!validRange}
            helperText={
              !validRange ? "From must be earlier than To." : undefined
            }
          />
          <Button
            type="submit"
            variant="outlined"
            disabled={busy || !validRange}
          >
            Run backfill
          </Button>
        </Stack>
      </Box>
      {busy && (
        <LinearProgress
          aria-label="Applying simulator command"
          sx={{ mt: 2 }}
        />
      )}
      {backfill.error && <ErrorNotice error={backfill.error} />}
      {backfill.isSuccess && (
        <Alert severity="success" sx={{ mt: 2 }}>
          Backfill accepted. Run ID: {backfill.data.id}
        </Alert>
      )}
    </Paper>
  );
}

function ScenarioRuns() {
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(5);
  const query = useScenarioRuns(page, size);
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Typography variant="h6" component="h2" mb={2}>
        Scenario runs
      </Typography>
      {query.isPending && <Loading label="Loading scenario runs…" />}
      {query.error && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {query.data?.items.length === 0 && (
        <Empty
          title="No scenario runs"
          detail="Start the simulator or run a backfill to create a run."
        />
      )}
      {!!query.data?.items.length && (
        <TableContainer>
          <Table size="small" aria-label="Scenario runs">
            <TableHead>
              <TableRow>
                {[
                  "Run ID",
                  "Kind",
                  "Profile",
                  "Started",
                  "Ended",
                  "Counters",
                ].map((name) => (
                  <TableCell key={name}>{name}</TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {query.data.items.map((run) => (
                <TableRow key={run.id}>
                  <TableCell sx={{ fontFamily: "monospace", fontSize: 12 }}>
                    {run.id}
                  </TableCell>
                  <TableCell>{run.kind ?? "—"}</TableCell>
                  <TableCell>{run.profile ?? "—"}</TableCell>
                  <TableCell>{dateTime(run.startedAt)}</TableCell>
                  <TableCell>{dateTime(run.endedAt)}</TableCell>
                  <TableCell sx={{ overflowWrap: "anywhere", maxWidth: 240 }}>
                    {Object.keys(run.counters).length
                      ? JSON.stringify(run.counters)
                      : "—"}
                  </TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      )}
      {query.data && (
        <TablePagination
          component="div"
          count={query.data.totalElements}
          page={page}
          rowsPerPage={size}
          rowsPerPageOptions={[5, 10, 25]}
          onPageChange={(_, value) => setPage(value)}
          onRowsPerPageChange={(event) => {
            setSize(Number(event.target.value));
            setPage(0);
          }}
        />
      )}
    </Paper>
  );
}

function RecentAlerts() {
  const query = useRecentAlerts();
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Stack
        direction="row"
        alignItems="center"
        justifyContent="space-between"
        mb={1}
      >
        <Typography variant="h6" component="h2">
          Recent alerts
        </Typography>
        <Button
          disabled={query.isFetching}
          onClick={() => void query.refetch()}
        >
          Refresh alerts
        </Button>
      </Stack>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Auto-refreshes every 10 seconds while this page is active.
      </Typography>
      {query.isPending && <Loading label="Loading recent alerts…" />}
      {query.isFetching && !query.isPending && (
        <LinearProgress aria-label="Refreshing recent alerts" />
      )}
      {query.error && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {query.data?.length === 0 && (
        <Empty
          title="No recent alerts"
          detail="No automated requirement breaches were returned."
        />
      )}
      <Stack
        component="ul"
        spacing={1.5}
        sx={{ listStyle: "none", p: 0, m: 0 }}
      >
        {query.data?.map((alert) => {
          const severity = alert.severity?.toUpperCase();
          const color = ["CRITICAL", "HIGH", "ERROR"].includes(severity ?? "")
            ? "error"
            : ["WARNING", "WARN", "MEDIUM"].includes(severity ?? "")
              ? "warning"
              : "info";
          return (
            <Box component="li" key={alert.id}>
              <Alert severity={color}>
                <Typography variant="body2" fontWeight={600}>
                  {alert.message}
                </Typography>
                <Typography variant="caption">
                  {alert.severity ?? "Unspecified severity"} ·{" "}
                  {dateTime(alert.occurredAt)}
                </Typography>
              </Alert>
            </Box>
          );
        })}
      </Stack>
    </Paper>
  );
}

function Administration() {
  return (
    <>
      <PageHeading
        eyebrow="MANAGER WORKSPACE"
        title="Administration."
        detail="Effective storage policies, simulator operations and automated alerts across all regions."
      />
      <Stack spacing={3}>
        <Policies />
        <Simulator />
        <ScenarioRuns />
        <RecentAlerts />
      </Stack>
    </>
  );
}
export function AdminPage() {
  return (
    <ManagerOnly>
      <Administration />
    </ManagerOnly>
  );
}
