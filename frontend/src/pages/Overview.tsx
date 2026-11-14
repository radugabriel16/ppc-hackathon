import { useState, type ReactNode } from "react";
import {
  Box,
  Chip,
  LinearProgress,
  Paper,
  Stack,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
  TextField,
  ToggleButton,
  ToggleButtonGroup,
  Typography,
} from "@mui/material";
import { ErrorNotice, Empty, Loading, PageHeading } from "../components/common";
import { MapLinkButton } from "../components/Shell";
import { StatisticsChart } from "../components/StatisticsChart";
import { HotspotMap } from "../components/HotspotMap";
import {
  benchmarkOption,
  BENCHMARK_METRICS,
  forecastOption,
  meterOption,
  type BenchmarkMetric,
} from "../charts/options";
import type { HotspotMode } from "../charts/hotspots";
import { useDataMode } from "../data/hooks";
import {
  useStorageBenchmark,
  useStorageRecommendations,
  useMeterConsumption,
  useOutageHotspots,
  useForecast,
} from "../data/stats-hooks";
import { useRegion } from "../data/region-context";
import {
  CATEGORIES,
  STORAGES,
  REGION_INFO,
  label,
  type BenchmarkProfile,
  type Region,
} from "../data/models";

interface QueryState {
  isPending: boolean;
  isFetching: boolean;
  error: unknown;
  refetch: () => unknown;
}
function StatContent({
  query,
  empty,
  children,
}: {
  query: QueryState;
  empty: boolean;
  children: ReactNode;
}) {
  if (query.isPending) return <Loading label="Loading statistics…" />;
  if (query.error)
    return (
      <ErrorNotice error={query.error} retry={() => void query.refetch()} />
    );
  if (empty)
    return (
      <Empty
        title="No data yet"
        detail="No records were returned for this selection."
      />
    );
  return (
    <>
      {query.isFetching && (
        <LinearProgress aria-label="Refreshing statistics" />
      )}
      {children}
    </>
  );
}
const numeric = (value: number) =>
  value.toLocaleString(undefined, { maximumFractionDigits: 3 });
const time = (value: string) => new Date(value).toLocaleString();

function Benchmark() {
  const query = useStorageBenchmark();
  const [profile, setProfile] = useState<BenchmarkProfile>("normal");
  const [metric, setMetric] = useState<BenchmarkMetric>("p95Ms");
  const rows = query.data?.filter((row) => row.profile === profile) ?? [];
  return (
    <Paper variant="outlined" sx={{ p: 3, minWidth: 0 }}>
      <Stack
        direction={{ xs: "column", md: "row" }}
        gap={2}
        justifyContent="space-between"
        mb={1}
      >
        <Box>
          <Typography variant="h6" component="h2">
            Storage benchmark matrix
          </Typography>
          <Typography variant="body2" color="text.secondary">
            Category × storage · latency, throughput and request error rate
          </Typography>
        </Box>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={profile}
          aria-label="Benchmark load"
          onChange={(_, value: BenchmarkProfile | null) => {
            if (value) setProfile(value);
          }}
        >
          <ToggleButton value="normal">Normal</ToggleButton>
          <ToggleButton value="peak">Peak</ToggleButton>
        </ToggleButtonGroup>
      </Stack>
      <TextField
        select
        label="Heatmap metric"
        value={metric}
        onChange={(event) => setMetric(event.target.value as BenchmarkMetric)}
        slotProps={{ select: { native: true } }}
        sx={{ my: 2, minWidth: 220 }}
      >
        {Object.entries(BENCHMARK_METRICS).map(([key, name]) => (
          <option key={key} value={key}>
            {name}
          </option>
        ))}
      </TextField>
      <StatContent query={query} empty={rows.length === 0}>
        {!!rows.length && (
          <StatisticsChart
            option={benchmarkOption(rows, metric)}
            label={`${label(profile)} load: ${BENCHMARK_METRICS[metric]} by category and storage`}
          />
        )}
        <TableContainer>
          <Table
            size="small"
            aria-label={`${label(profile)} storage benchmark matrix`}
          >
            <TableHead>
              <TableRow>
                <TableCell>Category</TableCell>
                {STORAGES.map((storage) => (
                  <TableCell key={storage}>{storage.toUpperCase()}</TableCell>
                ))}
              </TableRow>
            </TableHead>
            <TableBody>
              {CATEGORIES.map((category) => (
                <TableRow key={category}>
                  <TableCell component="th" scope="row">
                    {label(category)}
                  </TableCell>
                  {STORAGES.map((storage) => {
                    const row = rows.find(
                      (row) =>
                        row.category === category && row.storage === storage,
                    );
                    return (
                      <TableCell key={storage} sx={{ minWidth: 190 }}>
                        {row ? (
                          <>
                            <Typography variant="body2">
                              p50 {numeric(row.p50Ms)} / p95{" "}
                              {numeric(row.p95Ms)} / p99 {numeric(row.p99Ms)} ms
                            </Typography>
                            <Typography
                              variant="caption"
                              color="text.secondary"
                            >
                              {numeric(row.throughputMiBps)} MiB/s ·{" "}
                              {numeric(row.errorRate * 100)}% errors
                            </Typography>
                          </>
                        ) : (
                          "No data yet"
                        )}
                      </TableCell>
                    );
                  })}
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </StatContent>
    </Paper>
  );
}

function Recommendations() {
  const query = useStorageRecommendations();
  return (
    <Paper variant="outlined" sx={{ p: 3 }}>
      <Typography variant="h6" component="h2" mb={1}>
        Storage recommendations
      </Typography>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Per-category recommendations and the reasons returned by the service.
      </Typography>
      <StatContent query={query} empty={!query.data?.length}>
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", sm: "1fr 1fr" },
            gap: 2,
          }}
        >
          {CATEGORIES.map((category) => {
            const item = query.data?.find((item) => item.category === category);
            return (
              <Box
                key={category}
                sx={{
                  p: 2,
                  border: "1px solid",
                  borderColor: "divider",
                  borderRadius: 2,
                }}
              >
                <Stack
                  direction="row"
                  alignItems="center"
                  justifyContent="space-between"
                  gap={1}
                  mb={1.5}
                >
                  <Typography variant="subtitle2">{label(category)}</Typography>
                  {item && (
                    <Chip
                      size="small"
                      label={item.storage.toUpperCase()}
                      color="primary"
                      variant="outlined"
                    />
                  )}
                </Stack>
                <Typography variant="body2" color="text.secondary">
                  {item?.reason ?? "No data yet"}
                </Typography>
              </Box>
            );
          })}
        </Box>
      </StatContent>
    </Paper>
  );
}

function Meters({ region }: { region: Region }) {
  const query = useMeterConsumption(region);
  const [selected, setSelected] = useState("");
  const meter =
    query.data?.find((meter) => meter.id === selected) ?? query.data?.[0];
  const missing =
    meter?.readings.filter((reading) => reading.kWh === null).length ?? 0;
  const flagged =
    meter?.readings.filter(
      (reading) => reading.anomaly === "spike" || reading.anomaly === "zero",
    ).length ?? 0;
  return (
    <Paper variant="outlined" sx={{ p: 3, minWidth: 0 }}>
      <Typography variant="h6" component="h2" mb={1}>
        Meter consumption
      </Typography>
      <Typography variant="body2" color="text.secondary" mb={2}>
        Interval energy in {REGION_INFO[region].name}. Diamonds mark anomalies;
        shaded windows mark missing readings.
      </Typography>
      <StatContent query={query} empty={!query.data?.length}>
        {meter && (
          <>
            <Stack
              direction={{ xs: "column", sm: "row" }}
              gap={2}
              alignItems={{ sm: "center" }}
              mb={2}
            >
              <TextField
                select
                label="Meter"
                value={meter.id}
                onChange={(event) => setSelected(event.target.value)}
                slotProps={{ select: { native: true } }}
                sx={{ minWidth: 240 }}
              >
                {query.data?.map((meter) => (
                  <option key={meter.id} value={meter.id}>
                    {meter.label} · {meter.id}
                  </option>
                ))}
              </TextField>
              <Typography variant="body2" color="text.secondary">
                {meter.intervalMinutes}-minute intervals · {flagged} anomalies ·{" "}
                {missing} missing readings
              </Typography>
            </Stack>
            {meter.readings.length ? (
              <>
                <StatisticsChart
                  option={meterOption(meter)}
                  label={`Consumption for ${meter.label}, including ${flagged} anomalies and ${missing} missing readings`}
                  height={360}
                />
                <Box component="details" sx={{ mt: 2 }}>
                  <summary>View meter readings</summary>
                  <TableContainer>
                    <Table size="small" aria-label="Meter readings">
                      <TableHead>
                        <TableRow>
                          <TableCell>Time</TableCell>
                          <TableCell>kWh</TableCell>
                          <TableCell>Observation</TableCell>
                        </TableRow>
                      </TableHead>
                      <TableBody>
                        {meter.readings.map((reading) => (
                          <TableRow key={reading.timestamp}>
                            <TableCell>{time(reading.timestamp)}</TableCell>
                            <TableCell>
                              {reading.kWh === null
                                ? "Missing"
                                : numeric(reading.kWh)}
                            </TableCell>
                            <TableCell>{reading.anomaly ?? "—"}</TableCell>
                          </TableRow>
                        ))}
                      </TableBody>
                    </Table>
                  </TableContainer>
                </Box>
              </>
            ) : (
              <Empty
                title="No data yet"
                detail="This meter has no readings in the reported time window."
              />
            )}
          </>
        )}
      </StatContent>
    </Paper>
  );
}

function Hotspots({ region }: { region: Region }) {
  const query = useOutageHotspots(region);
  const [mode, setMode] = useState<HotspotMode>("heat");
  return (
    <Paper variant="outlined" sx={{ p: 3, minWidth: 0 }}>
      <Stack
        direction={{ xs: "column", sm: "row" }}
        gap={2}
        justifyContent="space-between"
        mb={2}
      >
        <Box>
          <Typography variant="h6" component="h2">
            Outage hotspots
          </Typography>
          <Typography variant="body2" color="text.secondary">
            {REGION_INFO[region].name} · concentration weighted by outage count
          </Typography>
        </Box>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={mode}
          aria-label="Hotspot map layer"
          onChange={(_, value: HotspotMode | null) => {
            if (value) setMode(value);
          }}
        >
          <ToggleButton value="heat">Heat</ToggleButton>
          <ToggleButton value="clusters">Clusters</ToggleButton>
        </ToggleButtonGroup>
      </Stack>
      <StatContent query={query} empty={!query.data?.length}>
        {!!query.data?.length && (
          <HotspotMap rows={query.data} region={region} mode={mode} />
        )}
        <Typography
          variant="caption"
          color="text.secondary"
          component="p"
          sx={{ my: 1.5 }}
        >
          {mode === "heat"
            ? "Heat legend: green → yellow → red indicates increasing relative concentration. Zoom in to inspect individual assets."
            : "Cluster labels show total outages, summed across grouped assets. Click a cluster to zoom in."}
        </Typography>
        <TableContainer>
          <Table size="small" aria-label="Outage hotspot ranking">
            <TableHead>
              <TableRow>
                <TableCell>Asset</TableCell>
                <TableCell>Outages</TableCell>
                <TableCell>Total outage minutes</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {query.data?.map((row) => (
                <TableRow key={row.id}>
                  <TableCell>{row.assetName}</TableCell>
                  <TableCell>{numeric(row.outageCount)}</TableCell>
                  <TableCell>{numeric(row.durationMinutes)}</TableCell>
                </TableRow>
              ))}
            </TableBody>
          </Table>
        </TableContainer>
      </StatContent>
    </Paper>
  );
}

function Forecast({ region }: { region: Region }) {
  const query = useForecast(region);
  const mode = useDataMode();
  return (
    <Paper variant="outlined" sx={{ p: 3, minWidth: 0 }}>
      <Stack direction="row" alignItems="center" gap={2} mb={1}>
        <Typography variant="h6" component="h2">
          Regional consumption forecast
        </Typography>
        {mode === "mock" && (
          <Chip size="small" label="MOCK FORECAST" color="warning" />
        )}
      </Stack>
      <Typography variant="body2" color="text.secondary" mb={2}>
        {REGION_INFO[region].name} ·{" "}
        {mode === "mock" ? "Synthetic example with" : "Estimate with"} 80% and
        95% prediction intervals. Lighter shading shows the wider 95% band.
      </Typography>
      <StatContent query={query} empty={!query.data?.length}>
        {!!query.data?.length && (
          <>
            <StatisticsChart
              option={forecastOption(query.data)}
              label={`Regional consumption forecast for ${REGION_INFO[region].name} with 80% and 95% prediction intervals`}
              height={360}
            />
            <Box component="details" sx={{ mt: 2 }}>
              <summary>View forecast values</summary>
              <TableContainer>
                <Table size="small" aria-label="Forecast values">
                  <TableHead>
                    <TableRow>
                      {[
                        "Time",
                        "Estimate (kWh)",
                        "80% lower",
                        "80% upper",
                        "95% lower",
                        "95% upper",
                      ].map((name) => (
                        <TableCell key={name}>{name}</TableCell>
                      ))}
                    </TableRow>
                  </TableHead>
                  <TableBody>
                    {query.data.map((point) => (
                      <TableRow key={point.timestamp}>
                        <TableCell>{time(point.timestamp)}</TableCell>
                        {[
                          point.estimate,
                          point.lower80,
                          point.upper80,
                          point.lower95,
                          point.upper95,
                        ].map((value, index) => (
                          <TableCell key={index}>{numeric(value)}</TableCell>
                        ))}
                      </TableRow>
                    ))}
                  </TableBody>
                </Table>
              </TableContainer>
            </Box>
          </>
        )}
      </StatContent>
    </Paper>
  );
}

export function StatisticsPage() {
  const { region } = useRegion();
  return (
    <>
      <PageHeading
        eyebrow="OPERATIONAL INTELLIGENCE"
        title="Evidence behind the decisions."
        detail={`Storage benchmarks cover all regions. Meter, outage and forecast views follow ${REGION_INFO[region].name}.`}
        action={<MapLinkButton />}
      />
      <Stack spacing={3}>
        <Benchmark />
        <Recommendations />
        <Meters region={region} />
        <Hotspots region={region} />
        <Forecast region={region} />
      </Stack>
    </>
  );
}
