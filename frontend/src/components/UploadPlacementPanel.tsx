import { useState } from "react";
import { Alert, Button, Paper, Stack, TextField, Typography } from "@mui/material";
import { useCreateIssue } from "../data/hooks";
import type { CreateIssue, FileRecord, Issue } from "../data/models";
import { label } from "../data/models";
import { ErrorNotice } from "./common";

export type PlacementPoint = Pick<CreateIssue, "coordinates" | "regionId" | "segmentId">;

export function UploadPlacementPanel({
  file, point, message, onCancel, onCreated, onView,
}: {
  file: FileRecord;
  point?: PlacementPoint;
  message: string;
  onCancel: () => void;
  onCreated: (issue: Issue) => void;
  onView: () => void;
}) {
  const create = useCreateIssue();
  const [title, setTitle] = useState(file.name);
  const [capturedAt, setCapturedAt] = useState(
    () => new Date(file.capturedAt ?? Date.now()).toISOString().slice(0, -1),
  );
  const [description, setDescription] = useState(file.description ?? "");
  const [error, setError] = useState("");
  const eligible = ["DRONE_VIDEO", "OUTAGE_RECORD"].includes(file.category);
  return (
    <Paper variant="outlined" sx={{ p: 2.3 }}>
      <Stack component="form" spacing={2} onSubmit={(event) => {
        event.preventDefault();
        setError("");
        const timestamp = Date.parse(capturedAt + "Z");
        if (!point?.coordinates || !Number.isFinite(timestamp) || timestamp > Date.now() ||
            description.length > 1000 || !title.trim()) {
          setError("Choose a map location, a title and a valid capture timestamp that is not in the future.");
          return;
        }
        create.mutate({
          ...point,
          fileId: file.id,
          type: file.category === "DRONE_VIDEO" ? "DRONE_DETECTED" : "OUTAGE_VIDEO",
          severity: "MEDIUM",
          title: title.trim(),
          description,
          capturedAt: new Date(timestamp).toISOString(),
        }, { onSuccess: onCreated });
      }}>
        <Typography variant="h6">Place uploaded issue</Typography>
        <Typography sx={{ overflowWrap: "anywhere" }}>{file.name}</Typography>
        <Typography variant="body2">{label(file.category)}</Typography>
        <Typography>Click on the map to set the issue location</Typography>
        <TextField label="Issue title" value={title} required
          onChange={(event) => setTitle(event.target.value)}
          slotProps={{ htmlInput: { maxLength: 512 } }} />
        <TextField label="Capture timestamp (UTC)" type="datetime-local" required value={capturedAt}
          onChange={(event) => setCapturedAt(event.target.value)}
          slotProps={{ inputLabel: { shrink: true }, htmlInput: { max: new Date().toISOString().slice(0, -1), step: "any" } }} />
        <TextField label="Description (optional)" multiline rows={3} value={description}
          onChange={(event) => setDescription(event.target.value)}
          slotProps={{ htmlInput: { maxLength: 1000 } }} />
        {point?.coordinates && <Typography variant="caption">
          Location: {point.coordinates[0].toFixed(6)}, {point.coordinates[1].toFixed(6)}
        </Typography>}
        {!eligible && <Alert severity="error">This category cannot be placed on the map.</Alert>}
        {file.status !== "READY" && <Alert severity="warning">The file must be READY before confirming.</Alert>}
        {file.placedIssueId && <Alert severity="info">This file already has an issue. Confirm opens the existing issue.</Alert>}
        {message && <Alert severity="warning">{message}</Alert>}
        {error && <Alert severity="error">{error}</Alert>}
        {create.error && <ErrorNotice error={create.error} />}
        <Button onClick={onView}>View</Button>
        <Stack direction="row" gap={1}>
          <Button type="submit" variant="contained"
            disabled={!eligible || file.status !== "READY" || !point?.coordinates || !!message || create.isPending}>
            {create.isPending ? "Confirming…" : "Confirm"}
          </Button>
          <Button onClick={onCancel} disabled={create.isPending}>Cancel</Button>
        </Stack>
      </Stack>
    </Paper>
  );
}
