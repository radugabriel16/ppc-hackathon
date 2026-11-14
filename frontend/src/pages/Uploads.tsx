import { useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  FormControlLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  TextField,
  Typography,
} from "@mui/material";
import {
  CloudUploadOutlined,
  Pause,
  PlayArrow,
  Replay,
  UploadFile,
} from "@mui/icons-material";
import {
  useCases,
  useDemoMode,
  useFile,
  useFiles,
  useMap,
} from "../data/hooks";
import { useSource } from "../data/context";
import type { FileUploadMetadata } from "../api/gen/types.gen";
import { useUploadQueue } from "../data/uploads";
import { useRegion } from "../data/region-context";
import { bytes, CATEGORIES, label } from "../data/models";
import type { Category } from "../data/models";
import type { SavedUpload } from "../upload/types";
import {
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  StatusChip,
} from "../components/common";
import { VerificationDialog } from "./Files";

function UploadResult({ id }: { id: string }) {
  const query = useFile(id);
  return (
    <Stack gap={1}>
      {query.data && (
        <Stack direction="row" gap={1.5} alignItems="center">
          <StatusChip status={query.data.status} />
          <Typography variant="caption" color="text.secondary">
            {query.data.status === "VERIFYING"
              ? "All parts received. Checking file integrity…"
              : query.data.status === "READY"
                ? "Integrity verified. Ready for use."
                : "Integrity failed. Select and upload the file again."}
          </Typography>
        </Stack>
      )}
      {query.error && <ErrorNotice error={query.error} />}
    </Stack>
  );
}
export function UploadsPage() {
  const { region } = useRegion();
  const demo = useDemoMode();
  const source = useSource();
  const queue = useUploadQueue();
  const [category, setCategory] = useState<Category>(
    demo ? "METER_READING" : "OUTAGE_RECORD",
  );
  const map = useMap(region);
  const cases = useCases({ region, search: "", page: 0, size: 100 });
  const documentTypes = useQuery({
    queryKey: ["document-types"],
    queryFn: () => source.getDocumentTypes!(),
    enabled: !!source.getDocumentTypes,
  });
  const [assetId, setAssetId] = useState("");
  const [caseId, setCaseId] = useState("");
  const [documentTypeId, setDocumentTypeId] = useState("");
  const [occurredAt, setOccurredAt] = useState(() =>
    new Date().toISOString().slice(0, 16),
  );
  const [severity, setSeverity] = useState("MEDIUM");
  const [description, setDescription] = useState("");
  const [inputError, setInputError] = useState("");
  const [corrupt, setCorrupt] = useState(false);
  const [dragging, setDragging] = useState(false);
  const [verify, setVerify] = useState("");
  const picker = useRef<HTMLInputElement>(null);
  const resumePicker = useRef<HTMLInputElement>(null);
  const resumeRecord = useRef<SavedUpload | undefined>(undefined);
  const history = useFiles({ region, search: "", page: 0, size: 8 });
  const addFiles = (files: FileList | null) => {
    setInputError("");
    let metadata: FileUploadMetadata | undefined;
    if (!demo) {
      if (category === "CONNECTION_DOCUMENT") {
        if (
          !cases.data?.items.some((item) => item.id === caseId) ||
          !documentTypeId
        ) {
          setInputError("Select a connection case and document type.");
          return;
        }
        metadata = { category, caseId, documentTypeId };
      } else {
        if (
          !map.data?.assetList.some((item) => item.id === assetId) ||
          !Number.isFinite(Date.parse(occurredAt + "Z"))
        ) {
          setInputError("Select an asset and a valid UTC timestamp.");
          return;
        }
        const timestamp = new Date(occurredAt + "Z").toISOString();
        if (category === "DRONE_VIDEO")
          metadata = { category, assetId, recordedAt: timestamp };
        else if (category === "OUTAGE_RECORD")
          metadata = {
            category,
            assetId,
            startedAt: timestamp,
            severity,
            description,
          };
        else {
          setInputError(
            "Meter readings must use the simulator ingest endpoint.",
          );
          return;
        }
      }
    }
    if (files)
      for (const file of Array.from(files))
        queue.add(file, category, region, corrupt, undefined, metadata);
  };
  const liveNames = new Set(
    queue.items
      .filter((x) => !["verifying", "cancelled"].includes(x.snapshot.state))
      .map((x) => x.name),
  );
  const pending = queue.saved.filter((x) => !liveNames.has(x.fileName));
  return (
    <>
      <PageHeading
        eyebrow="RELIABLE FILE INGESTION"
        title="Big files. Small worries."
        detail="Resumable uploads with a SHA-256 check on every part and every file."
      />
      <Paper variant="outlined" sx={{ p: 3, mb: 2.5 }}>
        <Stack direction={{ xs: "column", md: "row" }} spacing={3}>
          <Box sx={{ flex: 1 }}>
            <Typography variant="h6" mb={0.5}>
              Add to your evidence library
            </Typography>
            <Typography variant="body2" color="text.secondary" mb={2}>
              Destination: {label(region)} · Choose a category before adding
              files.
            </Typography>
            <TextField
              select
              fullWidth
              label="File category"
              value={category}
              onChange={(e) => setCategory(e.target.value as Category)}
            >
              {CATEGORIES.filter((c) => demo || c !== "METER_READING").map(
                (c) => (
                  <MenuItem key={c} value={c}>
                    {label(c)}
                  </MenuItem>
                ),
              )}
            </TextField>
            {!demo && (
              <Stack spacing={2} mt={2}>
                {category === "CONNECTION_DOCUMENT" ? (
                  <>
                    <TextField
                      select
                      label="Connection case"
                      value={caseId}
                      onChange={(e) => setCaseId(e.target.value)}
                    >
                      {cases.data?.items.map((item) => (
                        <MenuItem key={item.id} value={item.id}>
                          {item.title}
                        </MenuItem>
                      ))}
                    </TextField>
                    <TextField
                      select
                      label="Document type"
                      value={documentTypeId}
                      onChange={(e) => setDocumentTypeId(e.target.value)}
                    >
                      {documentTypes.data?.map((item) => (
                        <MenuItem key={item.id} value={item.id}>
                          {item.name}
                        </MenuItem>
                      ))}
                    </TextField>
                    {cases.error && <ErrorNotice error={cases.error} />}
                    {documentTypes.error && (
                      <ErrorNotice error={documentTypes.error} />
                    )}
                  </>
                ) : (
                  <>
                    <TextField
                      select
                      label="Network asset"
                      value={assetId}
                      onChange={(e) => setAssetId(e.target.value)}
                    >
                      {map.data?.assetList.map((item) => (
                        <MenuItem key={item.id} value={item.id}>
                          {item.name}
                        </MenuItem>
                      ))}
                    </TextField>
                    <TextField
                      label={
                        category === "DRONE_VIDEO"
                          ? "Recorded at (UTC)"
                          : "Started at (UTC)"
                      }
                      type="datetime-local"
                      value={occurredAt}
                      onChange={(e) => setOccurredAt(e.target.value)}
                      slotProps={{ inputLabel: { shrink: true } }}
                    />
                    {map.error && <ErrorNotice error={map.error} />}
                    {category === "OUTAGE_RECORD" && (
                      <>
                        <TextField
                          select
                          label="Outage severity"
                          value={severity}
                          onChange={(e) => setSeverity(e.target.value)}
                        >
                          {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((item) => (
                            <MenuItem key={item} value={item}>
                              {label(item)}
                            </MenuItem>
                          ))}
                        </TextField>
                        <TextField
                          label="Outage description"
                          value={description}
                          onChange={(e) => setDescription(e.target.value)}
                        />
                      </>
                    )}
                  </>
                )}
                <Typography variant="caption" color="text.secondary">
                  Drone videos use resumable uploads. Documents and outage
                  records upload directly. Meter readings are ingested by the
                  simulator, not this form.
                </Typography>
              </Stack>
            )}
            {demo && (
              <FormControlLabel
                sx={{ mt: 1 }}
                control={
                  <Checkbox
                    size="small"
                    checked={corrupt}
                    onChange={(e) => setCorrupt(e.target.checked)}
                  />
                }
                label={
                  <Typography variant="caption">
                    Simulate a corrupt file after verification
                  </Typography>
                }
              />
            )}
          </Box>
          <Box
            role="region"
            aria-label="File drop area"
            onDragOver={(e) => {
              e.preventDefault();
              setDragging(true);
            }}
            onDragLeave={() => setDragging(false)}
            onDrop={(e) => {
              e.preventDefault();
              setDragging(false);
              addFiles(e.dataTransfer.files);
            }}
            sx={{
              flex: 1.5,
              border: "1.5px dashed",
              borderColor: dragging ? "primary.main" : "#cad6c7",
              bgcolor: dragging ? "#e5efdd" : "#f7faf3",
              borderRadius: 2,
              p: 3,
              textAlign: "center",
            }}
          >
            <CloudUploadOutlined
              sx={{ fontSize: 36, color: "primary.main", mb: 0.5 }}
            />
            <Typography fontWeight={600}>
              Drop files into your workspace
            </Typography>
            <Typography
              variant="caption"
              display="block"
              color="text.secondary"
              mb={1.5}
            >
              or choose files from your device
            </Typography>
            <Button
              variant="contained"
              startIcon={<UploadFile />}
              onClick={() => picker.current?.click()}
            >
              Choose files
            </Button>
            <input
              ref={picker}
              type="file"
              multiple
              hidden
              aria-label="Choose files to upload"
              onChange={(e) => {
                addFiles(e.target.files);
                e.target.value = "";
              }}
            />
          </Box>
        </Stack>
      </Paper>
      <Stack
        direction="row"
        spacing={2}
        sx={{ mb: 2.5, px: 1, flexWrap: "wrap" }}
      >
        {[
          "3 parallel parts",
          "Worker SHA-256",
          "Automatic retry",
          "Reload & resume",
        ].map((text) => (
          <Typography key={text} variant="caption" color="text.secondary">
            ✓ {text}
          </Typography>
        ))}
      </Stack>
      <Alert severity="info" sx={{ mb: 2.5 }}>
        Navigating away pauses active uploads. After a reload, reselect the
        original file to resume; only missing parts are sent.
        {demo &&
          " The demo server simulates a 20% transient part failure rate."}
      </Alert>
      {queue.error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {queue.error}
        </Alert>
      )}
      {inputError && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {inputError}
        </Alert>
      )}
      {queue.savedError && <ErrorNotice error={queue.savedError} />}
      <Stack spacing={2} mb={3}>
        {queue.items.map((item) => {
          const s = item.snapshot;
          const active = ["hashing", "uploading", "completing"].includes(
            s.state,
          );
          const progress = s.totalBytes
            ? (s.sentBytes / s.totalBytes) * 100
            : s.state === "verifying"
              ? 100
              : 0;
          return (
            <Paper variant="outlined" sx={{ p: 2.5 }} key={item.key}>
              <Stack
                direction={{ xs: "column", sm: "row" }}
                justifyContent="space-between"
                gap={2}
              >
                <Box sx={{ flex: 1 }}>
                  <Stack direction="row" gap={1.5} alignItems="center">
                    <UploadFile color="primary" />
                    <Typography
                      variant="body2"
                      fontWeight={600}
                      sx={{ overflowWrap: "anywhere" }}
                    >
                      {item.name}
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {label(s.state)}
                    </Typography>
                  </Stack>
                  <LinearProgress
                    variant={
                      s.state === "hashing" || s.state === "completing"
                        ? "indeterminate"
                        : "determinate"
                    }
                    value={progress}
                    sx={{ height: 6, borderRadius: 5, my: 1.8 }}
                  />
                  <Stack
                    direction="row"
                    justifyContent="space-between"
                    flexWrap="wrap"
                    gap={1}
                  >
                    <Typography variant="caption" color="text.secondary">
                      {bytes(s.sentBytes)} / {bytes(s.totalBytes)} ·{" "}
                      {Math.round(progress)}%
                    </Typography>
                    <Typography variant="caption" color="text.secondary">
                      {bytes(Math.round(s.speed))}/s · {s.retries} retries
                    </Typography>
                  </Stack>
                </Box>
                <Stack direction="row" alignItems="center" spacing={1}>
                  {active && (
                    <Button
                      size="small"
                      startIcon={<Pause />}
                      onClick={() => item.engine.pause()}
                    >
                      Pause
                    </Button>
                  )}
                  {["paused", "failed"].includes(s.state) && (
                    <Button
                      size="small"
                      startIcon={<PlayArrow />}
                      onClick={() => void item.engine.resume()}
                    >
                      Resume
                    </Button>
                  )}
                  {!["verifying", "cancelled"].includes(s.state) && (
                    <Button
                      size="small"
                      color="error"
                      onClick={() => void item.engine.cancel()}
                    >
                      Cancel
                    </Button>
                  )}
                  {["failed", "cancelled", "verifying"].includes(s.state) && (
                    <Button
                      size="small"
                      onClick={() => queue.dismiss(item.key)}
                    >
                      Dismiss
                    </Button>
                  )}
                </Stack>
              </Stack>
              {s.error && (
                <Alert severity="error" sx={{ mt: 2 }}>
                  {s.error}
                </Alert>
              )}
              {s.fileId && (
                <Box mt={2}>
                  <UploadResult id={s.fileId} />
                </Box>
              )}
            </Paper>
          );
        })}
      </Stack>
      {pending.length > 0 && (
        <Paper variant="outlined" sx={{ p: 2.5, mb: 3 }}>
          <Typography variant="h6" mb={0.5}>
            Pick up where you left off
          </Typography>
          <Typography variant="body2" color="text.secondary" mb={2}>
            Your browser requires you to choose the original file again. Its
            fingerprint is checked before resuming.
          </Typography>
          <Stack spacing={2}>
            {pending.map((record) => (
              <Stack
                direction={{ xs: "column", sm: "row" }}
                key={record.uploadId}
                justifyContent="space-between"
                gap={1}
              >
                <Box>
                  <Typography variant="body2" fontWeight={600}>
                    {record.fileName}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {bytes(record.sizeBytes)} · {label(record.category)} ·{" "}
                    {label(record.region)}
                  </Typography>
                </Box>
                <Stack direction="row" gap={1}>
                  <Button
                    size="small"
                    startIcon={<Replay />}
                    onClick={() => {
                      resumeRecord.current = record;
                      resumePicker.current?.click();
                    }}
                  >
                    Select original & resume
                  </Button>
                  <Button
                    color="error"
                    size="small"
                    onClick={() => void queue.discard(record)}
                  >
                    Discard
                  </Button>
                </Stack>
              </Stack>
            ))}
          </Stack>
          <input
            ref={resumePicker}
            hidden
            type="file"
            aria-label="Select original file to resume"
            onChange={(e) => {
              const file = e.target.files?.[0];
              const record = resumeRecord.current;
              if (file && record)
                queue.add(
                  file,
                  record.category,
                  record.region,
                  !!record.simulateCorrupt,
                  record,
                );
              e.target.value = "";
            }}
          />
        </Paper>
      )}
      <Paper variant="outlined" sx={{ p: 2.5 }}>
        <Typography variant="h6" mb={2}>
          Recent ingestion activity
        </Typography>
        {history.isPending && <Loading />}
        {history.error && (
          <ErrorNotice
            error={history.error}
            retry={() => void history.refetch()}
          />
        )}
        {history.data?.items.length === 0 && (
          <Empty
            title="Ready for your first upload"
            detail="Add files to start ingesting evidence."
          />
        )}
        <Stack spacing={1}>
          {history.data?.items.map((file) => (
            <Stack
              direction="row"
              alignItems="center"
              justifyContent="space-between"
              gap={2}
              key={file.id}
              sx={{
                py: 1.2,
                borderBottom: "1px solid",
                borderColor: "divider",
              }}
            >
              <Box sx={{ minWidth: 0 }}>
                <Typography
                  variant="body2"
                  fontWeight={600}
                  sx={{ overflowWrap: "anywhere" }}
                >
                  {file.name}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {bytes(file.sizeBytes)} · {label(file.category)}
                </Typography>
              </Box>
              <Stack direction="row" gap={1} alignItems="center">
                <StatusChip status={file.status} />
                <Button size="small" onClick={() => setVerify(file.id)}>
                  Report
                </Button>
              </Stack>
            </Stack>
          ))}
        </Stack>
      </Paper>
      {verify && (
        <VerificationDialog id={verify} onClose={() => setVerify("")} />
      )}
    </>
  );
}
