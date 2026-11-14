import { useState } from "react";
import { useSearchParams, Link } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  IconButton,
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
  Tooltip,
  Typography,
} from "@mui/material";
import { EditOutlined, InfoOutlined } from "@mui/icons-material";
import { scopedForecastOption } from "../charts/options";
import { useGeography, useSession, useDataMode } from "../data/hooks";
import { useRegion } from "../data/region-context";
import {
  useEditThreshold,
  useForecastRun,
  useGenerateForecast,
  useThresholds,
} from "../data/forecast-hooks";
import { forecastRunInput, selectedAreaId } from "../data/scope";
import type { ForecastRun, GeographicArea } from "../data/models";
import { ErrorNotice } from "./common";
import { StatisticsChart } from "./StatisticsChart";

const numeric = (value: number) =>
  value.toLocaleString(undefined, { maximumFractionDigits: 3 });
function Provenance({
  baseline,
  bridged,
}: {
  baseline: boolean;
  bridged?: boolean;
}) {
  return (
    <Stack direction="row" gap={1} alignItems="center">
      {baseline ? (
        <Chip size="small" color="warning" label="BASELINE" />
      ) : (
        <Typography variant="caption">Model</Typography>
      )}
      {bridged && (
        <Tooltip title="today's missing intervals estimated">
          <InfoOutlined
            fontSize="small"
            aria-label="today's missing intervals estimated"
            color="action"
          />
        </Tooltip>
      )}
    </Stack>
  );
}

function ForecastResults({
  run,
  areas,
}: {
  run: ForecastRun;
  areas: GeographicArea[];
}) {
  return (
    <Stack gap={2}>
      <Typography variant="caption">
        Run {run.id} · {run.status} · UTC days · kWh/day
      </Typography>
      {run.status === "FAILED" && (
        <Alert severity="error">
          {run.error ?? "Forecast calculation failed."}
        </Alert>
      )}
      {run.segments.map((segment) => {
        const name =
          areas.find((area) => area.id === segment.segmentId)?.name ??
          segment.segment;
        return (
          <Box
            key={segment.segmentId}
            sx={{ borderTop: "1px solid", borderColor: "divider", pt: 2 }}
          >
            <Stack direction="row" alignItems="center" gap={2} flexWrap="wrap">
              <Typography variant="h6">{name}</Typography>
              <Provenance
                baseline={segment.fallbackUsed}
                bridged={segment.bridged}
              />
              <Typography variant="caption">{segment.modelVersion}</Typography>
            </Stack>
            <StatisticsChart
              option={scopedForecastOption(segment)}
              label={`Three-day forecast vs threshold for ${name}`}
              height={270}
            />
            <TableContainer>
              <Table size="small" aria-label={`Forecast totals for ${name}`}>
                <TableHead>
                  <TableRow>
                    {[
                      "Day (UTC)",
                      "Total (kWh)",
                      "Run threshold (kWh/day)",
                      "Excess (kWh)",
                      "Status / method",
                    ].map((name) => (
                      <TableCell key={name}>{name}</TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {segment.forecasts.map((day) => (
                    <TableRow key={day.date}>
                      <TableCell>
                        D+{day.horizon} · {day.date}
                      </TableCell>
                      <TableCell>
                        {day.predictedEnergyKwh === null
                          ? "Insufficient data"
                          : numeric(day.predictedEnergyKwh)}
                      </TableCell>
                      <TableCell>
                        {day.thresholdKwh ??
                          segment.thresholdKwh ??
                          "Not configured"}
                      </TableCell>
                      <TableCell>
                        {day.excessKwh == null ? "—" : numeric(day.excessKwh)}
                      </TableCell>
                      <TableCell>
                        <Typography variant="caption">
                          {day.status} · {day.eligibleMeters}/
                          {day.expectedMeters} meters
                        </Typography>
                        <Provenance
                          baseline={day.fallbackUsed}
                          bridged={day.bridged}
                        />
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          </Box>
        );
      })}
      <Typography variant="subtitle2">
        Created ML forecast issues ({run.createdIssues.length})
      </Typography>
      {run.createdIssues.map((issue) => {
        const params = new URLSearchParams({ issue: issue.id ?? "" });
        const segment = run.segments.find(
          (s) => s.segmentId === issue.segmentId,
        );
        const region = segment?.region.toUpperCase();
        if (region) params.set("region", region);
        if (issue.segmentId) params.set("segment", issue.segmentId);
        return (
          <Button
            key={issue.id}
            component={Link}
            to={`/map?${params}`}
            sx={{ justifyContent: "start", textAlign: "left" }}
          >
            {issue.title ?? issue.description}
          </Button>
        );
      })}
      {!run.createdIssues.length && run.status === "COMPLETED" && (
        <Typography variant="body2" color="text.secondary">
          No new issues. Exceedances already reported are not duplicated.
        </Typography>
      )}
    </Stack>
  );
}

export function ForecastPanel() {
  const { selectedRegion, subregionId } = useRegion();
  return <ScopedForecast key={`${selectedRegion}:${subregionId}`} />;
}

function ScopedForecast() {
  const { selectedRegion, subregionId } = useRegion();
  const mode = useDataMode();
  const geography = useGeography();
  const session = useSession();
  const areas = geography.data ?? [];
  const region = areas.find((a) => !a.parentId && a.region === selectedRegion);
  const selected = areas.find(
    (a) => a.id === selectedAreaId(areas, selectedRegion, subregionId),
  );
  const generate = useGenerateForecast();
  const thresholds = useThresholds();
  const edit = useEditThreshold();
  const [params, setParams] = useSearchParams();
  const query = useForecastRun(params.get("run") ?? undefined);
  const candidate = query.data ?? generate.data;
  const [editing, setEditing] = useState<{
    segmentId: string;
    name: string;
    value: string;
  } | null>(null);
  const [saveError, setSaveError] = useState("");
  const configs =
    thresholds.data?.filter(
      (t) =>
        (!selectedRegion || t.regionId === region?.id) &&
        (!subregionId || t.segmentId === subregionId),
    ) ?? [];
  const validScope =
    !selectedRegion ||
    (!!region && (!subregionId || selected?.parentId === region.id));
  const expected = forecastRunInput(region?.id, subregionId);
  const matchesScope =
    candidate?.scope === expected.scope &&
    (expected.scope !== "region" || candidate.regionId === expected.regionId) &&
    (expected.scope !== "segment" ||
      candidate.segmentId === expected.segmentId);
  const run = matchesScope ? candidate : undefined;
  const busy = generate.isPending || run?.status === "RUNNING";
  return (
    <Paper variant="outlined" sx={{ p: 2.5, minWidth: 0 }}>
      <Stack
        direction="row"
        justifyContent="space-between"
        gap={2}
        flexWrap="wrap"
        mb={2}
      >
        <Box>
          <Typography variant="h6">
            Scoped predictions · {selected?.name ?? "Romania"}
          </Typography>
          <Typography variant="body2" color="text.secondary">
            D+1 / D+2 / D+3 daily energy vs per-segment thresholds. Not an
            outage probability or kW capacity.
          </Typography>
        </Box>
        <Button
          variant="contained"
          disabled={busy || !validScope || mode === "demo"}
          onClick={() =>
            generate.mutate(forecastRunInput(region?.id, subregionId), {
              onSuccess: (result) =>
                setParams((previous) => {
                  const next = new URLSearchParams(previous);
                  next.set("run", result.id);
                  return next;
                }),
            })
          }
        >
          Generate predictions
        </Button>
      </Stack>
      {mode === "demo" && (
        <Alert severity="info">
          Forecast runs and thresholds require API mode.
        </Alert>
      )}
      {busy && (
        <Box role="status">
          <Typography>Generating predictions for the current scope…</Typography>
          <LinearProgress aria-label="Forecast run progress" />
        </Box>
      )}
      {generate.error && <ErrorNotice error={generate.error} />}
      {query.error && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {candidate && !matchesScope && (
        <Alert severity="warning">
          This saved run belongs to a different scope. Select its scope or
          generate new predictions.
        </Alert>
      )}
      {thresholds.error && (
        <ErrorNotice
          error={thresholds.error}
          retry={() => void thresholds.refetch()}
        />
      )}
      <Box component="details" open={!!subregionId} sx={{ my: 2 }}>
        <summary>Per-segment thresholds ({configs.length}) · kWh/day</summary>
        <Stack gap={1} mt={1}>
          {configs.map((config) => {
            const name =
              areas.find((a) => a.id === config.segmentId)?.name ??
              config.segmentId;
            return (
              <Stack
                key={config.segmentId}
                direction="row"
                gap={1}
                alignItems="center"
              >
                <Typography variant="body2">
                  {name}:{" "}
                  {config.dailyEnergyKwh == null
                    ? "Not configured"
                    : numeric(config.dailyEnergyKwh)}{" "}
                  kWh/day · {config.source ?? "Unknown source"}
                </Typography>
                {session.data?.user.role === "MANAGER" && config.segmentId && (
                  <IconButton
                    aria-label={`Edit threshold for ${name}`}
                    size="small"
                    onClick={() => {
                      edit.reset();
                      setSaveError("");
                      setEditing({
                        segmentId: config.segmentId!,
                        name: name ?? config.segmentId!,
                        value: String(config.dailyEnergyKwh ?? ""),
                      });
                    }}
                  >
                    <EditOutlined fontSize="small" />
                  </IconButton>
                )}
              </Stack>
            );
          })}
          {mode !== "demo" && !thresholds.isPending && !configs.length && (
            <Typography variant="body2">
              No configured thresholds returned.
            </Typography>
          )}
        </Stack>
      </Box>
      {run && <ForecastResults run={run} areas={areas} />}
      {editing && (
        <Dialog
          open
          onClose={edit.isPending ? undefined : () => setEditing(null)}
          fullWidth
          maxWidth="xs"
        >
          <Box
            component="form"
            onSubmit={(event) => {
              event.preventDefault();
              const value = Number(editing.value);
              if (!Number.isFinite(value) || value <= 0) {
                setSaveError("Use a positive finite daily threshold.");
                return;
              }
              edit.mutate(
                { segmentId: editing.segmentId, value },
                { onSuccess: () => setEditing(null) },
              );
            }}
          >
            <DialogTitle>Edit threshold · {editing.name}</DialogTitle>
            <DialogContent>
              <TextField
                autoFocus
                fullWidth
                sx={{ mt: 1 }}
                label="Daily energy threshold (kWh/day)"
                type="number"
                value={editing.value}
                onChange={(e) =>
                  setEditing({ ...editing, value: e.target.value })
                }
                required
                slotProps={{ htmlInput: { min: 0.001, step: "any" } }}
                error={!!saveError}
                helperText={
                  saveError ||
                  "Applies to future runs; existing runs keep their original threshold."
                }
              />
              {edit.error && <ErrorNotice error={edit.error} />}
            </DialogContent>
            <DialogActions>
              <Button
                disabled={edit.isPending}
                onClick={() => setEditing(null)}
              >
                Cancel
              </Button>
              <Button disabled={edit.isPending} type="submit">
                Save threshold
              </Button>
            </DialogActions>
          </Box>
        </Dialog>
      )}
    </Paper>
  );
}
