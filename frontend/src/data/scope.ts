import {
  REGIONS,
  type ForecastRunCreate,
  type GeographicArea,
  type Region,
} from "./models";

export function forecastRunInput(
  regionId?: string,
  segmentId?: string,
): ForecastRunCreate {
  if (segmentId) return { scope: "segment", segmentId, regionId };
  if (regionId) return { scope: "region", regionId };
  return { scope: "country" };
}

export function readScope(params: URLSearchParams) {
  const value = params.get("region");
  const selectedRegion = REGIONS.find((region) => region === value) ?? null;
  return {
    region: selectedRegion ?? ("MUNTENIA" as Region),
    selectedRegion,
    subregionId: selectedRegion
      ? (params.get("segment") ?? undefined)
      : undefined,
  };
}

export function selectScope(
  params: URLSearchParams,
  region: Region | null,
  segmentId?: string,
) {
  const next = new URLSearchParams(params);
  next.delete("issue");
  next.delete("run");
  if (region) next.set("region", region);
  else next.delete("region");
  if (region && segmentId) next.set("segment", segmentId);
  else next.delete("segment");
  return next;
}

export function selectedAreaId(
  areas: GeographicArea[],
  region: Region | null,
  segmentId?: string,
) {
  return segmentId ?? areas.find((a) => !a.parentId && a.region === region)?.id;
}
