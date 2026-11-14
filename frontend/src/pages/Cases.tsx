import { useState } from "react";
import {
  Box,
  Checkbox,
  Chip,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  TablePagination,
  TextField,
  Typography,
} from "@mui/material";
import { AccessTime, Search } from "@mui/icons-material";
import { useCases } from "../data/hooks";
import { label } from "../data/models";
import type { CaseRecord } from "../data/models";
import { useRegion } from "../data/region-context";
import {
  Empty,
  ErrorNotice,
  Loading,
  PageHeading,
  StatusChip,
} from "../components/common";

export function CasesPage() {
  const { region } = useRegion();
  return <CasesContent key={region} />;
}
function CasesContent() {
  const { region } = useRegion();
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<CaseRecord["status"] | "">("");
  const [page, setPage] = useState(0);
  const query = useCases({
    region,
    search,
    status: status || undefined,
    page,
    size: 6,
  });
  return (
    <>
      <PageHeading
        eyebrow="CASE WORKSPACE"
        title="Keep every case moving."
        detail="Ordered by due date. See the evidence you have and the documents still missing."
      />
      <Paper variant="outlined" sx={{ p: 2.5, mb: 2.5 }}>
        <Stack direction={{ xs: "column", sm: "row" }} gap={2}>
          <TextField
            label="Search cases"
            value={search}
            onChange={(e) => {
              setSearch(e.target.value);
              setPage(0);
            }}
            sx={{ flex: 1 }}
            InputProps={{
              startAdornment: (
                <InputAdornment position="start">
                  <Search fontSize="small" />
                </InputAdornment>
              ),
            }}
          />
          <TextField
            select
            label="Case status"
            value={status}
            onChange={(e) => {
              setStatus(e.target.value as CaseRecord["status"] | "");
              setPage(0);
            }}
            sx={{ minWidth: 180 }}
          >
            <MenuItem value="">All statuses</MenuItem>
            {["OPEN", "REVIEW", "COMPLETE"].map((x) => (
              <MenuItem key={x} value={x}>
                {label(x)}
              </MenuItem>
            ))}
          </TextField>
          <Chip
            icon={<AccessTime />}
            label="Earliest due first"
            variant="outlined"
            sx={{ alignSelf: "center" }}
          />
        </Stack>
      </Paper>
      {query.isPending && <Loading />}
      {query.error && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {query.data &&
        (query.data.items.length ? (
          <Box
            sx={{
              display: "grid",
              gridTemplateColumns: { xs: "1fr", lg: "1fr 1fr" },
              gap: 2,
            }}
          >
            {query.data.items.map((item) => {
              const overdue =
                item.status !== "COMPLETE" &&
                !!item.dueAt &&
                Date.parse(item.dueAt) < Date.now();
              const missing = item.documents.filter((d) => !d.received).length;
              return (
                <Paper variant="outlined" key={item.id} sx={{ p: 2.5 }}>
                  <Stack
                    direction="row"
                    justifyContent="space-between"
                    mb={1.4}
                  >
                    <Typography className="eyebrow">{item.id}</Typography>
                    <StatusChip status={item.status} />
                  </Stack>
                  <Typography variant="h6">{item.title}</Typography>
                  <Stack
                    direction="row"
                    gap={1}
                    alignItems="center"
                    mt={1}
                    mb={2}
                  >
                    <AccessTime
                      sx={{
                        fontSize: 15,
                        color: overdue ? "error.main" : "text.secondary",
                      }}
                    />
                    <Typography
                      variant="caption"
                      color={overdue ? "error.main" : "text.secondary"}
                    >
                      {overdue ? "Overdue · " : "Due "}
                      {item.dueAt
                        ? new Date(item.dueAt).toLocaleString("en-GB", {
                            timeZone: "Europe/Bucharest",
                            day: "2-digit",
                            month: "short",
                            hour: "2-digit",
                            minute: "2-digit",
                          })
                        : "No due date"}
                    </Typography>
                  </Stack>
                  <Box sx={{ bgcolor: "#f7f9f4", borderRadius: 2, p: 1.5 }}>
                    <Stack
                      direction="row"
                      justifyContent="space-between"
                      mb={1}
                    >
                      <Typography variant="caption" fontWeight={600}>
                        Document checklist
                      </Typography>
                      <Typography
                        variant="caption"
                        color={missing ? "warning.main" : "primary.main"}
                      >
                        {missing ? `${missing} missing` : "All received"}
                      </Typography>
                    </Stack>
                    {item.documents.map((doc) => (
                      <Stack
                        direction="row"
                        alignItems="center"
                        key={doc.name}
                        spacing={1}
                      >
                        <Checkbox
                          checked={doc.received}
                          disabled
                          size="small"
                          sx={{
                            p: 0.4,
                            "&.Mui-disabled": {
                              color: doc.received ? "#4b8461" : "#c4c9c1",
                            },
                          }}
                          inputProps={{
                            "aria-label": `${doc.name}: ${doc.received ? "received" : "missing"}`,
                          }}
                        />
                        <Typography
                          variant="body2"
                          color={
                            doc.received ? "text.secondary" : "text.primary"
                          }
                        >
                          {doc.name}
                        </Typography>
                        {!doc.received && (
                          <Typography variant="caption" color="warning.main">
                            Missing
                          </Typography>
                        )}
                      </Stack>
                    ))}
                  </Box>
                </Paper>
              );
            })}
          </Box>
        ) : (
          <Paper variant="outlined">
            <Empty title="No cases found" />
          </Paper>
        ))}
      <TablePagination
        component="div"
        count={query.data?.totalElements ?? 0}
        page={page}
        rowsPerPage={6}
        rowsPerPageOptions={[6]}
        onPageChange={(_, p) => setPage(p)}
      />
    </>
  );
}
