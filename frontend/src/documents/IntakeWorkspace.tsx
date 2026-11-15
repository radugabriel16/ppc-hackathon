import { useEffect, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Alert,
  Badge,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  FormControlLabel,
  LinearProgress,
  MenuItem,
  Paper,
  Stack,
  Tab,
  Tabs,
  TextField,
  Typography,
  IconButton,
  TablePagination,
} from "@mui/material";
import { Close } from "@mui/icons-material";
import { useSource } from "../data/context";
import { validCnp } from "../data/document-intake";
import type {
  DocumentIntakeItem,
  IntakeDocumentType,
} from "../api/gen/types.gen";
import { AppError } from "../data/errors";

const TYPES: IntakeDocumentType[] = [
  "REQUEST_FORM",
  "CONNECTION_APPROVAL",
  "ID",
];
const typeLabel: Record<IntakeDocumentType, string> = {
  REQUEST_FORM: "Connection request",
  CONNECTION_APPROVAL: "Connection approval",
  ID: "Identity document",
};
export interface UploadSlot {
  customerId: string;
  documentType: IntakeDocumentType;
  customerName?: string;
}
const reasonLabels: Record<string, string> = {
  IDENTITY_DOCUMENT: "Identity documents always require a human check.",
  NO_EXTRACTABLE_TEXT: "No readable PDF text. Check the document manually.",
  UNRECOGNIZED_TYPE: "The title does not match a known document.",
  AMBIGUOUS_TYPE: "More than one document type appears in the title area.",
  CNP_MISSING: "The opening paragraph has no CNP.",
  CNP_INVALID: "The CNP is invalid.",
  CNP_AMBIGUOUS: "Multiple different CNPs were found.",
  CUSTOMER_NOT_FOUND: "No client matches the CNP.",
  TYPE_ALREADY_PRESENT:
    "This document type is already present. Explicit replacement is required.",
  CONTENT_MISMATCH:
    "The document content differs from the selected client or type.",
  UNSUPPORTED_FORMAT: "Unsupported file format.",
  PARSE_ERROR: "The PDF could not be read safely.",
};
const message = (e: unknown) =>
  e instanceof Error ? e.message : "The operation failed.";

export function IntakeWorkspace({
  slot,
  clearSlot,
  previewId,
  clearPreview,
}: {
  slot: UploadSlot | null;
  clearSlot: () => void;
  previewId: string | null;
  clearPreview: () => void;
}) {
  const source = useSource(),
    api = source.documentIntake,
    cache = useQueryClient();
  const [upload, setUpload] = useState<"single" | "batch" | null>(null);
  const [files, setFiles] = useState<File[]>([]),
    [busy, setBusy] = useState(false),
    [error, setError] = useState("");
  const [manual, setManual] = useState(false),
    [result, setResult] = useState(""),
    [batchId, setBatchId] = useState<string>();
  const [panel, setPanel] = useState(false),
    [queue, setQueue] = useState<"IDENTITY" | "MANUAL">("IDENTITY"),
    [page, setPage] = useState(0);
  const [selected, setSelected] = useState<string>(),
    [kind, setKind] = useState<IntakeDocumentType>("ID");
  const [cnp, setCnp] = useState(""),
    [matched, setMatched] = useState<{ name: string; cnp: string } | null>(
      null,
    ),
    [replace, setReplace] = useState(false);
  const [rejectReason, setRejectReason] = useState(""),
    [reviewBusy, setReviewBusy] = useState(false),
    [reviewError, setReviewError] = useState("");
  const [preview, setPreview] = useState<{ url: string; type: string } | null>(
      null,
    ),
    [previewError, setPreviewError] = useState("");
  const [reviewPreview, setReviewPreview] = useState<string | null>(null);
  const identity = useQuery({
    queryKey: ["document-reviews", "IDENTITY", queue === "IDENTITY" ? page : 0],
    enabled: !!api,
    queryFn: () => api!.reviews("IDENTITY", queue === "IDENTITY" ? page : 0),
    refetchInterval: 3000,
  });
  const other = useQuery({
    queryKey: ["document-reviews", "MANUAL", queue === "MANUAL" ? page : 0],
    enabled: !!api,
    queryFn: () => api!.reviews("MANUAL", queue === "MANUAL" ? page : 0),
    refetchInterval: 3000,
  });
  const batch = useQuery({
    queryKey: ["document-batch", batchId],
    enabled: !!api && !!batchId,
    queryFn: () => api!.getBatch(batchId!),
    refetchInterval: (q) =>
      q.state.data?.status === "COMPLETED" ? false : 2000,
  });
  const refresh = () =>
    Promise.all(
      [
        "cases",
        "document-reviews",
        "document-batch",
        "issues",
        "map",
        "files",
      ].map((key) => cache.invalidateQueries({ queryKey: [key] })),
    );
  useEffect(() => {
    if (batch.data?.autoLinkedCount)
      void cache.invalidateQueries({ queryKey: ["cases"] });
  }, [batch.data?.autoLinkedCount, cache]);
  const active = queue === "IDENTITY" ? identity : other;
  const item = active.data?.items?.find((i) => i.id === selected);
  const count =
    (identity.data?.totalElements ?? 0) + (other.data?.totalElements ?? 0);
  const effectiveUpload = slot ? "single" : upload;
  const fileId = previewId || reviewPreview;
  useEffect(() => {
    let cancelled = false,
      objectUrl: string | undefined;
    setPreview(null);
    setPreviewError("");
    if (fileId && source.downloadFile) {
      source
        .downloadFile(fileId, true)
        .then((blob) => {
          if (cancelled) return;
          if (
            !["application/pdf", "image/jpeg", "image/png"].includes(
              blob.type.split(";")[0],
            )
          ) {
            setPreviewError("Preview is available only for PDF, JPEG and PNG.");
            return;
          }
          objectUrl = URL.createObjectURL(blob);
          setPreview({ url: objectUrl, type: blob.type });
        })
        .catch((e) => {
          if (!cancelled) setPreviewError(message(e));
        });
    }
    return () => {
      cancelled = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [fileId, source]);
  const closeUpload = () => {
    setUpload(null);
    clearSlot();
    setFiles([]);
    setManual(false);
    setError("");
  };
  async function submit() {
    if (!api || !files.length) return;
    if (effectiveUpload === "single" && files.length !== 1) {
      setError("Choose exactly one file for Load Document.");
      return;
    }
    if (
      files.length > 50 ||
      files.reduce((n, f) => n + f.size, 0) > 200 * 1024 * 1024
    ) {
      setError("Maximum 50 files and 200 MiB per batch.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      if (effectiveUpload === "batch") {
        const r = await api.batch(files);
        setBatchId(r.batchId);
        setPanel(true);
      } else {
        const r = await api.upload(
          files[0],
          slot?.customerId,
          slot?.documentType,
          manual,
        );
        setResult(
          `${r.originalFileName}: ${r.status}${r.reviewReason ? " — " + reasonLabels[r.reviewReason] : ""}`,
        );
        if (r.status === "NEEDS_REVIEW") setPanel(true);
      }
      await refresh();
      closeUpload();
    } catch (e) {
      setError(message(e));
    } finally {
      setBusy(false);
    }
  }
  function selectItem(value: DocumentIntakeItem) {
    setSelected(value.id);
    setKind(value.detectedType ?? "ID");
    setCnp("");
    setMatched(null);
    setReplace(false);
    setRejectReason("");
    setReviewError("");
  }
  async function findCustomer() {
    if (!api || !validCnp(cnp)) return;
    setReviewBusy(true);
    setReviewError("");
    try {
      const r = await api.lookup(cnp);
      setMatched({ name: r.customerName, cnp });
    } catch (e) {
      setMatched(null);
      setReviewError(message(e));
    } finally {
      setReviewBusy(false);
    }
  }
  async function decide(confirm: boolean) {
    if (!api || !item) return;
    setReviewBusy(true);
    setReviewError("");
    try {
      if (confirm)
        await api.confirm(item.id, {
          documentType: kind,
          cnp,
          version: item.version,
          replaceExisting: replace,
        });
      else
        await api.reject(item.id, {
          reason: rejectReason,
          version: item.version,
        });
      await refresh();
      setSelected(undefined);
      setCnp("");
      setMatched(null);
    } catch (e) {
      if (e instanceof AppError && e.status === 409) {
        await refresh();
        setMatched(null);
        setReviewError(
          "This item changed. Reloaded; check it again before confirming.",
        );
      } else setReviewError(message(e));
    } finally {
      setReviewBusy(false);
    }
  }
  return (
    <>
      <Stack direction="row" gap={1} mb={2} flexWrap="wrap">
        <Button
          variant="contained"
          disabled={!api}
          onClick={() => {
            setUpload("single");
            setFiles([]);
          }}
        >
          Load Document
        </Button>
        <Button
          variant="outlined"
          disabled={!api}
          onClick={() => {
            setUpload("batch");
            setFiles([]);
          }}
        >
          Load Batch
        </Button>
        <Badge badgeContent={count} color="warning">
          <Button disabled={!api} onClick={() => setPanel(!panel)}>
            Review documents
          </Button>
        </Badge>
      </Stack>
      {!api && (
        <Alert severity="info">
          Document intake requires a connected API session.
        </Alert>
      )}
      {result && (
        <Alert severity="info" onClose={() => setResult("")}>
          {result}
        </Alert>
      )}
      {batch.data && (
        <Paper variant="outlined" sx={{ p: 2, mb: 2 }}>
          <Typography>Batch: {batch.data.status}</Typography>
          {batch.data.status === "PROCESSING" && (
            <LinearProgress sx={{ my: 1 }} />
          )}
          <Typography>
            Auto-linked: {batch.data.autoLinkedCount} · Needs review:{" "}
            {batch.data.items.filter((i) => i.status === "NEEDS_REVIEW").length}{" "}
            · Confirmed:{" "}
            {batch.data.items.filter((i) => i.status === "CONFIRMED").length} ·
            Failed: {batch.data.failedCount}
          </Typography>
          {batch.data.items.map((i) => (
            <Typography key={i.id} variant="body2">
              {i.originalFileName} — {i.status}
              {i.errorDetail ? ` (${i.errorDetail})` : ""}
            </Typography>
          ))}
        </Paper>
      )}
      {batch.error && <Alert severity="error">{message(batch.error)}</Alert>}
      <Dialog
        open={!!effectiveUpload}
        onClose={() => {
          if (!busy) closeUpload();
        }}
        fullWidth
      >
        <DialogTitle>
          {effectiveUpload === "batch" ? "Load Batch" : "Load Document"}
        </DialogTitle>
        <DialogContent>
          {slot && (
            <Stack gap={1} mb={2}>
              <TextField
                label="Customer"
                value={slot.customerName ?? slot.customerId}
                slotProps={{ input: { readOnly: true } }}
              />
              <TextField
                label="Document type"
                value={typeLabel[slot.documentType]}
                slotProps={{ input: { readOnly: true } }}
              />
            </Stack>
          )}
          <Box
            onDragOver={(e) => e.preventDefault()}
            onDrop={(e) => {
              e.preventDefault();
              if (!busy) setFiles(Array.from(e.dataTransfer.files));
            }}
            sx={{ p: 3, border: "1px dashed #8c9e92", borderRadius: 1 }}
          >
            <Typography mb={1}>Drop documents here or choose files</Typography>
            <input
              aria-label="Choose documents"
              type="file"
              multiple={effectiveUpload === "batch"}
              disabled={busy}
              onChange={(e) => setFiles(Array.from(e.target.files ?? []))}
            />
            {files.map((f, i) => (
              <Typography key={i} variant="body2">
                {f.name} — {busy ? "Uploading / processing" : "Ready to upload"}
              </Typography>
            ))}
          </Box>
          {slot && (
            <FormControlLabel
              control={
                <Checkbox
                  checked={manual}
                  onChange={(e) => setManual(e.target.checked)}
                />
              }
              label="I checked this document and confirm the selected customer and type if it has no readable text."
            />
          )}
          {busy && <LinearProgress sx={{ mt: 2 }} />}
          {error && <Alert severity="error">{error}</Alert>}
        </DialogContent>
        <DialogActions>
          <Button disabled={busy} onClick={closeUpload}>
            Cancel
          </Button>
          <Button
            disabled={busy || !files.length}
            onClick={() => void submit()}
          >
            Upload
          </Button>
        </DialogActions>
      </Dialog>
      {panel && api && (
        <Paper
          role="region"
          aria-label="Document review panel"
          elevation={8}
          sx={{
            position: "fixed",
            right: 16,
            bottom: 16,
            width: { xs: "calc(100% - 32px)", sm: 440 },
            maxHeight: "75vh",
            overflow: "auto",
            zIndex: 1200,
            p: 2,
          }}
        >
          <Stack direction="row" justifyContent="space-between">
            <Typography variant="h6">Document review</Typography>
            <IconButton
              aria-label="Close review panel"
              onClick={() => setPanel(false)}
            >
              <Close />
            </IconButton>
          </Stack>
          <Tabs
            value={queue}
            onChange={(_, value: "IDENTITY" | "MANUAL") => {
              setQueue(value);
              setPage(0);
              setSelected(undefined);
            }}
          >
            <Tab
              value="IDENTITY"
              label={`Identity documents (${identity.data?.totalElements ?? 0})`}
            />
            <Tab
              value="MANUAL"
              label={`Needs review (${other.data?.totalElements ?? 0})`}
            />
          </Tabs>
          {active.error && (
            <Alert severity="error">{message(active.error)}</Alert>
          )}
          {active.data?.items?.map((i) => (
            <Button
              key={i.id}
              fullWidth
              onClick={() => selectItem(i)}
              sx={{ justifyContent: "flex-start", textTransform: "none" }}
            >
              {i.originalFileName}
            </Button>
          ))}
          {!active.data?.items?.length && (
            <Typography sx={{ py: 2 }}>No documents in this queue.</Typography>
          )}
          <TablePagination
            component="div"
            count={active.data?.totalElements ?? 0}
            page={page}
            rowsPerPage={10}
            rowsPerPageOptions={[10]}
            onPageChange={(_, p) => {
              setPage(p);
              setSelected(undefined);
            }}
          />
          {item && (
            <Stack spacing={1.5} mt={2}>
              <Alert severity="warning">
                {reasonLabels[item.reviewReason ?? ""] ??
                  "Check the document before associating it."}
              </Alert>
              <Typography variant="body2">
                Detected:{" "}
                {item.detectedType ? typeLabel[item.detectedType] : "Unknown"} ·
                CNP: {item.cnpMasked ?? "Unavailable"}
              </Typography>
              <Button
                disabled={!item.fileId}
                onClick={() => setReviewPreview(item.fileId ?? null)}
              >
                Preview document
              </Button>
              <TextField
                select
                label="Confirm document type"
                value={kind}
                onChange={(e) => {
                  setKind(e.target.value as IntakeDocumentType);
                  setMatched(null);
                }}
              >
                {TYPES.map((t) => (
                  <MenuItem key={t} value={t}>
                    {typeLabel[t]}
                  </MenuItem>
                ))}
              </TextField>
              <TextField
                label="Customer CNP"
                value={cnp}
                onChange={(e) => {
                  setCnp(e.target.value);
                  setMatched(null);
                }}
                error={!!cnp && !validCnp(cnp)}
                helperText={
                  cnp && !validCnp(cnp)
                    ? "Check the 13 digits, date, county and control digit."
                    : "Enter the CNP checked on the document."
                }
              />
              <Button
                disabled={!validCnp(cnp) || reviewBusy}
                onClick={() => void findCustomer()}
              >
                Find customer
              </Button>
              {matched && <Chip label={`Matched customer: ${matched.name}`} />}
              {item.reviewReason === "TYPE_ALREADY_PRESENT" && (
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={replace}
                      onChange={(e) => setReplace(e.target.checked)}
                    />
                  }
                  label="Replace the existing document and keep it in history"
                />
              )}
              <Button
                variant="contained"
                disabled={
                  reviewBusy ||
                  !matched ||
                  matched.cnp !== cnp ||
                  (item.reviewReason === "TYPE_ALREADY_PRESENT" && !replace)
                }
                onClick={() => void decide(true)}
              >
                Confirm
              </Button>
              <TextField
                label="Rejection reason"
                value={rejectReason}
                onChange={(e) => setRejectReason(e.target.value)}
                inputProps={{ maxLength: 500 }}
              />
              <Button
                color="error"
                disabled={reviewBusy || !rejectReason.trim()}
                onClick={() => void decide(false)}
              >
                Reject
              </Button>
              {reviewError && <Alert severity="error">{reviewError}</Alert>}
            </Stack>
          )}
        </Paper>
      )}
      <Dialog
        open={!!fileId}
        onClose={() => {
          clearPreview();
          setReviewPreview(null);
        }}
        fullWidth
        maxWidth="md"
      >
        <DialogTitle>Document preview</DialogTitle>
        <DialogContent>
          {previewError ? (
            <Alert severity="error">{previewError}</Alert>
          ) : preview ? (
            preview.type.startsWith("image/") ? (
              <Box
                component="img"
                src={preview.url}
                alt="Uploaded document"
                sx={{ maxWidth: "100%" }}
              />
            ) : (
              <Box
                component="iframe"
                title="PDF document"
                src={preview.url}
                sx={{ width: "100%", height: "65vh", border: 0 }}
              />
            )
          ) : (
            <LinearProgress />
          )}
        </DialogContent>
        <DialogActions>
          <Button
            onClick={() => {
              clearPreview();
              setReviewPreview(null);
            }}
          >
            Close
          </Button>
        </DialogActions>
      </Dialog>
    </>
  );
}
