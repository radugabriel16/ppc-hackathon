import { useEffect, useState } from "react";
import { useQueryClient } from "@tanstack/react-query";
import { useSearchParams } from "react-router-dom";
import {
  Box,
  Button,
  Checkbox,
  Chip,
  InputAdornment,
  MenuItem,
  Paper,
  Stack,
  TablePagination,
  TextField,
  Typography,
  Alert,
  ToggleButton,
  ToggleButtonGroup,
  Table,
  TableBody,
  TableCell,
  TableContainer,
  TableHead,
  TableRow,
} from "@mui/material";
import { AccessTime, Search } from "@mui/icons-material";
import { IntakeWorkspace, type UploadSlot } from "../documents/IntakeWorkspace";
import { CnpReveal, NewCustomerButton } from "../documents/CustomerActions";
import type { IntakeDocumentType } from "../api/gen/types.gen";
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

export function CasesPage({ documents = false }: { documents?: boolean }) {
  const { selectedRegion, subregionId } = useRegion();
  return (
    <CasesContent
      key={`${documents}:${selectedRegion}:${subregionId}`}
      documents={documents}
    />
  );
}
const VIEW_KEY = "filegrid.cases-view";
function storedView(): { view: "list" | "grid"; error: string } {
  try {
    return {
      view: localStorage.getItem(VIEW_KEY) === "list" ? "list" : "grid",
      error: "",
    };
  } catch {
    return { view: "grid", error: "View preference storage is unavailable." };
  }
}
function CasesContent({ documents }: { documents: boolean }) {
  const { selectedRegion, subregionId } = useRegion();
  const [params] = useSearchParams();
  const [preference, setPreference] = useState(() =>
    documents ? { view: "list" as const, error: "" } : storedView(),
  );
  const cache = useQueryClient();
  const [created, setCreated] = useState<CaseRecord[]>([]);
  const [priorityCaseId, setPriorityCaseId] = useState<string>();
  const [uploadSlot, setUploadSlot] = useState<UploadSlot | null>(null);
  const [previewId, setPreviewId] = useState<string | null>(null);
  const [missingOnly, setMissingOnly] = useState(true);
  const [search, setSearch] = useState("");
  const [status, setStatus] = useState<CaseRecord["status"] | "">("");
  const [page, setPage] = useState(0);
  const query = useCases({
    clientId: params.get("clientId") || undefined,
    caseId: params.get("caseId") || undefined,
    priorityCaseId,
    region: selectedRegion ?? undefined,
    segmentId: subregionId,
    missingOnly,
    search,
    status: status || undefined,
    page,
    size: 6,
  });
  useEffect(() => {
    if (query.isSuccess && !query.isFetching) setCreated([]);
  }, [query.data, query.isSuccess, query.isFetching]);
  const items = [
    ...(page === 0 ? created : []),
    ...(query.data?.items ?? []).filter(
      (item) => page !== 0 || !created.some((row) => row.id === item.id),
    ),
  ].slice(0, 6);
  const revealKey = `${page}:${search}:${status}:${missingOnly}:${preference.view}`;
  return (
    <>
      <PageHeading
        eyebrow={documents ? "DOCUMENT WORKSPACE" : "CASE WORKSPACE"}
        title={documents ? "Manage Customer Documents" : "Connection cases"}
        detail={
          documents
            ? "Load documents, review unmatched files and track every client checklist. Region and segment follow the workspace scope."
            : "Track connection cases and required documents. Region and segment follow the workspace scope."
        }
      />
      <IntakeWorkspace
        slot={uploadSlot}
        clearSlot={() => setUploadSlot(null)}
        previewId={previewId}
        clearPreview={() => setPreviewId(null)}
        primaryAction={documents ? (
          <NewCustomerButton onCreated={(customer, region) => {
            setCreated((rows) => [{
              id: customer.caseId, customerId: customer.id,
              customerName: customer.name, cnpMasked: customer.cnpMasked,
              title: customer.name, region, status: "OPEN", dueAt: null,
              intakeDocuments: customer.documents,
              documents: customer.documents.map((doc) => ({ name: doc.name, received: false })),
            }, ...rows]);
            setPriorityCaseId(customer.caseId);
            setPage(0);
            setSearch("");
            setStatus("");
            setMissingOnly(true);
            void cache.invalidateQueries({ queryKey: ["cases"] });
          }} />
        ) : undefined}
      />
      <Button
        onClick={() => {
          setMissingOnly(!missingOnly);
          setPage(0);
        }}
      >
        {missingOnly
          ? "Show all clients"
          : "Show clients with missing documents"}
      </Button>
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
            {["OPEN", "COMPLETE"].map((x) => (
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
          <ToggleButtonGroup
            exclusive
            value={preference.view}
            aria-label="Cases view"
            size="small"
            onChange={(_, view: "list" | "grid" | null) => {
              if (!view) return;
              try {
                localStorage.setItem(VIEW_KEY, view);
                setPreference({ view, error: "" });
              } catch {
                setPreference({
                  view,
                  error: "Could not remember the view preference.",
                });
              }
            }}
          >
            <ToggleButton value="list" aria-label="List view">
              List
            </ToggleButton>
            <ToggleButton value="grid" aria-label="Grid view">
              Grid
            </ToggleButton>
          </ToggleButtonGroup>
        </Stack>
      </Paper>
      {preference.error && <Alert severity="warning">{preference.error}</Alert>}
      {query.isPending && <Loading />}
      {query.error && (
        <ErrorNotice error={query.error} retry={() => void query.refetch()} />
      )}
      {(query.data || created.length > 0) &&
        (items.length ? (
          preference.view === "list" ? (
            <TableContainer component={Paper} variant="outlined">
              <Table aria-label="Clients missing documents">
                <TableHead>
                  <TableRow>
                    <TableCell>Client / case</TableCell>
                    {documents && <TableCell>CNP</TableCell>}
                    <TableCell>Status</TableCell>
                    <TableCell>Due</TableCell>
                    <TableCell>Missing documents</TableCell>
                  </TableRow>
                </TableHead>
                <TableBody>
                  {items.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell>
                        {item.customerName ?? item.title}
                        {!documents && item.cnpMasked && (
                          <Typography variant="caption" display="block">
                            CNP {item.cnpMasked}
                          </Typography>
                        )}
                        <Typography variant="caption" display="block">
                          {item.id}
                        </Typography>
                      </TableCell>
                      {documents && (
                        <TableCell>
                          <CnpReveal key={`${item.id}:${revealKey}`}
                            customerId={item.customerId} cnpMasked={item.cnpMasked} />
                        </TableCell>
                      )}
                      <TableCell>
                        <StatusChip status={item.status} />
                      </TableCell>
                      <TableCell>
                        {item.dueAt
                          ? new Date(item.dueAt).toLocaleDateString()
                          : "No due date"}
                      </TableCell>
                      <TableCell>
                        {item.intakeDocuments?.length
                          ? item.intakeDocuments.map((doc) => (
                              <Button
                                key={doc.documentType}
                                size="small"
                                onClick={() => {
                                  if (doc.fileId) setPreviewId(doc.fileId);
                                  else if (item.customerId)
                                    setUploadSlot({
                                      customerId: item.customerId,
                                      documentType:
                                        doc.documentType as IntakeDocumentType,
                                      customerName:
                                        item.customerName ?? item.title,
                                    });
                                }}
                              >
                                {doc.name} — {doc.status}
                              </Button>
                            ))
                          : item.documents
                              .filter((d) => !d.received)
                              .map((d) => d.name)
                              .join(", ")}
                      </TableCell>
                    </TableRow>
                  ))}
                </TableBody>
              </Table>
            </TableContainer>
          ) : (
            <Box
              aria-label="Cases grid"
              sx={{
                display: "grid",
                gridTemplateColumns: { xs: "1fr", lg: "1fr 1fr" },
                gap: 2,
              }}
            >
              {items.map((item) => {
                const overdue =
                  item.status !== "COMPLETE" &&
                  !!item.dueAt &&
                  Date.parse(item.dueAt) < Date.now();
                const missing = item.documents.filter(
                  (d) => !d.received,
                ).length;
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
                    <Typography variant="h6">
                      {item.customerName ?? item.title}
                    </Typography>
                    {documents ? (
                      <CnpReveal key={`${item.id}:${revealKey}`}
                        customerId={item.customerId} cnpMasked={item.cnpMasked} />
                    ) : item.cnpMasked && (
                      <Typography variant="caption">
                        CNP {item.cnpMasked}
                      </Typography>
                    )}
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
                      {item.intakeDocuments?.map((doc) => (
                        <Button
                          key={doc.documentType}
                          fullWidth
                          sx={{ justifyContent: "flex-start" }}
                          onClick={() => {
                            if (doc.fileId) setPreviewId(doc.fileId);
                            else if (item.customerId)
                              setUploadSlot({
                                customerId: item.customerId,
                                documentType:
                                  doc.documentType as IntakeDocumentType,
                                customerName: item.customerName ?? item.title,
                              });
                          }}
                        >
                          {doc.name} — {doc.status}
                        </Button>
                      ))}
                      {!item.intakeDocuments?.length &&
                        item.documents.map((doc) => (
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
                              <Typography
                                variant="caption"
                                color="warning.main"
                              >
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
          )
        ) : (
          <Paper variant="outlined">
            <Empty title="No cases found" />
          </Paper>
        ))}
      <TablePagination
        component="div"
        count={Math.max(query.data?.totalElements ?? 0, items.length)}
        page={page}
        rowsPerPage={6}
        rowsPerPageOptions={[6]}
        onPageChange={(_, p) => setPage(p)}
      />
    </>
  );
}
