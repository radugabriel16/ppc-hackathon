// Originals live outside frontend and are never rewritten by build/generation.
import assets from "../../../contracts/examples/assets.json";
import file from "../../../contracts/examples/file.json";
import map from "../../../contracts/examples/map-features.json";
import checklist from "../../../contracts/examples/case-checklist.json";
import upload from "../../../contracts/examples/upload-session.json";
import reading from "../../../contracts/examples/meter-reading-ingest.json";
import { REGION_INFO, REGIONS } from "../data/models";
import type {
  Region,
  RegionPage,
  NetworkAssetPage,
  FileResource,
  GeoJsonFeatureCollection,
  CaseDocumentChecklist,
  UploadSessionCreated,
} from "../api/gen/types.gen";

// JSON imports widen literal strings; these DTO assertions do not alter fixture bytes.
export const examples = {
  assets: assets as NetworkAssetPage,
  file: file as FileResource,
  map: map as GeoJsonFeatureCollection,
  checklist: checklist as CaseDocumentChecklist,
  upload: upload as UploadSessionCreated,
  reading,
};
// No regions or case-list example was supplied. These explicit mock-only records
// link the IDs in the supplied examples; they are not claimed to be contract examples.
const ids = [...new Set(assets.items.map((x) => x.regionId))];
export const mockRegions: Region[] = REGIONS.map((code, i) => ({
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
