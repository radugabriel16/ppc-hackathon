import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import { Link } from "react-router-dom";
import {
  Alert,
  Box,
  Button,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  InputAdornment,
  MenuItem,
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
import {
  CloudUploadOutlined,
  DescriptionOutlined,
  Search,
  VerifiedUserOutlined,
} from "@mui/icons-material";
import { useFile, useFiles } from "../data/hooks";
import { useSource } from "../data/context";
import { bytes, CATEGORIES, FILE_STATUSES, label } from "../data/models";
import type { Category, FileStatus } from "../data/models";
import { useRegion } from "../data/region-context";
import {
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  StatusChip,
} from "../components/common";
import { FileViewerDialog } from "../components/FileViewerDialog";

export function VerificationDialog({
  id,
  onClose,
}: {
  id: string;
  onClose: () => void;
}) {
  const query = useFile(id);
  const file = query.data;
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="sm">
      <DialogTitle>File integrity report</DialogTitle>
      <DialogContent>
        {query.isPending && <Loading label="Checking integrity…" />}
        {query.error && (
          <ErrorNotice error={query.error} retry={() => void query.refetch()} />
        )}
        {file && (
          <Stack spacing={2}>
            <Stack
              direction="row"
              alignItems="center"
              justifyContent="space-between"
            >
              <Typography fontWeight={600}>{file.name}</Typography>
              <StatusChip status={file.status} />
            </Stack>
            <Typography variant="caption" color="text.secondary">
              {file.id} · SHA-256
            </Typography>
            <Typography variant="body2">Capture timestamp: {file.capturedAt ?? "Not supplied"}</Typography>
            <Typography sx={{ whiteSpace: "pre-wrap" }}>{file.description || "No description supplied"}</Typography>
            <Alert
              severity={
                file.status === "CORRUPT"
                  ? "error"
                  : file.status === "VERIFYING"
                    ? "info"
                    : file.status === "READY" &&
                        file.expectedSha256 === file.actualSha256
                      ? "success"
                      : "warning"
              }
            >
              {file.status === "CORRUPT"
                ? "Integrity check failed. The file is corrupt and must be uploaded again."
                : file.status === "VERIFYING"
                  ? "Verification is in progress. This report refreshes automatically."
                  : file.status === "READY" &&
                      file.expectedSha256 === file.actualSha256
                    ? "Integrity verified. The checksums match."
                    : "Verification is unavailable for this file status."}
            </Alert>
            <Box sx={{ p: 2, bgcolor: "#f5f7f2", borderRadius: 2 }}>
              <Typography variant="caption" color="text.secondary">
                EXPECTED SHA-256
              </Typography>
              <Typography className="hash-text" mt={0.5}>
                {file.expectedSha256 || "Pending"}
              </Typography>
            </Box>
            <Box
              sx={{
                p: 2,
                bgcolor: file.status === "CORRUPT" ? "#fcf0ef" : "#f5f7f2",
                borderRadius: 2,
              }}
            >
              <Typography variant="caption" color="text.secondary">
                ACTUAL SHA-256
              </Typography>
              <Typography className="hash-text" mt={0.5}>
                {file.status === "VERIFYING"
                  ? "Pending verification…"
                  : file.actualSha256 || "Unavailable"}
              </Typography>
            </Box>
          </Stack>
        )}
      </DialogContent>
      <DialogActions sx={{ p: 2.5 }}>
        <Button onClick={onClose}>Close report</Button>
      </DialogActions>
    </Dialog>
  );
}
export function FilesPage() {
  const { region } = useRegion();
  return <FilesContent key={region} />;
}
function FilesContent() {
  const source = useSource();
  const download = useMutation({
    mutationFn: async (file: { id: string; name: string }) => {
      const blob = await source.downloadFile!(file.id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  const { region } = useRegion();
  const [search, setSearch] = useState("");
  const [category, setCategory] = useState<Category | "">("");
  const [status, setStatus] = useState<FileStatus | "">("");
  const [page, setPage] = useState(0);
  const [size, setSize] = useState(10);
  const [verify, setVerify] = useState("");
  const [view, setView] = useState("");
  const query = useFiles({
    region,
    search,
    category: category || undefined,
    status: status || undefined,
    page,
    size,
  });
  return (
    <>
      <PageHeading
        eyebrow="EVIDENCE LIBRARY"
        title="Files, ready for decisions."
        detail="One place for network evidence, with integrity you can verify."
        action={
          <Button
            component={Link}
            to="/uploads"
            variant="contained"
            startIcon={<CloudUploadOutlined />}
          >
            Upload files
          </Button>
        }
      />
      {download.error && <ErrorNotice error={download.error} />}
      <Paper variant="outlined" sx={{ overflow: "hidden" }}>
        <Stack direction={{ xs: "column", sm: "row" }} gap={2} sx={{ p: 2.5 }}>
          <TextField
            label="Search files"
            placeholder="File name or ID"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            sx={{ flex: 1 }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Search sx={{ fontSize: 19 }} />
                </InputAdornment>
              ),
            }}
          />
          <TextField
            select
            label="Category"
            value={category}
            onChange={(e) => {
              setCategory(e.target.value as Category | "");
              setPage(0);
            }}
            sx={{ minWidth: 210 }}
          >
            <MenuItem value="">All categories</MenuItem>
            {CATEGORIES.map((x) => (
              <MenuItem key={x} value={x}>
                {label(x)}
              </MenuItem>
            ))}
          </TextField>
          <TextField
            select
            label="Status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as FileStatus | "");
              setPage(0);
            }}
            sx={{ minWidth: 160 }}
          >
            <MenuItem value="">All statuses</MenuItem>
            {FILE_STATUSES.map((x) => (
              <MenuItem key={x} value={x}>
                {label(x)}
              </MenuItem>
            ))}
          </TextField>
        </Stack>
        {query.isPending && <Loading />}
        {query.error && (
          <ErrorNotice error={query.error} retry={() => void query.refetch()} />
        )}
        {query.data &&
          (query.data.items.length ? (
            <TableContainer>
              <Table aria-label="Files">
                <TableHead>
                  <TableRow>
                    {[
                      "File name",
                      "Category",
                      "Status",
                      "Size",
                      "Ingested",
                      "Integrity",
                    ].map((x) => (
                      <TableCell key={x}>{x}</TableCell>
                    ))}
                  </TableRow>
                </TableHead>
                <TableBody>
                  {query.data.items.map((file) => (
                    <TableRow key={file.id} hover>
                      <TableCell>
                        <Button size="small" onClick={() => setView(file.id)}>View</Button>
                        {source.downloadFile && (
                          <Button
                            size="small"
                            disabled={
                              file.status !== "READY" || download.isPending
                            }
                            onClick={() => download.mutate(file)}
                          >
                            Download
                          </Button>
                        )}
                        <Stack direction="row" gap={1.4} alignItems="center">
                          <Box
                            sx={{
                              bgcolor: "#edf2ea",
                              p: 1,
                              borderRadius: 2,
                              display: "flex",
                              color: "#54725b",
                            }}
                          >
                            <DescriptionOutlined fontSize="small" />
                          </Box>
                          <Box>
                            <Typography variant="body2" fontWeight={600}>
                              {file.name}
                            </Typography>
                            <Typography
                              variant="caption"
                              color="text.secondary"
                            >
                              {file.id}
                            </Typography>
                          </Box>
                        </Stack>
                      </TableCell>
                      <TableCell>
                        <Typography variant="body2">
                          {label(file.category)}
                        </Typography>
                      </TableCell>
                      <TableCell>
                        <StatusChip status={file.status} />
                      </TableCell>
                      <TableCell sx={{ whiteSpace: "nowrap" }}>
                        {bytes(file.sizeBytes)}
                      </TableCell>
                      <TableCell sx={{ whiteSpace: "nowrap" }}>
                        {new Date(file.createdAt).toLocaleString("en-GB", {
                          timeZone: "Europe/Bucharest",
                          day: "2-digit",
                          month: "short",
                          hour: "2-digit",
                          minute: "2-digit",
                        })}
                      </TableCell>
                      <TableCell>
                        <Button
                          size="small"
                          onClick={() => setVerify(file.id)}
                          startIcon={<VerifiedUserOutlined />}
                        >
                          Verify
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          ) : (
            <Empty title="No files found" />
          ))}
        <TablePagination
          component="div"
          count={query.data?.totalElements ?? 0}
          page={page}
          rowsPerPage={size}
          rowsPerPageOptions={[5, 10, 20]}
          onPageChange={(_, p) => setPage(p)}
          onRowsPerPageChange={(e) => {
            setSize(Number(e.target.value));
            setPage(0);
          }}
        />
      </Paper>
      {verify && (
        <VerificationDialog id={verify} onClose={() => setVerify("")} />
      )}
      {view && <FileViewerDialog key={view} id={view} onClose={() => setView("")} />}
    </>
  );
}
