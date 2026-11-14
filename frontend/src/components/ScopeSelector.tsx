import { MenuItem, Stack, TextField } from "@mui/material";
import { useGeography } from "../data/hooks";
import { REGIONS, REGION_INFO, type Region } from "../data/models";
import { useRegion } from "../data/region-context";
import { ErrorNotice } from "./common";

export function ScopeSelector() {
  const { selectedRegion, subregionId, setScope } = useRegion();
  const geography = useGeography();
  const segments =
    geography.data?.filter(
      (area) => area.parentId && area.region === selectedRegion,
    ) ?? [];
  return (
    <Stack direction="row" gap={1} alignItems="center" flexWrap="wrap">
      <TextField
        select
        size="small"
        label="Scope"
        value={selectedRegion ?? ""}
        slotProps={{
          select: { displayEmpty: true },
          inputLabel: { shrink: true },
        }}
        onChange={(event) =>
          setScope((event.target.value || null) as Region | null)
        }
        sx={{ minWidth: 130 }}
      >
        <MenuItem value="">Romania</MenuItem>
        {REGIONS.map((r) => (
          <MenuItem key={r} value={r}>
            {REGION_INFO[r].name}
          </MenuItem>
        ))}
      </TextField>
      {selectedRegion && (
        <TextField
          select
          size="small"
          label="Segment"
          value={subregionId ?? ""}
          onChange={(event) =>
            setScope(selectedRegion, event.target.value || undefined)
          }
          sx={{ minWidth: 175 }}
          error={
            !!subregionId &&
            !geography.isPending &&
            !segments.some((s) => s.id === subregionId)
          }
          helperText={
            subregionId &&
            !geography.isPending &&
            !segments.some((s) => s.id === subregionId)
              ? "Unknown segment for this region"
              : undefined
          }
        >
          <MenuItem value="">All segments</MenuItem>
          {segments.map((s) => (
            <MenuItem key={s.id} value={s.id}>
              {s.name}
            </MenuItem>
          ))}
        </TextField>
      )}
      {geography.error && <ErrorNotice error={geography.error} />}
    </Stack>
  );
}
