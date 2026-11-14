// Originals live outside frontend and are never rewritten by build/generation.
import assets from "../../../contracts/examples/assets.json";
import file from "../../../contracts/examples/file.json";
import map from "../../../contracts/examples/map-features.json";
import checklist from "../../../contracts/examples/case-checklist.json";
import upload from "../../../contracts/examples/upload-session.json";
import reading from "../../../contracts/examples/meter-reading-ingest.json";
import regions from "../../../contracts/examples/regions.json";
import { REGION_INFO, REGIONS } from "../data/models";
import type {
  Region,
  RegionPage,
  NetworkAssetPage,
  FileResource,
  GeoJsonFeatureCollection,
  CaseDocumentChecklist,
  UploadSessionCreated,
  Subregion,
  AreaGeometry,
} from "../api/gen/types.gen";
import { coordinate } from "../data/api-mapping";

function areaGeometry(value: {
  type: string;
  coordinates: number[][][][];
}): AreaGeometry {
  if (value.type !== "MultiPolygon")
    throw new Error("Expected MultiPolygon geography fixture.");
  return {
    type: "MultiPolygon",
    coordinates: value.coordinates.map((polygon) =>
      polygon.map((ring) => ring.map(coordinate)),
    ),
  };
}

// JSON imports widen literal strings; these DTO assertions do not alter fixture bytes.
export const examples = {
  assets: assets as NetworkAssetPage,
  file: file as FileResource,
  map: map as GeoJsonFeatureCollection,
  checklist: checklist as CaseDocumentChecklist,
  upload: upload as UploadSessionCreated,
  reading,
  regions: {
    ...regions,
    items: regions.items.map(
      (row): Region => ({
        ...row,
        center: {
          type: "Point",
          coordinates: [row.center.coordinates[0], row.center.coordinates[1]],
        },
        geometry: areaGeometry(row.geometry),
        subregions: row.subregions.map(
          (subregion): Subregion => ({
            ...subregion,
            geometry: areaGeometry(subregion.geometry),
          }),
        ),
      }),
    ),
  },
};
// Keep example geography linked to the asset fixtures.
const ids = [...new Set(assets.items.map((x) => x.regionId))];
export const mockRegions: Region[] = REGIONS.map((code, i) => ({
  ...examples.regions.items!.find((region) => region.code === code),
  id: ids[i],
  code,
  name: REGION_INFO[code].name,
  center: { type: "Point", coordinates: REGION_INFO[code].center },
  bounds: { bbox: REGION_INFO[code].bbox },
}));
export const regionExample: RegionPage = {
  items: mockRegions,
  page: 0,
  size: 100,
  totalElements: mockRegions.length,
  totalPages: 1,
};
