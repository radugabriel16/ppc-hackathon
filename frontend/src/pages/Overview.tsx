import {
  Alert,
  Box,
  LinearProgress,
  Paper,
  Stack,
  Typography,
} from "@mui/material";
import { useStatistics } from "../data/hooks";
import { useRegion } from "../data/region-context";
import { bytes, REGION_INFO } from "../data/models";
import {
  ErrorNotice,
  Loading,
  Metric,
  PageHeading,
} from "../components/common";
import { MapLinkButton } from "../components/Shell";

export function StatisticsPage() {
  const { region } = useRegion();
  const query = useStatistics(region);
  const data = query.data;
  return (
    <>
      <PageHeading
        eyebrow="OPERATIONAL OVERVIEW"
        title="The bigger picture."
        detail={`File integrity and operational workload for ${REGION_INFO[region].name}.`}
        action={<MapLinkButton />}
      />
      {query.isPending && <Loading />}
      {query.error && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {data && (
        <>
          <Stack direction="row" flexWrap="wrap" gap={2} mb={3}>
            <Metric
              label="Files ingested"
              value={data.files}
              note={`${bytes(data.bytes)} of evidence`}
              accent
            />
            <Metric
              label="Ready for use"
              value={data.ready}
              note="Integrity verified"
            />
            <Metric
              label="Corrupt files"
              value={data.corrupt}
              note="Require a fresh upload"
            />
            <Metric
              label="Active issues"
              value={data.openIssues}
              note="Open or in progress"
            />
          </Stack>
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", md: "1.2fr 1fr" },
              gap: 3,
            }}
          >
            <Paper variant="outlined" sx={{ p: 3 }}>
              <Typography variant="h6" mb={3}>
                Evidence readiness
              </Typography>
              {[
                ["Ready", data.ready, "#176747"],
                ["Corrupt", data.corrupt, "#c64046"],
                [
                  "Other statuses",
                  data.files - data.ready - data.corrupt,
                  "#d9ac40",
                ],
              ].map(([name, value, color]) => (
                <Box key={name} mb={3}>
                  <Stack direction="row" justifyContent="space-between" mb={1}>
                    <Typography variant="body2">{name}</Typography>
                    <Typography variant="body2" color="text.secondary">
                      {value} / {data.files}
                    </Typography>
                  </Stack>
                  <LinearProgress
                    variant="determinate"
                    value={data.files ? (Number(value) / data.files) * 100 : 0}
                    sx={{
                      height: 8,
                      borderRadius: 4,
                      bgcolor: "#f0f3eb",
                      "& .MuiLinearProgress-bar": { bgcolor: color },
                    }}
                  />
                </Box>
              ))}
            </Paper>
            <Paper variant="outlined" sx={{ p: 3 }}>
              <Typography variant="h6" mb={2}>
                Needs attention
              </Typography>
              <Typography
                sx={{ fontSize: 46, fontWeight: 600, color: "warning.main" }}
              >
                {data.overdueCases}
              </Typography>
              <Typography variant="body2" mb={3}>
                Cases past their due date
              </Typography>
              <Alert severity={data.corrupt ? "warning" : "success"}>
                {data.corrupt
                  ? `${data.corrupt} files have an integrity mismatch. Review their reports in Files.`
                  : "No corrupt files in this region."}
              </Alert>
            </Paper>
          </Box>
        </>
      )}
    </>
  );
}
