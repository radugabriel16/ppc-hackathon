import {
  Table, TableBody, TableCell, TableContainer, TableHead, TableRow,
} from "@mui/material";
import type { RawMeterReading } from "../data/models";

export function MeterReadingsTable({ readings }: { readings: RawMeterReading[] }) {
  return (
    <TableContainer>
      <Table size="small" aria-label="Individual ingested meter readings">
        <TableHead>
          <TableRow>
            <TableCell>Received at (server)</TableCell>
            <TableCell>Meter code / segment</TableCell>
            <TableCell>Reading timestamp (start / end)</TableCell>
            <TableCell>kWh</TableCell>
            <TableCell>Seq</TableCell>
            <TableCell>readingKey</TableCell>
          </TableRow>
        </TableHead>
        <TableBody>
          {readings.map((reading) => (
            <TableRow key={reading.id}>
              <TableCell sx={{ whiteSpace: "nowrap" }}>
                <time dateTime={reading.receivedAt}>{reading.receivedAt}</time>
              </TableCell>
              <TableCell>
                {reading.meterCode}
                <br />
                {reading.segmentCode
                  ? `${reading.segmentCode}${reading.segmentName ? ` / ${reading.segmentName}` : ""}`
                  : reading.segmentId ?? "No segment"}
              </TableCell>
              <TableCell sx={{ whiteSpace: "nowrap" }}>
                <time dateTime={reading.intervalStart}>{reading.intervalStart}</time>
                <br />
                <time dateTime={reading.intervalEnd}>{reading.intervalEnd}</time>
              </TableCell>
              <TableCell>{String(reading.energyKwh)}</TableCell>
              <TableCell>{reading.seq}</TableCell>
              <TableCell sx={{ overflowWrap: "anywhere" }}>{reading.readingKey}</TableCell>
            </TableRow>
          ))}
        </TableBody>
      </Table>
    </TableContainer>
  );
}
