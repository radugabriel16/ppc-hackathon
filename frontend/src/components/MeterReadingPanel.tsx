import { useState } from "react";
import {
  Box, LinearProgress, Stack, Table, TableBody, TableCell, TableContainer,
  TableHead, TablePagination, TableRow, ToggleButton, ToggleButtonGroup, Typography,
} from "@mui/material";
import { meterOption } from "../charts/options";
import {
  useMeterReadings, useMeterReadingWindow,
} from "../data/meter-readings-hooks";
import type { RawMeterReading, ReadingMeter, Region } from "../data/models";
import { Empty, ErrorNotice, Loading } from "./common";
import { MeterReadingsTable } from "./MeterReadingsTable";
import { StatisticsChart } from "./StatisticsChart";

type Interval = 15 | 60 | 1440;

function aggregateReadings(readings: RawMeterReading[], interval: Interval) {
  const buckets = new Map<number, { timestamp: string; end: string; kWh: number; count: number }>();
  const step = interval * 60000;
  for (const reading of readings) {
    const start = Math.floor(Date.parse(reading.intervalStart) / step) * step;
    const bucket = buckets.get(start) ?? {
      timestamp: new Date(start).toISOString(),
      end: new Date(start + step).toISOString(),
      kWh: 0,
      count: 0,
    };
    bucket.kWh += reading.energyKwh;
    bucket.count++;
    buckets.set(start, bucket);
  }
  return [...buckets.values()].sort((a, b) => a.timestamp.localeCompare(b.timestamp));
}

export function MeterReadingPanel({ meter, region }: { meter: ReadingMeter; region: Region }) {
  const [interval, setInterval] = useState<Interval>(15);
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(50);
  const window = useMeterReadingWindow(meter.id);
  const raw = useMeterReadings(
    { meterId: meter.id, order: "received_desc", page, size },
    false,
    interval === 15,
  );
  const readings = window.data?.readings ?? [];
  const aggregates = interval === 15 ? [] : aggregateReadings(readings, interval);
  const chartReadings = interval === 15
    ? readings.map((reading) => ({
        timestamp: reading.intervalStart, kWh: reading.energyKwh, anomaly: null,
      }))
    : aggregates.map((reading) => ({
        timestamp: reading.timestamp, kWh: reading.kWh, anomaly: null,
      }));
  const aggregateRows = [...aggregates].reverse().slice(page * size, (page + 1) * size);
  const tableQuery = interval === 15 ? raw : window;
  const total = interval === 15 ? raw.data?.totalElements ?? 0 : aggregates.length;
  return (
    <>
      <Stack direction={{ xs: "column", sm: "row" }} gap={2} alignItems={{ sm: "center" }} mb={2}>
        <ToggleButtonGroup
          exclusive
          size="small"
          value={interval}
          aria-label="Meter reading interval"
          onChange={(_, value: Interval | null) => {
            if (value !== null) {
              setInterval(value);
              setPage(0);
            }
          }}
        >
          <ToggleButton value={15}>Raw (15 min)</ToggleButton>
          <ToggleButton value={60}>1 h</ToggleButton>
          <ToggleButton value={1440}>1 day</ToggleButton>
        </ToggleButtonGroup>
        <Typography variant="body2" color="text.secondary">
          Chart: seven days ending at this meter&apos;s latest reading timestamp,
          not the current time.
        </Typography>
      </Stack>
      {window.isPending && <Loading label="Loading meter chart..." />}
      {window.error && <ErrorNotice error={window.error} retry={() => void window.refetch()} />}
      {window.isFetching && !window.isPending && <LinearProgress aria-label="Refreshing meter chart" />}
      {window.data && !readings.length && (
        <Empty title="No ingested readings" detail="This meter has no readings in catalog-db." />
      )}
      {!!chartReadings.length && window.data?.from && window.data.to && (
        <StatisticsChart
          option={{
            ...meterOption({
              id: meter.id, label: meter.code, region,
              intervalMinutes: interval, readings: chartReadings,
            }),
            xAxis: {
              type: "time",
              min: Date.parse(window.data.from),
              max: Date.parse(window.data.to),
            },
          }}
          label={`${meter.code}: ${interval === 15 ? "individual ingested readings" : `${interval}-minute energy totals`}`}
          height={360}
        />
      )}
      <Box component="details" sx={{ mt: 2 }}>
        <summary>View meter readings</summary>
        <Typography variant="body2" color="text.secondary" my={2}>
          {interval === 15
            ? "Individual catalog rows, newest server receipt first. Timestamps and kWh are shown without display rounding. Source and ingest result are not stored."
            : "UTC interval totals from the chart window, newest interval first. Boundary intervals may be partial; missing readings are not imputed."}
        </Typography>
        {tableQuery.isPending && <Loading label="Loading meter readings..." />}
        {tableQuery.error && <ErrorNotice error={tableQuery.error} retry={() => void tableQuery.refetch()} />}
        {tableQuery.isFetching && !tableQuery.isPending && <LinearProgress aria-label="Refreshing meter readings" />}
        {interval === 15 && raw.data && (
          <MeterReadingsTable readings={raw.data.items} />
        )}
        {interval !== 15 && window.data && (
          <TableContainer>
            <Table size="small" aria-label="Aggregated meter readings">
              <TableHead>
                <TableRow>
                  <TableCell>Interval start (UTC)</TableCell>
                  <TableCell>Interval end (UTC)</TableCell>
                  <TableCell>kWh (sum)</TableCell>
                  <TableCell>Individual readings</TableCell>
                </TableRow>
              </TableHead>
              <TableBody>
                {aggregateRows.map((row) => (
                  <TableRow key={row.timestamp}>
                    <TableCell>{row.timestamp}</TableCell>
                    <TableCell>{row.end}</TableCell>
                    <TableCell>{String(row.kWh)}</TableCell>
                    <TableCell>{row.count}</TableCell>
                  </TableRow>
                ))}
              </TableBody>
            </Table>
          </TableContainer>
        )}
        <TablePagination
          component="div"
          count={total}
          page={page}
          rowsPerPage={size}
          rowsPerPageOptions={[25, 50, 100]}
          onPageChange={(_, value) => setPage(value)}
          onRowsPerPageChange={(event) => {
            setSize(Number(event.target.value));
            setPage(0);
          }}
        />
      </Box>
    </>
  );
}
