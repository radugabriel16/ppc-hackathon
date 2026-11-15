import { useState } from "react";
import { useMutation } from "@tanstack/react-query";
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  Stack, Typography,
} from "@mui/material";
import { useFile } from "../data/hooks";
import { useSource } from "../data/context";
import { bytes, label } from "../data/models";
import { ErrorNotice, Loading, StatusChip } from "./common";

export function FileViewerDialog({ id, onClose }: { id: string; onClose: () => void }) {
  const source = useSource();
  const query = useFile(id);
  const file = query.data;
  const [mediaError, setMediaError] = useState("");
  const download = useMutation({
    mutationFn: async () => {
      if (!source.downloadFile || !file) throw new Error("File download is unavailable.");
      const blob = await source.downloadFile(id);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = file.name;
      link.click();
      setTimeout(() => URL.revokeObjectURL(url), 1000);
    },
  });
  const url = file?.status === "READY" && !query.isFetching && !query.error
    ? source.fileViewUrl?.(id) : undefined;
  const type = file?.mediaType ?? "";
  return (
    <Dialog open onClose={onClose} fullWidth maxWidth="md">
      <DialogTitle>{file?.name ?? "File viewer"}</DialogTitle>
      <DialogContent>
        {(query.isPending || query.isFetching) && <Loading label="Loading file and verifying integrity…" />}
        {query.error && <ErrorNotice error={query.error} />}
        {file && (
          <Stack spacing={2}>
            <Stack direction="row" gap={1} alignItems="center">
              <StatusChip status={file.status} />
              <Typography variant="body2">{label(file.category)} · {bytes(file.sizeBytes)} · {type}</Typography>
            </Stack>
            <Typography variant="body2">Capture timestamp: {file.capturedAt ?? "Not supplied"}</Typography>
            <Typography sx={{ whiteSpace: "pre-wrap", overflowWrap: "anywhere" }}>
              {file.description || "No description supplied"}
            </Typography>
            <Typography variant="caption">{label(file.region)} · {file.id}</Typography>
            {file.status !== "READY" && (
              <Alert severity={file.status === "CORRUPT" ? "error" : "info"}>
                {file.status === "CORRUPT" ? "Corrupt files cannot be viewed or downloaded." : "The file is not ready for viewing."}
              </Alert>
            )}
            {file.status === "READY" && !source.fileViewUrl && (
              <Alert severity="warning">Inline file viewing is unavailable in this data mode.</Alert>
            )}
            {mediaError && <Alert severity="error">{mediaError}</Alert>}
            {url && type.startsWith("video/") && (
              <Box component="video" src={url} controls preload="metadata"
                onError={() => setMediaError("Video playback failed. The file may be unavailable or its format unsupported.")}
                sx={{ width: "100%", maxHeight: "60vh", bgcolor: "#000" }} />
            )}
            {url && type === "application/pdf" && (
              <Box component="iframe" src={url} title={file.name}
                onError={() => setMediaError("The PDF viewer could not load this file.")}
                sx={{ width: "100%", height: "65vh", border: 0 }} />
            )}
            {url && type.startsWith("image/") && (
              <Box component="img" src={url} alt={file.description || file.name}
                onError={() => setMediaError("The image could not be loaded.")}
                sx={{ maxWidth: "100%", maxHeight: "65vh", objectFit: "contain" }} />
            )}
            {download.error && <ErrorNotice error={download.error} />}
          </Stack>
        )}
      </DialogContent>
      <DialogActions>
        {source.downloadFile && (
          <Button disabled={file?.status !== "READY" || download.isPending || !!query.error}
            onClick={() => download.mutate()}>Download</Button>
        )}
        <Button onClick={onClose}>Close</Button>
      </DialogActions>
    </Dialog>
  );
}
