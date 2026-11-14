import { Box, Breadcrumbs, Button, Stack, Typography } from "@mui/material";
import type { GeographicArea } from "../data/models";

export interface GeographySelectionProps {
  areas: GeographicArea[];
  selectedId?: string;
  onSelect: (area?: GeographicArea) => void;
}

export function GeographyExplorer({
  areas,
  selectedId,
  onSelect,
}: GeographySelectionProps) {
  const selected = areas.find((area) => area.id === selectedId);
  const parent = selected?.parentId
    ? areas.find((area) => area.id === selected.parentId)
    : selected;
  const choices = parent
    ? areas.filter((area) => area.parentId === parent.id)
    : areas.filter((area) => !area.parentId);
  return (
    <Box sx={{ px: 2, py: 1.5 }}>
      <Breadcrumbs aria-label="Geography breadcrumb" separator=">">
        <Button
          size="small"
          onClick={() => onSelect()}
          aria-current={!selected ? "location" : undefined}
        >
          Romania
        </Button>
        {parent && (
          <Button
            size="small"
            onClick={() => onSelect(parent)}
            aria-current={!selected?.parentId ? "location" : undefined}
          >
            {parent.name}
          </Button>
        )}
        {selected?.parentId && (
          <Typography aria-current="location">{selected.name}</Typography>
        )}
      </Breadcrumbs>
      <Typography variant="caption" color="text.secondary">
        Click a region to explore. Use the list below or Escape to go back.
      </Typography>
      <Stack
        component="ul"
        aria-label={parent ? "Subregions" : "Regions"}
        direction="row"
        flexWrap="wrap"
        gap={0.5}
        sx={{ listStyle: "none", p: 0, m: "8px 0 0" }}
      >
        {choices.map((area) => (
          <Box component="li" key={area.id}>
            <Button
              size="small"
              variant={area.id === selectedId ? "contained" : "outlined"}
              aria-pressed={area.id === selectedId}
              onClick={() => onSelect(area)}
            >
              {area.name} · {area.meterCount} meters
            </Button>
          </Box>
        ))}
      </Stack>
    </Box>
  );
}
