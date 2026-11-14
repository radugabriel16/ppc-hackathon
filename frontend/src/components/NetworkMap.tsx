import { useEffect, useRef, useState } from "react";
import { Alert, Box, Button } from "@mui/material";
import maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as LibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import { REGION_INFO } from "../data/models";
import type { Asset, MapData, Region } from "../data/models";

interface Props {
  data: MapData;
  region: Region;
  resolved: boolean;
  layers: { assets: boolean; issues: boolean; outages: boolean };
  onCreate: (assetId?: string) => void;
  onIssue: (id: string) => void;
}
const empty = { type: "FeatureCollection" as const, features: [] };
const issueFilter = (resolved: boolean): maplibregl.FilterSpecification =>
  resolved ? ["has", "status"] : ["!=", ["get", "status"], "RESOLVED"];
function update(map: LibreMap, props: Props) {
  (map.getSource("assets") as GeoJSONSource)?.setData(props.data.assets);
  (map.getSource("issues") as GeoJSONSource)?.setData(props.data.issues);
  (map.getSource("outages") as GeoJSONSource)?.setData(props.data.outages);
  const bbox = REGION_INFO[props.region].bbox;
  (map.getSource("region") as GeoJSONSource)?.setData({
    type: "Feature",
    properties: {},
    geometry: {
      type: "Polygon",
      coordinates: [
        [
          [bbox[0], bbox[1]],
          [bbox[2], bbox[1]],
          [bbox[2], bbox[3]],
          [bbox[0], bbox[3]],
          [bbox[0], bbox[1]],
        ],
      ],
    },
  });
  for (const [key, ids] of Object.entries({
    assets: ["asset-points", "asset-lines"],
    issues: ["issue-points"],
    outages: ["outage-points"],
  })) {
    for (const id of ids)
      map.setLayoutProperty(
        id,
        "visibility",
        props.layers[key as keyof Props["layers"]] ? "visible" : "none",
      );
  }
  map.setFilter("issue-points", issueFilter(props.resolved));
}
export function NetworkMap(props: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<LibreMap | null>(null);
  const latest = useRef(props);
  const previousRegion = useRef(props.region);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    latest.current = props;
    if (map.current?.isStyleLoaded()) update(map.current, props);
  }, [props]);
  useEffect(() => {
    if (!container.current) return;
    let instance: LibreMap;
    try {
      instance = new maplibregl.Map({
        container: container.current,
        style: "https://tiles.openfreemap.org/styles/positron",
        center: [25.1, 45.8],
        zoom: 5.7,
        attributionControl: false,
      });
    } catch (error) {
      setError(
        error instanceof Error ? error.message : "WebGL could not initialize.",
      );
      return;
    }
    map.current = instance;
    instance.addControl(
      new maplibregl.NavigationControl({ showCompass: false }),
      "top-right",
    );
    instance.addControl(
      new maplibregl.AttributionControl({
        compact: false,
        customAttribution:
          '<a href="https://openfreemap.org" target="_blank" rel="noopener">OpenFreeMap</a> · <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener">© OpenStreetMap contributors</a>',
      }),
      "bottom-right",
    );
    instance.on("error", () =>
      setError(
        "Map tiles could not load. Check your connection; the issue list remains available.",
      ),
    );
    instance.on("load", () => {
      setError("");
      setReady(true);
      for (const id of ["assets", "issues", "outages", "region"])
        instance.addSource(id, { type: "geojson", data: empty });
      instance.addLayer({
        id: "region-fill",
        type: "fill",
        source: "region",
        paint: { "fill-color": "#176747", "fill-opacity": 0.035 },
      });
      instance.addLayer({
        id: "region-line",
        type: "line",
        source: "region",
        paint: {
          "line-color": "#438568",
          "line-width": 1.4,
          "line-dasharray": [4, 4],
        },
      });
      instance.addLayer({
        id: "asset-lines",
        type: "line",
        source: "assets",
        filter: ["==", ["geometry-type"], "LineString"],
        paint: { "line-color": "#25816e", "line-width": 3.5 },
      });
      instance.addLayer({
        id: "outage-points",
        type: "circle",
        source: "outages",
        paint: {
          "circle-radius": 22,
          "circle-color": "#9b70ba",
          "circle-opacity": 0.3,
          "circle-stroke-width": 2,
          "circle-stroke-color": "#8e5daf",
        },
      });
      instance.addLayer({
        id: "asset-points",
        type: "circle",
        source: "assets",
        filter: ["==", ["geometry-type"], "Point"],
        paint: {
          "circle-radius": ["match", ["get", "type"], "SUBSTATION", 8, 5],
          "circle-color": [
            "match",
            ["get", "type"],
            "SUBSTATION",
            "#176747",
            "#457b9d",
          ],
          "circle-stroke-color": "#ffffff",
          "circle-stroke-width": 2,
        },
      });
      instance.addLayer({
        id: "issue-points",
        type: "circle",
        source: "issues",
        paint: {
          "circle-radius": 7,
          "circle-color": [
            "match",
            ["get", "status"],
            "OPEN",
            "#d44c53",
            "IN_PROGRESS",
            "#e2b23d",
            "#6e9e8a",
          ],
          "circle-stroke-width": 2.5,
          "circle-stroke-color": "#fff",
          "circle-translate": [12, -12],
        },
      });
      update(instance, latest.current);
    });
    instance.on("click", (event) => {
      if (!instance.getLayer("asset-points")) return;
      const features = instance.queryRenderedFeatures(event.point, {
        layers: [
          "issue-points",
          "asset-points",
          "asset-lines",
          "outage-points",
        ],
      });
      const feature = features[0];
      if (!feature) {
        // Offer a nearby asset; users can choose a different asset in the dialog.
        const distance = (asset: Asset) =>
          (asset.coordinates[0] - event.lngLat.lng) ** 2 +
          (asset.coordinates[1] - event.lngLat.lat) ** 2;
        const nearest = [...latest.current.data.assetList].sort(
          (a, b) => distance(a) - distance(b),
        )[0];
        latest.current.onCreate(nearest?.id);
        return;
      }
      const properties = feature.properties;
      const content = document.createElement("div");
      const title = document.createElement("strong");
      title.textContent = String(properties.name ?? properties.id);
      content.append(title);
      const detail = document.createElement("div");
      detail.textContent = String(
        properties.description ??
          properties.type ??
          `Affected assets: ${properties.affectedAssets}`,
      );
      content.append(detail);
      if (feature.layer.id === "issue-points") {
        latest.current.onIssue(String(properties.id));
        const status = document.createElement("div");
        status.textContent = String(properties.status).replaceAll("_", " ");
        content.append(status);
      } else if (feature.layer.id.startsWith("asset-")) {
        const button = document.createElement("button");
        button.className = "popup-action";
        button.textContent = "Create issue";
        button.onclick = () => latest.current.onCreate(String(properties.id));
        content.append(button);
      }
      new maplibregl.Popup({ closeButton: true, maxWidth: "280px" })
        .setLngLat(event.lngLat)
        .setDOMContent(content)
        .addTo(instance);
    });
    const resize = new ResizeObserver(() => instance.resize());
    resize.observe(container.current);
    return () => {
      resize.disconnect();
      instance.remove();
      map.current = null;
    };
  }, []);
  useEffect(() => {
    if (previousRegion.current !== props.region) {
      previousRegion.current = props.region;
      const b = REGION_INFO[props.region].bbox;
      map.current?.fitBounds(
        [
          [b[0], b[1]],
          [b[2], b[3]],
        ],
        { padding: 45, duration: 800 },
      );
    }
  }, [props.region]);
  const zoomRegion = () => {
    const b = REGION_INFO[props.region].bbox;
    map.current?.fitBounds(
      [
        [b[0], b[1]],
        [b[2], b[3]],
      ],
      { padding: 50 },
    );
  };
  return (
    <Box sx={{ position: "relative" }}>
      <Box
        ref={container}
        className="map-container"
        aria-label="Romania electricity network map"
      />
      {error && (
        <Alert
          severity="warning"
          sx={{ position: "absolute", bottom: 48, left: 12, right: 12 }}
        >
          {error}
        </Alert>
      )}
      <Button
        size="small"
        variant="contained"
        disabled={!ready}
        onClick={zoomRegion}
        sx={{
          position: "absolute",
          top: 14,
          left: 14,
          bgcolor: "white",
          color: "primary.dark",
          boxShadow: "0 1px 8px #0002",
          "&:hover": { bgcolor: "#eff4ed" },
        }}
      >
        Zoom to {REGION_INFO[props.region].name}
      </Button>
    </Box>
  );
}
