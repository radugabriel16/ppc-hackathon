import { Component } from "react";
import type { PropsWithChildren } from "react";
import {
  Alert,
  Box,
  Button,
  Chip,
  CircularProgress,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { InboxOutlined } from "@mui/icons-material";
import { errorText } from "../data/errors";
import { label } from "../data/models";

export function Loading({
  label: text = "Loading workspace…",
}: {
  label?: string;
}) {
  return (
    <Stack role="status" alignItems="center" spacing={2} sx={{ p: 6 }}>
      <CircularProgress size={26} />
      <Typography color="text.secondary" variant="body2">
        {text}
      </Typography>
    </Stack>
  );
}
export function ErrorNotice({
  error,
  retry,
}: {
  error: unknown;
  retry?: () => void;
}) {
  return (
    <Alert
      severity="error"
      action={
        retry && (
          <Button color="inherit" onClick={retry}>
            Retry
          </Button>
        )
      }
    >
      {errorText(error)}
    </Alert>
  );
}
export function Empty({
  title = "Nothing here yet",
  detail = "Try adjusting your filters.",
}: {
  title?: string;
  detail?: string;
}) {
  return (
    <Stack alignItems="center" spacing={1} sx={{ p: 7 }}>
      <InboxOutlined sx={{ color: "text.secondary", fontSize: 36 }} />
      <Typography fontWeight={600}>{title}</Typography>
      <Typography variant="body2" color="text.secondary">
        {detail}
      </Typography>
    </Stack>
  );
}
export function StatusChip({ status }: { status: string }) {
  const color = ["CORRUPT", "FAILED", "OPEN"].includes(status)
    ? "error"
    : ["VERIFYING", "IN_PROGRESS", "REVIEW", "STAGING"].includes(status)
      ? "warning"
      : ["READY", "RESOLVED", "COMPLETE"].includes(status)
        ? "success"
        : "default";
  return (
    <Chip size="small" label={label(status)} color={color} variant="outlined" />
  );
}
export function PageHeading({
  eyebrow,
  title,
  detail,
  action,
}: {
  eyebrow: string;
  title: string;
  detail: string;
  action?: React.ReactNode;
}) {
  return (
    <Stack
      direction={{ xs: "column", sm: "row" }}
      justifyContent="space-between"
      alignItems={{ sm: "center" }}
      gap={2}
      sx={{ mb: 3 }}
    >
      <Box>
        <Typography className="eyebrow">{eyebrow}</Typography>
        <Typography variant="h4" sx={{ my: 0.7 }}>
          {title}
        </Typography>
        <Typography color="text.secondary" variant="body2">
          {detail}
        </Typography>
      </Box>
      {action}
    </Stack>
  );
}
export function Metric({
  label: text,
  value,
  note,
  accent = false,
}: {
  label: string;
  value: React.ReactNode;
  note: string;
  accent?: boolean;
}) {
  return (
    <Paper
      variant="outlined"
      sx={{
        p: 2.4,
        flex: 1,
        minWidth: 150,
        bgcolor: accent ? "primary.dark" : "background.paper",
        color: accent ? "white" : "text.primary",
      }}
    >
      <Typography variant="body2" sx={{ opacity: 0.68 }}>
        {text}
      </Typography>
      <Typography
        sx={{
          fontSize: 30,
          fontWeight: 600,
          letterSpacing: "-.06rem",
          my: 0.5,
        }}
      >
        {value}
      </Typography>
      <Typography variant="caption" sx={{ opacity: 0.65 }}>
        {note}
      </Typography>
    </Paper>
  );
}
export class ErrorBoundary extends Component<
  PropsWithChildren,
  { error?: Error }
> {
  state: { error?: Error } = {};
  static getDerivedStateFromError(error: Error) {
    return { error };
  }
  render() {
    if (this.state.error)
      return (
        <Box sx={{ p: 5, maxWidth: 700, mx: "auto" }}>
          <Typography variant="h4" mb={2}>
            Workspace interrupted
          </Typography>
          <ErrorNotice error={this.state.error} />
          <Button
            sx={{ mt: 2 }}
            variant="contained"
            onClick={() => window.location.reload()}
          >
            Reload FileGrid
          </Button>
        </Box>
      );
    return this.props.children;
  }
}
