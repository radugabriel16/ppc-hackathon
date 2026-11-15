import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
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
  useMapMeters,
  useGeography,
  useSession,
  useUpdateIssue,
} from "../data/hooks";
import { AppError } from "../data/errors";
import { label, REGION_INFO } from "../data/models";
import type {
  CreateIssue,
  Asset,
  GeographicArea,
  MapData,
  Severity,
} from "../data/models";
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
import { GeographyExplorer } from "../components/GeographyExplorer";
import { ForecastPanel } from "../components/ForecastPanel";
import {
  ISSUE_STATES,
  ISSUE_TYPES,
  issueTitle,
  issueDocumentsUrl,
} from "../components/issue-presentation";
import { ASSET_MARKERS } from "../components/station-icons";

function CreateIssueDialog({
  data,
  initialAsset,
  initialPoint,
  onClose,
  onCreated,
}: {
  data: MapData;
  initialAsset?: string;
  initialPoint?: Pick<CreateIssue, "coordinates" | "regionId" | "segmentId">;
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
              ...initialPoint,
            },
            { onSuccess: onCreated },
          );
        }}
      >
        <DialogTitle>
          {initialPoint?.coordinates
            ? "Report outage here"
            : "Create network issue"}
          <Typography variant="body2" color="text.secondary">
            {initialPoint?.coordinates
              ? `Exact location: ${initialPoint.coordinates[0].toFixed(6)}, ${initialPoint.coordinates[1].toFixed(6)}`
              : "Connect a finding to an asset and its evidence."}
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
  const {
    region,
    selectedRegion,
    subregionId,
    setScope,
    setSubregion,
    clearRegion,
  } = useRegion();
  const query = useMap(region, selectedRegion === null);
  const geography = useGeography();
  const areas = geography.data ?? [];
  const parent = areas.find((a) => !a.parentId && a.region === selectedRegion);
  const selectedId = subregionId ?? parent?.id;
  const scopeKey = `${selectedRegion}:${subregionId}`;
  const [stationSelection, setStationSelection] = useState<{
    scope: string;
    station: Asset;
  } | null>(null);
  useEffect(() => {
    setStationSelection((selection) =>
      selection?.scope === scopeKey ? selection : null,
    );
  }, [scopeKey]);
  const station =
    stationSelection?.scope === scopeKey && !query.isPlaceholderData
      ? query.data?.assetList.find(
          (asset) => asset.id === stationSelection.station.id,
        )
      : undefined;
  const meters = useMapMeters(region, subregionId);
  const selectStation = (asset?: Asset) => {
    if (!asset) {
      setStationSelection(null);
      return;
    }
    const segmentId = subregionId ?? asset.segmentId;
    const targetScope = segmentId ? `${asset.region}:${segmentId}` : scopeKey;
    setStationSelection({ scope: targetScope, station: asset });
    if (segmentId && targetScope !== scopeKey)
      setScope(asset.region, segmentId);
  };
  const selectArea = (area?: GeographicArea) => {
    setStationSelection(null);
    if (!area) {
      clearRegion();
      return;
    }
    setScope(area.region, area.parentId ? area.id : undefined);
  };
  const goBack = () => (subregionId ? setSubregion(undefined) : clearRegion());
  const update = useUpdateIssue();
  const session = useSession();
  const demo = useDemoMode();
  const [resolved, setResolved] = useState(false);
  const [layers, setLayers] = useState({
    assets: true,
    issues: true,
    outages: true,
  });
  const [create, setCreate] = useState<
    | (Pick<CreateIssue, "coordinates" | "regionId" | "segmentId"> & {
        assetId?: string;
      })
    | null
  >(null);
  const [params, setParams] = useSearchParams();
  const selected = params.get("issue") ?? "";
  const setSelected = (id: string) =>
    setParams((previous) => {
      const next = new URLSearchParams(previous);
      if (id) next.set("issue", id);
      else next.delete("issue");
      return next;
    });
  const [conflict, setConflict] = useState(false);
  const [notice, setNotice] = useState(false);
  useEffect(() => {
    const escape = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setStationSelection(null);
      if (station && !create && !selected) {
        event.preventDefault();
        event.stopPropagation();
      }
    };
    document.addEventListener("keydown", escape, true);
    return () => document.removeEventListener("keydown", escape, true);
  }, [station, create, selected]);
  const data = query.data;
  const visibleData =
    data && query.isPlaceholderData
      ? {
          ...data,
          assets: { ...data.assets, features: [] },
          issues: { ...data.issues, features: [] },
          outages: { ...data.outages, features: [] },
          assetList: [],
          issueList: [],
        }
      : data;
  const issue = data?.issueList.find((x) => x.id === selected);
  const open = data?.issueList.filter((x) => x.status === "OPEN").length ?? 0;
  const inProgress =
    data?.issueList.filter((x) => x.status === "IN_PROGRESS").length ?? 0;
  return (
    <Box
      onKeyDown={(event) => {
        if (event.key === "Escape" && !create && !selected) {
          event.preventDefault();
          if (station) setStationSelection(null);
          else goBack();
        }
      }}
    >
      <PageHeading
        eyebrow="NETWORK INTELLIGENCE"
        title="Your network, in view."
        detail="Locate assets, investigate findings, and keep the grid moving."
        action={
          <Button
            variant="contained"
            startIcon={<Add />}
            disabled={!data || query.isPlaceholderData}
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
          note={
            selectedRegion
              ? `${REGION_INFO[region].name} operational area`
              : "Romania operational areas"
          }
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
      {geography.error && (
        <ErrorNotice
          error={geography.error}
          retry={() => void geography.refetch()}
        />
      )}
      {meters.error && (
        <ErrorNotice error={meters.error} retry={() => void meters.refetch()} />
      )}
      {notice && (
        <Alert sx={{ mb: 2 }} onClose={() => setNotice(false)}>
          Issue created. The network map has been refreshed.
        </Alert>
      )}
      {!issue && update.error && <ErrorNotice error={update.error} />}
      {data && (
        <Box
          sx={{
            display: "grid",
            gridTemplateColumns: { xs: "1fr", xl: "minmax(0, 1fr) 315px" },
            gap: 2.5,
            alignItems: "start",
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
                  label={selectedRegion ? REGION_INFO[region].name : "Romania"}
                  sx={{ bgcolor: "#eff3ec" }}
                />
              </Stack>
              <Typography
                variant="caption"
                color="text.secondary"
                sx={{ display: { xs: "none", sm: "block" } }}
              >
                Left click to select · Right click to report
              </Typography>
            </Stack>
            <Divider />
            <GeographyExplorer
              areas={areas}
              selectedId={selectedId}
              onSelect={selectArea}
            />
            {station && (
              <Stack direction="row" gap={1} alignItems="center" sx={{ px: 2 }}>
                <Button size="small" onClick={() => setStationSelection(null)}>
                  Clear meter highlight
                </Button>
                <Typography variant="caption">
                  {station.name}
                  {meters.isFetching ? " · Loading meters…" : ""}
                  {meters.data
                    ? ` · ${meters.data.filter((meter) => meter.assetId === station.id).length} linked meters highlighted`
                    : ""}
                </Typography>
              </Stack>
            )}
            <NetworkMap
              data={{
                ...visibleData!,
                meters: subregionId ? meters.data : [],
              }}
              station={station}
              onStation={selectStation}
              region={region}
              areas={areas}
              selectedId={selectedId}
              onSelect={selectArea}
              resolved={resolved}
              layers={layers}
              onCreate={setCreate}
              onIssue={setSelected}
              selectedIssue={selected}
            />
            <Box sx={{ px: 2, py: 1 }}>
              <Typography variant="caption" color="text.secondary">
                {subregionId ? (meters.data?.length ?? 0) : 0} meters visible ·
                Meters appear at segment scope · Click a point asset to
                highlight its linked meters · Co-located meters fanned out for
                clarity · Operational boundaries · [longitude, latitude] · No
                personal client data ·{" "}
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
                {Object.entries(ISSUE_TYPES).map(([type, info]) => (
                  <Stack key={type} direction="row" gap={1} alignItems="center">
                    <Box
                      sx={{
                        borderRadius: "50%",
                        bgcolor: ISSUE_STATES.OPEN.color,
                        color: "#fff",
                        width: 20,
                        height: 20,
                        textAlign: "center",
                        fontSize: 12,
                        fontWeight: 700,
                      }}
                    >
                      {info.symbol}
                    </Box>
                    <Typography variant="caption">{info.label}</Typography>
                  </Stack>
                ))}
                <Typography variant="caption">Blue markers · Meters</Typography>
                <Typography variant="caption">
                  Cyan markers · Highlighted linked meters
                </Typography>
                <Typography variant="caption">
                  Red pulsing ring · Open manual reports only
                </Typography>
              </Stack>
              <Divider sx={{ my: 1.5 }} />
              <Typography variant="subtitle2" mb={1}>
                Issue status
              </Typography>
              <Stack gap={0.8}>
                {Object.entries(ISSUE_STATES).map(([status, info]) => (
                  <Stack
                    key={status}
                    direction="row"
                    gap={1}
                    alignItems="center"
                  >
                    <Box
                      sx={{
                        width: 12,
                        height: 12,
                        borderRadius: "50%",
                        bgcolor: info.color,
                      }}
                    />
                    <Typography variant="caption">{info.label}</Typography>
                  </Stack>
                ))}
              </Stack>
              <Divider sx={{ my: 1.5 }} />
              <Stack gap={0.8}>
                {Object.entries(ASSET_MARKERS).map(([type, marker]) => (
                  <Stack
                    direction="row"
                    spacing={1.2}
                    key={type}
                    alignItems="center"
                  >
                    <Box
                      component="svg"
                      viewBox="0 0 48 48"
                      sx={{ width: 22, height: 22 }}
                    >
                      <polygon
                        points={marker.points
                          .map((point) => point.join(","))
                          .join(" ")}
                        fill={marker.color}
                        stroke="#fff"
                        strokeWidth={3}
                      />
                    </Box>
                    <Typography variant="caption" color="text.secondary">
                      {marker.label}
                    </Typography>
                  </Stack>
                ))}
                {[
                  ["#25816e", "Network line"],
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
                        width: text === "Network line" ? 20 : 9,
                        height: text === "Network line" ? 3 : 9,
                        bgcolor: color,
                        borderRadius: text === "Network line" ? 0 : "50%",
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
              <Stack gap={1} sx={{ maxHeight: 600, overflow: "auto" }}>
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
                              bgcolor: ISSUE_STATES[item.status].color,
                            }}
                          />
                        </Stack>
                        <Typography variant="body2" sx={{ my: 0.4 }}>
                          {issueTitle(item)}
                        </Typography>
                        <Chip
                          size="small"
                          label={
                            ISSUE_TYPES[item.type ?? "OUTAGE_REPORT"].label
                          }
                        />
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
      <Box mt={3}>
        <ForecastPanel />
      </Box>
      {issue && (
        <Dialog
          open
          onClose={() => {
            setSelected("");
            if (!update.isPending) update.reset();
          }}
          fullWidth
          maxWidth="sm"
        >
          <DialogTitle>
            {issueTitle(issue)} <StatusChip status={issue.status} />
          </DialogTitle>
          <DialogContent>
            <Stack spacing={2}>
              <Typography>{issue.description}</Typography>
              <Chip
                label={ISSUE_TYPES[issue.type ?? "OUTAGE_REPORT"].label}
                sx={{ alignSelf: "start" }}
              />
              <Typography variant="body2">
                Location: {issue.coordinates.join(", ")}
              </Typography>
              {issue.forecastDate && (
                <Typography variant="body2">
                  Forecast date: {issue.forecastDate} UTC
                </Typography>
              )}
              {issue.clientId && (
                <Typography variant="body2">
                  Client ID: {issue.clientId}
                </Typography>
              )}
              {issue.caseId && (
                <Typography variant="body2">Case ID: {issue.caseId}</Typography>
              )}
              {issue.type === "MISSING_DOCUMENTS" && (
                <Button component={Link} to={issueDocumentsUrl(issue)}>Open Documents</Button>
              )}
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
                if (!update.isPending) update.reset();
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
          initialPoint={create}
          onClose={() => setCreate(null)}
          onCreated={() => {
            setCreate(null);
            setNotice(true);
          }}
        />
      )}
    </Box>
  );
}
