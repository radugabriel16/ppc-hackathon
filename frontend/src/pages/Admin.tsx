import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  LinearProgress,
  Paper,
  Stack,
  Tab,
  Tabs,
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
import { MeterReadingsTable } from "../components/MeterReadingsTable";
import { useMeterReadings, useReadingMeters } from "../data/meter-readings-hooks";
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
  bytes,
  label,
  SIMULATOR_PROFILES,
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

function LatestIngestedReadings() {
  const [meterId, setMeterId] = useState("");
  const meters = useReadingMeters();
  const simulator = useSimulatorStatus();
  const query = useMeterReadings(
    { meterId: meterId || undefined, order: "received_desc", page: 0, size: 50 },
    simulator.data?.running === true || (simulator.data?.outboxSize ?? 0) > 0,
  );
  return (
    <Paper variant="outlined" sx={{ p: 3, minWidth: 0 }}>
      <Typography variant="h6" component="h2" mb={1}>
        Latest ingested readings
      </Typography>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Last 50 individual catalog readings, newest server receipt first.
        Source and ingest result are not stored.
      </Typography>
      <TextField
        select
        label="Filter by meter"
        value={meterId}
        onChange={(event) => setMeterId(event.target.value)}
        slotProps={{ select: { native: true } }}
        sx={{ minWidth: 240, mb: 2 }}
      >
        <option value="">All meters</option>
        {meters.data?.map((meter) => (
          <option key={meter.id} value={meter.id}>{meter.code}</option>
        ))}
      </TextField>
      {meters.error && <ErrorNotice error={meters.error} retry={() => void meters.refetch()} />}
      {simulator.error && <ErrorNotice error={simulator.error} retry={() => void simulator.refetch()} />}
      {query.isPending && <Loading label="Loading ingested readings..." />}
      {query.error && <ErrorNotice error={query.error} retry={() => void query.refetch()} />}
      {query.isFetching && !query.isPending && <LinearProgress aria-label="Refreshing ingested readings" />}
      {query.data?.items.length === 0 && (
        <Empty title="No ingested readings" detail="No catalog readings match this meter filter." />
      )}
      {!!query.data?.items.length && <MeterReadingsTable readings={query.data.items} />}
    </Paper>
  );
}

function Simulator() {
  const query = useSimulatorStatus();
  const { start, stop, backfill } = useSimulatorControls();
  const [profile, setProfile] = useState<SimulatorStart["profile"]>("normal");
  const [seconds, setSeconds] = useState(5);
  const [backfillProfile, setBackfillProfile] = useState<SimulatorStart["profile"]>("normal");
  const [preparing, setPreparing] = useState(false);
  const [prepareError, setPrepareError] = useState<unknown>(null);
  const alignedNow = () => new Date(Math.floor(Date.now() / 900000) * 900000);
  const [from, setFrom] = useState(() =>
    localDateTime(new Date(alignedNow().getTime() - 86400000)),
  );
  const [to, setTo] = useState(() => localDateTime(alignedNow()));
  const validRange =
    Number.isFinite(Date.parse(from)) &&
    Number.isFinite(Date.parse(to)) &&
    Date.parse(from) < Date.parse(to) &&
    Date.parse(to) - Date.parse(from) <= 31 * 86400000 &&
    Date.parse(from) % 900000 === 0 && Date.parse(to) % 900000 === 0;
  const busy = preparing || start.isPending || stop.isPending || backfill.isPending;
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
            label={query.data.running ? "Running" : (query.data.outboxSize ?? 0) > 0
              ? `Draining (${query.data.outboxSize} queued)` : "Stopped"}
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
          {query.data.readingsPerSecond ?? "—"} readings/s · Meters: {query.data.meterCount ?? "—"}
          {" · "}Source: {query.data.meterSource ?? "—"} · Outbox: {query.data.outboxSize ?? "—"}
          {" · "}Generation paused: {query.data.generationPaused === undefined ? "—" : query.data.generationPaused ? "Yes" : "No"}
          {query.data.counters && <> · Sent counters: {JSON.stringify(query.data.counters)}</>}
        </Typography>
      )}
      {query.data?.meterSource === "fallback" && <Alert severity="warning">API discovery failed; using fallback meters. Restart the simulator after API recovery.</Alert>}
      {query.data?.lastError && <Alert severity="error">{query.data.lastError}</Alert>}
      <Box
        component="form"
        onSubmit={async (event) => {
          event.preventDefault();
          if (busy) return;
          setPreparing(true);
          setPrepareError(null);
          start.reset();
          try {
            const status = await query.refetch({ throwOnError: true });
            const count = status.data?.meterCount;
            if (count === undefined || count <= 0)
              throw new Error("Simulator status did not return a positive meterCount.");
            start.mutate({ profile, readingsPerSecond: count / seconds });
          } catch (error) {
            setPrepareError(error);
          } finally {
            setPreparing(false);
          }

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
            select
            label="Seconds per meter"
            value={seconds}
            onChange={(event) => setSeconds(Number(event.target.value))}
            helperText="Each reading advances its meter by 15 simulated minutes"
            slotProps={{ select: { native: true } }}
          >
            {[5, 10, 30, 60].map((value) => <option key={value} value={value}>{value} seconds</option>)}
          </TextField>
          <Button
            type="submit"
            variant="contained"
            disabled={
              busy ||
              !query.data ||
              !!query.error
            }
          >
            {query.data?.running ? "Apply" : "Start"}
          </Button>
          <Button
            variant="outlined"
            disabled={
              busy || !query.data || !!query.error || !query.data.running
            }
            onClick={() => stop.mutate()}
          >
            Stop
          </Button>
        </Stack>
      </Box>
      {start.error && <ErrorNotice error={start.error} />}
      {prepareError !== null && <ErrorNotice error={prepareError} />}
      {stop.error && <ErrorNotice error={stop.error} />}
      <Typography variant="subtitle1" component="h3" mt={3} mb={1}>
        Backfill historical readings
      </Typography>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Choose a profile and a 15-minute aligned range of at most 31 days. Times use your local timezone.
      </Typography>
      <Box
        component="form"
        onSubmit={(event) => {
          event.preventDefault();
          if (validRange && !busy)
            backfill.mutate({
              profile: backfillProfile,
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
            label="Backfill profile"
            value={backfillProfile}
            onChange={(event) =>
              setBackfillProfile(event.target.value as SimulatorStart["profile"])
            }
            slotProps={{ select: { native: true } }}
            sx={{ minWidth: 140 }}
          >
            {SIMULATOR_PROFILES.map((value) => (
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
            slotProps={{ inputLabel: { shrink: true }, htmlInput: { step: 900 } }}
          />
          <TextField
            label="To"
            type="datetime-local"
            value={to}
            onChange={(event) => setTo(event.target.value)}
            slotProps={{ inputLabel: { shrink: true }, htmlInput: { step: 900 } }}
            error={!validRange}
            helperText={
              !validRange ? "Use 15-minute aligned times, From before To, at most 31 days apart." : undefined
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

export function ScenarioRuns() {
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
  const [tab, setTab] = useState(0);
  return (
    <>
      <PageHeading
        eyebrow="MANAGER WORKSPACE"
        title="Administration."
        detail="Effective storage policies, simulator operations and automated alerts across all regions."
      />
      <Tabs value={tab} onChange={(_, value: number) => setTab(value)} aria-label="Administration tabs">
        <Tab label="Meter readings" />
        <Tab label="Policies" />
        <Tab label="Alerts" />
      </Tabs>
      <Stack spacing={3} mt={3}>
        {tab === 0 && <><Simulator /><LatestIngestedReadings /><Alert severity="info">Runs history is unavailable here: the existing admin history endpoint reads catalog-db, but simulator runs are stored locally.</Alert></>}
        {tab === 1 && <Policies />}
        {tab === 2 && <RecentAlerts />}
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
