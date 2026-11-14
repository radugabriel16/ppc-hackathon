import { useState } from "react";
import {
  Alert,
  Box,
  Button,
  Checkbox,
  Chip,
  Dialog,
  DialogActions,
  DialogContent,
  DialogTitle,
  Divider,
  FormControlLabel,
  MenuItem,
  Paper,
  Stack,
  Switch,
  TextField,
  Typography,
} from "@mui/material";
import { Add, ArrowForward, MapOutlined } from "@mui/icons-material";
import {
  useCreateIssue,
  useDemoMode,
  useMap,
  useSession,
  useUpdateIssue,
} from "../data/hooks";
import { AppError } from "../data/errors";
import { label, REGION_INFO } from "../data/models";
import type { MapData, Severity } from "../data/models";
import { useRegion } from "../data/region-context";
import {
  Empty,
  ErrorNotice,
  Loading,
  Metric,
  PageHeading,
  StatusChip,
} from "../components/common";
import { NetworkMap } from "../components/NetworkMap";

function CreateIssueDialog({
  data,
  initialAsset,
  onClose,
  onCreated,
}: {
  data: MapData;
  initialAsset?: string;
  onClose: () => void;
  onCreated: () => void;
}) {
  const create = useCreateIssue();
  const [assetId, setAsset] = useState(
    initialAsset ?? data.assetList[0]?.id ?? "",
  );
  const [severity, setSeverity] = useState<Severity>("MEDIUM");
  const [description, setDescription] = useState("");
  const [videoId, setVideo] = useState("");
  const [offset, setOffset] = useState("");
  const fields =
    create.error instanceof AppError
      ? create.error.body.fieldErrors
      : undefined;
  return (
    <Dialog
      open
      onClose={create.isPending ? undefined : onClose}
      fullWidth
      maxWidth="sm"
    >
      <Box
        component="form"
        onSubmit={(e) => {
          e.preventDefault();
          create.mutate(
            {
              assetId,
              severity,
              description,
              videoId: videoId.trim() || undefined,
              offsetSeconds: offset === "" ? undefined : Number(offset),
            },
            { onSuccess: onCreated },
          );
        }}
      >
        <DialogTitle>
          Create network issue
          <Typography variant="body2" color="text.secondary">
            Connect a finding to an asset and its evidence.
          </Typography>
        </DialogTitle>
        <DialogContent>
          <Stack spacing={2.5} mt={1}>
            <TextField
              select
              label="Asset"
              value={assetId}
              required
              onChange={(e) => setAsset(e.target.value)}
              error={!!fields?.assetId}
              helperText={fields?.assetId}
            >
              {data.assetList.map((a) => (
                <MenuItem key={a.id} value={a.id}>
                  {a.id} · {a.name}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              select
              label="Severity"
              value={severity}
              onChange={(e) => setSeverity(e.target.value as Severity)}
            >
              {["LOW", "MEDIUM", "HIGH", "CRITICAL"].map((s) => (
                <MenuItem key={s} value={s}>
                  {label(s)}
                </MenuItem>
              ))}
            </TextField>
            <TextField
              label="Description"
              multiline
              rows={3}
              required
              value={description}
              onChange={(e) => setDescription(e.target.value)}
              inputProps={{ minLength: 8, maxLength: 2000 }}
              error={!!fields?.description}
              helperText={
                fields?.description ??
                "Describe what needs attention (at least 8 characters)."
              }
            />
            <Stack direction={{ xs: "column", sm: "row" }} spacing={2}>
              <TextField
                label="Video ID (optional)"
                value={videoId}
                onChange={(e) => setVideo(e.target.value)}
                error={!!fields?.videoId}
                helperText={fields?.videoId}
              />
              <TextField
                label="Offset in seconds"
                type="number"
                value={offset}
                onChange={(e) => setOffset(e.target.value)}
                inputProps={{ min: 0, step: "any" }}
                error={!!fields?.offsetSeconds}
                helperText={fields?.offsetSeconds}
              />
            </Stack>
            {create.error && <ErrorNotice error={create.error} />}
          </Stack>
        </DialogContent>
        <DialogActions sx={{ p: 3 }}>
          <Button onClick={onClose} disabled={create.isPending}>
            Cancel
          </Button>
          <Button type="submit" variant="contained" disabled={create.isPending}>
            {create.isPending ? "Creating…" : "Create issue"}
          </Button>
        </DialogActions>
      </Box>
    </Dialog>
  );
}
export function MapPage() {
  const { region } = useRegion();
  const query = useMap(region);
  const update = useUpdateIssue();
  const session = useSession();
  const demo = useDemoMode();
  const [resolved, setResolved] = useState(false);
  const [layers, setLayers] = useState({
    assets: true,
    issues: true,
    outages: true,
  });
  const [create, setCreate] = useState<{ assetId?: string } | null>(null);
  const [selected, setSelected] = useState("");
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState(false);
  const data = query.data;
  const issue = data?.issueList.find(
    (x) => x.id === selected && x.region === region,
  );
  const open = data?.issueList.filter((x) => x.status === "OPEN").length ?? 0;
  const inProgress =
    data?.issueList.filter((x) => x.status === "IN_PROGRESS").length ?? 0;
  const onCreate = (assetId?: string) => setCreate({ assetId });
  return (
    <>
      <PageHeading
        eyebrow="NETWORK INTELLIGENCE"
        title="Your network, in view."
        detail="Locate assets, investigate findings, and keep the grid moving."
        action={
          <Button
            variant="contained"
            startIcon={<Add />}
            disabled={!data}
            onClick={() => setCreate({})}
          >
            Create issue
          </Button>
        }
      />
      <Stack direction="row" flexWrap="wrap" gap={2} mb={3}>
        <Metric
          label="Network assets"
          value={data?.assetList.length ?? "—"}
          note={`${REGION_INFO[region].name} operational area`}
          accent
        />
        <Metric label="Open issues" value={open} note="Awaiting an operator" />
        <Metric
          label="In progress"
          value={inProgress}
          note="Under investigation"
        />
        <Metric
          label="Active outages"
          value={data?.outages.features.length ?? "—"}
          note="Planned & unplanned events"
        />
      </Stack>
      {query.isPending && <Loading />}
      {query.error && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {notice && (
        <Alert sx={{ mb: 2 }} onClose={() => setNotice(false)}>
          Issue created. The network map has been refreshed.
        </Alert>
      )}
      {data && (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", xl: "minmax(0, 1fr) 315px" },
            gap: 2.5,
          }}
        >
          <Paper variant="outlined" sx={{ overflow: "hidden" }}>
            <Stack
              direction="row"
              justifyContent="space-between"
              alignItems="center"
              sx={{ px: 2.2, py: 1.5 }}
            >
              <Stack direction="row" spacing={1} alignItems="center">
                <MapOutlined fontSize="small" color="primary" />
                <Typography variant="h6">Network explorer</Typography>
                <Chip
                  size="small"
                  label={REGION_INFO[region].name}
                  sx={{ bgcolor: "#eff3ec" }}
                />
              </Stack>
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: { xs: "none", sm: "block" } }}
              >
                Click the map to report a finding
              </Typography>
            </Stack>
            <Divider />
            <NetworkMap
              data={data}
              region={region}
              resolved={resolved}
              layers={layers}
              onCreate={onCreate}
              onIssue={setSelected}
            />
            <Box sx={{ px: 2, py: 1 }}>
              <Typography variant="caption" color="text.secondary">
                Illustrative boundaries · [longitude, latitude] · No personal
                client data ·{" "}
                <a
                  href="https://www.openstreetmap.org/copyright"
                  target="_blank"
                  rel="noreferrer"
                >
                  © OpenStreetMap contributors
                </a>
              </Typography>
            </Box>
          </Paper>
          <Stack gap={2}>
            <Paper variant="outlined" sx={{ p: 2.3 }}>
              <Typography variant="h6" mb={1}>
                Map layers
              </Typography>
              {(["assets", "issues", "outages"] as const).map((key) => (
                <Stack
                  key={key}
                  direction="row"
                  alignItems="center"
                  justifyContent="space-between"
                >
                  <Typography variant="body2">{label(key)}</Typography>
                  <Switch
                    size="small"
                    checked={layers[key]}
                    inputProps={{ "aria-label": `${label(key)} layer` }}
                    onChange={(e) =>
                      setLayers({ ...layers, [key]: e.target.checked })
                    }
                  />
                </Stack>
              ))}
              <Divider sx={{ my: 1.5 }} />
              <Stack gap={0.8}>
                {[
                  ["#176747", "Substation"],
                  ["#457b9d", "Transformer"],
                  ["#25816e", "Line segment"],
                  ["#d44c53", "Open issue"],
                  ["#e2b23d", "In progress"],
                  ["#6e9e8a", "Resolved"],
                  ["#9b70ba", "Outage"],
                ].map(([color, text]) => (
                  <Stack
                    direction="row"
                    spacing={1.2}
                    key={text}
                    alignItems="center"
                  >
                    <Box
                      sx={{
                        width: text === "Line segment" ? 20 : 9,
                        height: text === "Line segment" ? 3 : 9,
                        bgcolor: color,
                        borderRadius: text === "Line segment" ? 0 : "50%",
                      }}
                    />
                    <Typography variant="caption" color="text.secondary">
                      {text}
                    </Typography>
                  </Stack>
                ))}
              </Stack>
              <FormControlLabel
                sx={{ mt: 1.5, "& .MuiTypography-root": { fontSize: 12 } }}
                control={
                  <Checkbox
                    size="small"
                    checked={resolved}
                    onChange={(e) => setResolved(e.target.checked)}
                  />
                }
                label="Show resolved issues"
              />
            </Paper>
            <Paper variant="outlined" sx={{ p: 2.3 }}>
              <Stack
                direction="row"
                justifyContent="space-between"
                alignItems="center"
                mb={1.5}
              >
                <Typography variant="h6">Attention queue</Typography>
                <Chip
                  size="small"
                  label={
                    data.issueList.filter(
                      (x) => resolved || x.status !== "RESOLVED",
                    ).length
                  }
                />
              </Stack>
              <Stack gap={1}>
                {data.issueList
                  .filter((x) => resolved || x.status !== "RESOLVED")
                  .map((item) => (
                    <Button
                      key={item.id}
                      variant="text"
                      onClick={() => setSelected(item.id)}
                      sx={{
                        justifyContent: "flex-start",
                        textAlign: "left",
                        bgcolor: selected === item.id ? "#edf3e9" : "#f8faf6",
                        p: 1.3,
                        color: "text.primary",
                      }}
                    >
                      <Box>
                        <Stack direction="row" spacing={1} alignItems="center">
                          <Typography variant="caption" fontWeight={650}>
                            {item.id}
                          </Typography>
                          <Box
                            sx={{
                              width: 6,
                              height: 6,
                              borderRadius: "50%",
                              bgcolor:
                                item.status === "OPEN"
                                  ? "#d44c53"
                                  : item.status === "IN_PROGRESS"
                                    ? "#e2b23d"
                                    : "#6e9e8a",
                            }}
                          />
                        </Stack>
                        <Typography variant="body2" sx={{ my: 0.4 }}>
                          {item.description}
                        </Typography>
                        <Typography variant="caption" color="text.secondary">
                          {item.assetId} · {label(item.severity)} severity
                        </Typography>
                      </Box>
                    </Button>
                  ))}
                {data.issueList.length === 0 && (
                  <Empty title="All clear" detail="No issues in this area." />
                )}
              </Stack>
            </Paper>
          </Stack>
        </Box>
      )}
      {issue && (
        <Dialog
          open
          onClose={() => {
            setSelected("");
            update.reset();
          }}
          fullWidth
          maxWidth="sm"
        >
          <DialogTitle>
            {issue.id} <StatusChip status={issue.status} />
          </DialogTitle>
          <DialogContent>
            <Stack spacing={2}>
              <Typography>{issue.description}</Typography>
              <Typography variant="body2" color="text.secondary">
                {issue.assetId} · {label(issue.severity)} severity · Version{" "}
                {issue.version ?? "unavailable"}
              </Typography>
              {issue.videoId && (
                <Typography variant="body2">
                  Video {issue.videoId} · {issue.offsetSeconds ?? 0} seconds
                </Typography>
              )}
              {demo && (
                <FormControlLabel
                  control={
                    <Checkbox
                      checked={conflict}
                      onChange={(e) => setConflict(e.target.checked)}
                    />
                  }
                  label="Simulate another operator taking this issue (409)"
                />
              )}
              {issue.version === null && (
                <Alert severity="warning">
                  The API map feature has no issue version. Status changes are
                  unavailable until the contract supplies it.
                </Alert>
              )}
              {update.error && <ErrorNotice error={update.error} />}
              {update.isSuccess && (
                <Alert severity="success">Issue updated.</Alert>
              )}
              {session.data?.user.role !== "MANAGER" && (
                <Typography variant="caption" color="text.secondary">
                  A manager can resolve this issue.
                </Typography>
              )}
            </Stack>
          </DialogContent>
          <DialogActions sx={{ p: 2.5 }}>
            <Button
              onClick={() => {
                setSelected("");
                update.reset();
              }}
            >
              Close
            </Button>
            {issue.status === "OPEN" && (
              <Button
                disabled={update.isPending || issue.version === null}
                variant="contained"
                endIcon={<ArrowForward />}
                onClick={() =>
                  update.mutate({
                    id: issue.id,
                    status: "IN_PROGRESS",
                    version: issue.version!,
                    simulateConflict: conflict,
                  })
                }
              >
                Take issue
              </Button>
            )}
            {issue.status !== "RESOLVED" &&
              session.data?.user.role === "MANAGER" && (
                <Button
                  disabled={update.isPending || issue.version === null}
                  variant="contained"
                  onClick={() =>
                    update.mutate({
                      id: issue.id,
                      status: "RESOLVED",
                      version: issue.version!,
                      simulateConflict: conflict,
                    })
                  }
                >
                  Resolve issue
                </Button>
              )}
          </DialogActions>
        </Dialog>
      )}
      {create && data && (
        <CreateIssueDialog
          key={region}
          data={data}
          initialAsset={create.assetId}
          onClose={() => setCreate(null)}
          onCreated={() => {
            setCreate(null);
            setNotice(true);
          }}
        />
      )}
    </>
  );
}
