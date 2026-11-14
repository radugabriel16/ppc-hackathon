import type { Feature, FeatureCollection, LineString, Point } from "geojson";
import type {
  FileResource,
  GeoJsonFeatureCollection,
  MapIssue,
  NetworkAsset,
} from "../api/gen/types.gen";
import { contractError, requireValue } from "./api-client";
import type { Asset, FileRecord, Issue, Region } from "./models";

export function coordinate(value: unknown): [number, number] {
  if (
    !Array.isArray(value) ||
    value.length !== 2 ||
    !value.every((x) => typeof x === "number" && Number.isFinite(x)) ||
    Math.abs(value[0]) > 180 ||
    Math.abs(value[1]) > 90
  )
    throw contractError("Map coordinates must be [longitude, latitude].");
  return [value[0], value[1]];
}
export function fileRecord(dto: FileResource, region: Region): FileRecord {
  return {
    id: requireValue(dto.id, "file.id"),
    name: requireValue(dto.originalName, "file.originalName"),
    category: requireValue(dto.category, "file.category"),
    status: requireValue(dto.status, "file.status"),
    sizeBytes: requireValue(dto.sizeBytes, "file.sizeBytes"),
    region,
    createdAt: requireValue(dto.createdAt, "file.createdAt"),
    expectedSha256: dto.sha256 ?? "",
    actualSha256: "",
  };
}
export function issueRecord(dto: MapIssue, region: Region): Issue {
  return {
    id: requireValue(dto.id, "issue.id"),
    assetId: requireValue(dto.assetId, "issue.assetId"),
    region,
    description: dto.description ?? "No description supplied",
    severity: requireValue(dto.severity, "issue.severity"),
    status: requireValue(dto.status, "issue.status"),
    version: dto.version ?? null,
    coordinates: coordinate(dto.location?.coordinates),
  };
}
// GeoJSON's properties are completely untyped by the contract. Whitelist map data
// rather than forwarding arbitrary server properties (including possible PII).
export function mapCollection(
  raw: GeoJsonFeatureCollection,
  layer: "ASSETS",
  assets: NetworkAsset[],
): FeatureCollection<Point | LineString>;
export function mapCollection(
  raw: GeoJsonFeatureCollection,
  layer: "ISSUES" | "OUTAGES",
  assets?: NetworkAsset[],
): FeatureCollection<Point>;
export function mapCollection(
  raw: GeoJsonFeatureCollection,
  layer: string,
  assets: NetworkAsset[] = [],
): FeatureCollection<Point | LineString> {
  if (raw.type !== "FeatureCollection" || !Array.isArray(raw.features))
    throw contractError("Expected a GeoJSON FeatureCollection.");
  const features: Feature<Point | LineString>[] = raw.features.map((dto) => {
    const p = dto.properties ?? {};
    const g = dto.geometry;
    let geometry: Point | LineString;
    if (g?.type === "Point")
      geometry = { type: "Point", coordinates: coordinate(g.coordinates) };
    else if (
      layer === "OUTAGES" &&
      g?.type === "LineString" &&
      Array.isArray(g.coordinates) &&
      g.coordinates.length >= 2
    )
      geometry = { type: "Point", coordinates: coordinate(g.coordinates[0]) };
    else if (
      layer === "ASSETS" &&
      g?.type === "LineString" &&
      Array.isArray(g.coordinates) &&
      g.coordinates.length >= 2
    )
      geometry = {
        type: "LineString",
        coordinates: g.coordinates.map(coordinate),
      };
    else throw contractError(`Unsupported ${layer} geometry.`);
    const id = typeof p.id === "string" ? p.id : undefined;
    if (!id) throw contractError("Map feature is missing properties.id.");
    const properties: Record<string, unknown> = { id };
    if (layer === "ASSETS") {
      const asset = assets.find((a) => a.id === id);
      const type = p.assetType ?? p.type ?? asset?.type;
      if (
        type !== "SUBSTATION" &&
        type !== "TRANSFORMER" &&
        type !== "LINE_SEGMENT"
      )
        throw contractError("Map asset type is missing or unsupported.");
      properties.type = type;
      properties.name =
        typeof p.name === "string"
          ? p.name
          : (asset?.name ?? asset?.code ?? id);
    } else if (layer === "ISSUES") {
      if (
        !["OPEN", "IN_PROGRESS", "RESOLVED"].includes(String(p.status)) ||
        !["LOW", "MEDIUM", "HIGH", "CRITICAL"].includes(String(p.severity)) ||
        typeof p.assetId !== "string"
      )
        throw contractError(
          "Issue map feature lacks assetId, severity or status.",
        );
      for (const key of ["assetId", "status", "severity"])
        properties[key] = p[key];
      properties.description =
        typeof p.description === "string"
          ? p.description
          : "No description supplied";
      properties.version =
        typeof p.version === "number" &&
        Number.isInteger(p.version) &&
        p.version >= 0
          ? p.version
          : null;
    } else {
      properties.name = typeof p.name === "string" ? p.name : "Outage";
      properties.affectedAssets =
        typeof p.affectedAssets === "number" ? p.affectedAssets : "unknown";
    }
    return { type: "Feature", id, geometry, properties };
  });
  return { type: "FeatureCollection", features };
}
export function assetList(
  collection: FeatureCollection<Point | LineString>,
  region: Region,
): Asset[] {
  return collection.features.map((f) => ({
    id: String(f.properties!.id),
    name: String(f.properties!.name),
    type: f.properties!.type as Asset["type"],
    region,
    coordinates: coordinate(
      f.geometry.type === "Point"
        ? f.geometry.coordinates
        : f.geometry.coordinates[0],
    ),
  }));
}
export function issueList(
  collection: FeatureCollection<Point>,
  region: Region,
): Issue[] {
  return collection.features.map((f) =>
    issueRecord(
      {
        id: String(f.properties!.id),
        assetId: String(f.properties!.assetId),
        description: String(f.properties!.description),
        severity: f.properties!.severity as Issue["severity"],
        status: f.properties!.status as Issue["status"],
        version: f.properties!.version as number | undefined,
        location: {
          type: "Point",
          coordinates: coordinate(f.geometry.coordinates),
        },
      },
      region,
    ),
  );
}
