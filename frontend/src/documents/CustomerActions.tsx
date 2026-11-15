import { useEffect, useRef, useState } from "react";
import {
  Alert, Box, Button, Dialog, DialogActions, DialogContent, DialogTitle,
  IconButton, MenuItem, Stack, TextField, Typography,
} from "@mui/material";
import { Visibility, VisibilityOff } from "@mui/icons-material";
import { useSource } from "../data/context";
import { useGeography } from "../data/hooks";
import { useRegion } from "../data/region-context";
import { validCnp } from "../data/document-intake";
import type { CustomerResource } from "../api/gen/types.gen";
import type { Region } from "../data/models";

export function CnpReveal({
  customerId, cnpMasked,
}: { customerId?: string; cnpMasked?: string | null }) {
  const api = useSource().documentIntake;
  const [cnp, setCnp] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const generation = useRef(0);
  useEffect(() => () => { generation.current += 1; }, []);
  useEffect(() => {
    if (!cnp) return;
    const timer = window.setTimeout(() => setCnp(null), 30000);
    return () => window.clearTimeout(timer);
  }, [cnp]);
  async function toggle() {
    if (cnp) {
      setCnp(null);
      return;
    }
    if (!api || !customerId) return;
    const current = ++generation.current;
    setBusy(true);
    setError("");
    try {
      const result = await api.revealCnp(customerId);
      if (current === generation.current) setCnp(result.cnp);
    } catch (e) {
      if (current === generation.current)
        setError(e instanceof Error ? e.message : "CNP reveal failed.");
    } finally {
      if (current === generation.current) setBusy(false);
    }
  }
  return (
    <Box>
      <Stack direction="row" alignItems="center" gap={1}>
        <Typography variant="body2">{cnp ?? cnpMasked ?? "Unavailable"}</Typography>
        <IconButton
          size="small"
          aria-label={cnp ? "Hide CNP" : "Show CNP"}
          disabled={busy || !api || !customerId || !cnpMasked}
          onClick={() => void toggle()}
        >
          {cnp ? <VisibilityOff fontSize="small" /> : <Visibility fontSize="small" />}
        </IconButton>
      </Stack>
      {error && <Alert severity="error">{error}</Alert>}
    </Box>
  );
}

export function NewCustomerButton({
  onCreated,
}: { onCreated: (customer: CustomerResource, region: Region) => void }) {
  const api = useSource().documentIntake;
  const { selectedRegion, subregionId } = useRegion();
  const geography = useGeography();
  const [open, setOpen] = useState(false);
  const [name, setName] = useState("");
  const [cnp, setCnp] = useState("");
  const [segmentId, setSegmentId] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const needsSegment = !selectedRegion && !subregionId;
  const regionId = geography.data?.find(
    (area) => area.parentId === null && area.region === selectedRegion,
  )?.id;
  const selectedSegment = subregionId ?? (needsSegment ? segmentId : undefined);
  function close() {
    setOpen(false);
    setName("");
    setCnp("");
    setSegmentId("");
    setError("");
  }
  async function submit() {
    if (!api || !name.trim() || !validCnp(cnp)) return;
    if (!regionId && !selectedSegment) {
      setError("Select a segment for this client.");
      return;
    }
    const scopedRegion = selectedRegion ?? geography.data?.find(
      (area) => area.id === selectedSegment,
    )?.region;
    if (!scopedRegion) {
      setError("Workspace geography is unavailable. Select the scope again.");
      return;
    }
    setBusy(true);
    setError("");
    try {
      const customer = await api.createCustomer({
        name: name.trim(), cnp, regionId, segmentId: selectedSegment,
      });
      onCreated(customer, scopedRegion);
      close();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Client creation failed.");
    } finally {
      setBusy(false);
    }
  }
  return (
    <>
      <Button variant="contained" disabled={!api} onClick={() => setOpen(true)}>
        New client
      </Button>
      <Dialog open={open} onClose={() => { if (!busy) close(); }} fullWidth>
        <Box component="form" onSubmit={(e) => { e.preventDefault(); void submit(); }}>
          <DialogTitle>New client</DialogTitle>
          <DialogContent>
            <Stack gap={2} sx={{ pt: 1 }}>
              <TextField
                label="Name" value={name} required disabled={busy}
                onChange={(e) => setName(e.target.value)}
                inputProps={{ maxLength: 128 }} autoComplete="off"
              />
              <TextField
                label="CNP" value={cnp} required disabled={busy}
                onChange={(e) => setCnp(e.target.value)}
                inputProps={{ maxLength: 13, inputMode: "numeric" }} autoComplete="off"
                error={!!cnp && !validCnp(cnp)}
                helperText={cnp && !validCnp(cnp) ? "Enter a valid 13-digit CNP." : undefined}
              />
              {needsSegment && (
                <TextField select label="Segment" value={segmentId} required disabled={busy}
                  onChange={(e) => setSegmentId(e.target.value)}>
                  {geography.data?.filter((area) => area.parentId !== null).map((area) => (
                    <MenuItem key={area.id} value={area.id}>{area.name}</MenuItem>
                  ))}
                </TextField>
              )}
              {geography.error && (
                <Alert severity="error">{geography.error.message}</Alert>
              )}
              {error && <Alert severity="error">{error}</Alert>}
            </Stack>
          </DialogContent>
          <DialogActions>
            <Button disabled={busy} onClick={close}>Cancel</Button>
            <Button type="submit" variant="contained"
              disabled={busy || !name.trim() || !validCnp(cnp) || (!regionId && !selectedSegment)}>
              {busy ? "Creating..." : "Create client"}
            </Button>
          </DialogActions>
        </Box>
      </Dialog>
    </>
  );
}
