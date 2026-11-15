import { useEffect, useRef, useState } from "react";
import { Alert, Box, Button, Menu, MenuItem, Snackbar } from "@mui/material";
import maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as LibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Asset, CreateIssue, MapData, Region } from "../data/models";
import type { GeographySelectionProps } from "./GeographyExplorer";
import { areaBounds, areaFeatures, reportArea } from "./map-geography";
import { ISSUE_TYPES } from "./issue-presentation";
import { meterFeatures } from "./meter-features";
import { issueColor, manualReportFilter } from "./issue-map-style";
import { animateIssuePulse } from "./issue-pulse";
import { ISSUE_STATES } from "./issue-presentation";
import { stationFeatures } from "./station-features";
import { addStationImages, ASSET_MARKERS } from "./station-icons";

interface Props extends GeographySelectionProps {
  data: MapData;
  region: Region;
  resolved: boolean;
  layers: { assets: boolean; issues: boolean; outages: boolean };
  onCreate: (
    point: Pick<CreateIssue, "coordinates" | "regionId" | "segmentId"> & {
      assetId?: string;
    },
  ) => void;
  onIssue: (id: string) => void;
  selectedIssue?: string;
  station?: Asset;
  onStation: (station?: Asset) => void;
}
const empty = { type: "FeatureCollection" as const, features: [] };
const issueFilter = (resolved: boolean): maplibregl.ExpressionSpecification =>
  resolved ? ["has", "status"] : ["!=", ["get", "status"], "RESOLVED"];
function update(map: LibreMap, props: Props) {
  const selected = props.areas.find((a) => a.id === props.selectedId);
  (map.getSource("assets") as GeoJSONSource)?.setData(props.data.assets);
  (map.getSource("stations") as GeoJSONSource)?.setData(
    stationFeatures(props.data.assets),
  );
  (map.getSource("issues") as GeoJSONSource)?.setData(props.data.issues);
  (map.getSource("outages") as GeoJSONSource)?.setData(props.data.outages);
  (map.getSource("areas") as GeoJSONSource)?.setData(
    areaFeatures(props.areas, props.selectedId),
  );
  (map.getSource("meters") as GeoJSONSource)?.setData(
    meterFeatures(
      selected?.parentId
        ? (props.data.meters ?? []).filter(
            (meter) => meter.segmentId === selected.id,
          )
        : [],
      props.station?.id,
    ),
  );
  map.setPaintProperty(
    "meter-points",
    "icon-opacity",
    props.station ? ["case", ["get", "highlighted"], 1, 0.45] : 1,
  );
  const parentId = selected?.parentId ?? selected?.id;
  for (const kind of ["region", "subregion"]) {
    for (const suffix of ["fill", "line"]) {
      const id = `${kind}-${suffix}`;
      const isRegion = kind === "region";
      map.setLayerZoomRange(id, isRegion || parentId ? 0 : 7.3, 24);
      map.setFilter(
        id,
        isRegion
          ? ["==", ["get", "parentId"], ""]
          : parentId
            ? ["==", ["get", "parentId"], parentId]
            : ["!=", ["get", "parentId"], ""],
      );
    }
  }
  for (const area of props.areas)
    map.setFeatureState(
      { source: "areas", id: area.id },
      { selected: area.id === props.selectedId },
    );
  for (const [key, ids] of Object.entries({
    assets: ["station-points", "asset-lines"],
    issues: ["issue-points", "issue-icons", "issue-selected", "issue-pulse"],
    outages: ["outage-points"],
  })) {
    for (const id of ids)
      map.setLayoutProperty(
        id,
        "visibility",
        props.layers[key as keyof Props["layers"]] ? "visible" : "none",
      );
  }
  map.setFilter("issue-points", [
    "any",
    issueFilter(props.resolved),
    ["==", ["get", "id"], props.selectedIssue ?? ""],
  ]);
  map.setFilter("issue-icons", [
    "any",
    issueFilter(props.resolved),
    ["==", ["get", "id"], props.selectedIssue ?? ""],
  ]);
  map.setFilter("issue-selected", [
    "==",
    ["get", "id"],
    props.selectedIssue ?? "",
  ]);
}
export function NetworkMap(props: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<LibreMap | null>(null);
  const latest = useRef(props);
  const previousSelection = useRef<string | undefined>(undefined);
  const previousIssue = useRef<string | undefined>(undefined);
  const previousStation = useRef<string | undefined>(undefined);
  const zoomedMeters = useRef<string | undefined>(undefined);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [context, setContext] = useState<{
    left: number;
    top: number;
    point: [number, number];
  } | null>(null);
  const [hint, setHint] = useState("");
  useEffect(() => {
    latest.current = props;
    if (map.current?.getSource("areas")) {
      update(map.current, props);
      if (
        props.selectedIssue &&
        previousIssue.current !== props.selectedIssue
      ) {
        const issue = props.data.issueList.find(
          (item) => item.id === props.selectedIssue,
        );
        if (issue) {
          previousIssue.current = props.selectedIssue;
          map.current.easeTo({
            center: issue.coordinates,
            zoom: Math.max(map.current.getZoom(), 10),
            duration: 300,
          });
        }
      }
      if (previousSelection.current !== props.selectedId) {
        previousSelection.current = props.selectedId;
        const selected = props.areas.find((a) => a.id === props.selectedId);
        const areas = selected
          ? [selected]
          : props.areas.filter((a) => !a.parentId);
        if (areas.length)
          map.current.fitBounds(areaBounds(areas), {
            padding: 45,
            maxZoom: 11,
            duration: window.matchMedia("(prefers-reduced-motion: reduce)")
              .matches
              ? 0
              : 700,
          });
      }
      if (previousStation.current !== props.station?.id) {
        previousStation.current = props.station?.id;
        zoomedMeters.current = undefined;
      }
      if (
        props.station &&
        props.data.meters &&
        zoomedMeters.current !== props.station.id
      ) {
        zoomedMeters.current = props.station.id;
        const bounds = new maplibregl.LngLatBounds();
        for (const asset of props.data.assets.features)
          if (asset.geometry.type === "Point")
            bounds.extend([
              asset.geometry.coordinates[0],
              asset.geometry.coordinates[1],
            ]);
        for (const meter of props.data.meters) bounds.extend(meter.coordinates);
        map.current.fitBounds(bounds, {
          padding: 80,
          maxZoom: 15,
          duration: window.matchMedia("(prefers-reduced-motion: reduce)")
            .matches
            ? 0
            : 700,
        });
      }
    }
  }, [props]);
  const hasManualReports = props.data.issues.features.some(
    (feature) =>
      feature.properties?.type === "OUTAGE_REPORT" &&
      feature.properties?.status === "OPEN",
  );
  useEffect(() => {
    if (!ready || !props.layers.issues || !hasManualReports) return;
    if (map.current && container.current)
      return animateIssuePulse(map.current, container.current);
  }, [ready, props.layers.issues, hasManualReports]);
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
    let pulseFrame = 0;
    let hovered: string | undefined;
    const hoverFrames = new Map<string, number>();
    const animateHover = (id: string, value: number) => {
      const previous = hoverFrames.get(id);
      if (previous !== undefined) cancelAnimationFrame(previous);
      const target = { source: "areas", id };
      const from = Number(instance.getFeatureState(target).hover ?? 0);
      const start = performance.now();
      const reduced = window.matchMedia(
        "(prefers-reduced-motion: reduce)",
      ).matches;
      const step = (now: number) => {
        const progress = reduced
          ? 1
          : Math.max(0, Math.min((now - start) / 150, 1));
        instance.setFeatureState(target, {
          hover: from + (value - from) * progress,
        });
        if (progress < 1) hoverFrames.set(id, requestAnimationFrame(step));
        else hoverFrames.delete(id);
      };
      step(start);
    };
    const tooltip = new maplibregl.Popup({
      closeButton: false,
      closeOnClick: false,
      offset: 12,
    });
    let tooltipTimeout: number | undefined;
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
    instance.on("error", (event) =>
      setError(
        `Map rendering warning: ${event.error.message}. The issue list remains available.`,
      ),
    );
    instance.on("load", () => {
      setError("");
      setReady(true);
      for (const id of [
        "assets",
        "stations",
        "issues",
        "outages",
        "areas",
        "meters",
      ])
        instance.addSource(id, { type: "geojson", data: empty });
      for (const kind of ["region", "subregion"]) {
        instance.addLayer({
          id: `${kind}-fill`,
          type: "fill",
          source: "areas",
          paint: {
            "fill-color": [
              "case",
              ["get", "highlighted"],
              "#209755",
              "#8c9992",
            ],
            "fill-opacity": [
              "case",
              ["get", "highlighted"],
              0.35,
              [
                "interpolate",
                ["linear"],
                ["number", ["feature-state", "hover"], 0],
                0,
                kind === "region" ? 0.1 : 0.025,
                1,
                0.23,
              ],
            ],
          },
        });
        instance.addLayer({
          id: `${kind}-line`,
          type: "line",
          source: "areas",
          paint: {
            "line-color": [
              "case",
              ["get", "highlighted"],
              "#176747",
              "#9aa59f",
            ],
            "line-width": [
              "case",
              ["boolean", ["feature-state", "selected"], false],
              3.5,
              [
                "interpolate",
                ["linear"],
                ["number", ["feature-state", "hover"], 0],
                0,
                1.4,
                1,
                3,
              ],
            ],
          },
        });
        instance.setPaintProperty(`${kind}-fill`, "fill-opacity-transition", {
          duration: 150,
        });
        instance.setPaintProperty(`${kind}-line`, "line-width-transition", {
          duration: 150,
        });
      }
      instance.addLayer({
        id: "area-pulse",
        type: "line",
        source: "areas",
        filter: ["==", ["get", "parentId"], ""],
        paint: { "line-color": "#4c9a70", "line-width": 6, "line-opacity": 0 },
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
      addStationImages(instance);
      instance.addLayer({
        id: "station-points",
        type: "symbol",
        source: "stations",
        layout: {
          "icon-image": ["concat", "station-", ["get", "type"]],
          "icon-size": [
            "interpolate",
            ["linear"],
            ["zoom"],
            5,
            0.65,
            8,
            1,
            12,
            1.35,
            15,
            1.65,
            18,
            2,
          ],
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
      });
      for (const [id, color] of [
        ["meter", "#2378aa"],
        ["meter-highlighted", "#00a6b2"],
      ]) {
        const meterCanvas = document.createElement("canvas");
        meterCanvas.width = meterCanvas.height = 24;
        const meterContext = meterCanvas.getContext("2d");
        if (meterContext) {
          meterContext.fillStyle = color;
          meterContext.beginPath();
          meterContext.arc(12, 12, 10, 0, Math.PI * 2);
          meterContext.fill();
          meterContext.strokeStyle = "#fff";
          meterContext.lineWidth = 3;
          meterContext.stroke();
          instance.addImage(id, meterContext.getImageData(0, 0, 24, 24), {
            pixelRatio: 2,
          });
        }
      }
      instance.addLayer({
        id: "meter-points",
        type: "symbol",
        source: "meters",
        layout: {
          "icon-image": [
            "case",
            ["get", "highlighted"],
            "meter-highlighted",
            "meter",
          ],
          "icon-size": [
            "interpolate",
            ["linear"],
            ["zoom"],
            5,
            0.15,
            9,
            0.35,
            12,
            0.7,
            15,
            1,
            18,
            1.2,
          ],
          "icon-offset": ["get", "markerOffset"],
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
          "icon-rotation-alignment": "viewport",
        },
      });
      for (const [type, info] of Object.entries(ISSUE_TYPES)) {
        const canvas = document.createElement("canvas");
        canvas.width = canvas.height = 40;
        const ctx = canvas.getContext("2d");
        if (!ctx) continue;
        ctx.fillStyle = "#fff";
        ctx.font = "bold 22px sans-serif";
        ctx.textAlign = "center";
        ctx.textBaseline = "middle";
        ctx.fillText(info.symbol, 20, 21);
        instance.addImage(type, ctx.getImageData(0, 0, 40, 40), {
          pixelRatio: 2,
        });
      }
      instance.addLayer({
        id: "issue-pulse",
        type: "circle",
        source: "issues",
        filter: manualReportFilter,
        paint: {
          "circle-radius": 14,
          "circle-opacity": 0,
          "circle-stroke-width": 2,
          "circle-stroke-color": ISSUE_STATES.OPEN.color,
          "circle-stroke-opacity": 0,
        },
      });
      instance.addLayer({
        id: "issue-selected",
        type: "circle",
        source: "issues",
        paint: {
          "circle-radius": 14,
          "circle-opacity": 0,
          "circle-stroke-color": "#34495e",
          "circle-stroke-width": 2,
        },
      });
      instance.addLayer({
        id: "issue-points",
        type: "circle",
        source: "issues",
        paint: {
          "circle-radius": 9,
          "circle-color": issueColor,
          "circle-stroke-width": 1,
          "circle-stroke-color": "#ffffff",
        },
      });
      for (const property of ["circle-radius", "circle-stroke-opacity"])
        instance.setPaintProperty("issue-pulse", `${property}-transition`, {
          duration: 0,
        });
      instance.setPaintProperty("issue-points", "circle-color-transition", {
        duration: 0,
      });
      instance.addLayer({
        id: "issue-icons",
        type: "symbol",
        source: "issues",
        layout: {
          "icon-image": ["coalesce", ["get", "type"], "OUTAGE_REPORT"],
          "icon-size": 1,
          "icon-allow-overlap": true,
          "icon-ignore-placement": true,
        },
      });
      update(instance, latest.current);
      const selected = latest.current.areas.find(
        (a) => a.id === latest.current.selectedId,
      );
      const initialAreas = selected
        ? [selected]
        : latest.current.areas.filter((a) => !a.parentId);
      if (initialAreas.length)
        instance.fitBounds(areaBounds(initialAreas), {
          padding: 45,
          duration: 0,
        });
      previousSelection.current = latest.current.selectedId;
      if (
        !window.matchMedia("(prefers-reduced-motion: reduce)").matches &&
        !sessionStorage.getItem("region-outline-pulsed")
      ) {
        sessionStorage.setItem("region-outline-pulsed", "1");
        const start = performance.now();
        const pulse = (now: number) => {
          const progress = Math.max(0, Math.min((now - start) / 1400, 1));
          instance.setPaintProperty(
            "area-pulse",
            "line-opacity",
            Math.sin(progress * Math.PI) * 0.35,
          );
          if (progress < 1) pulseFrame = requestAnimationFrame(pulse);
        };
        pulseFrame = requestAnimationFrame(pulse);
      }
    });
    instance.on("mousemove", (event) => {
      if (!instance.getLayer("region-fill")) return;
      window.clearTimeout(tooltipTimeout);
      const hits = instance.queryRenderedFeatures(event.point, {
        layers: [
          "meter-points",
          "issue-points",
          "subregion-fill",
          "region-fill",
          "station-points",
        ],
      });
      const feature =
        hits.find((f) => f.layer.id === "meter-points") ??
        hits.find((f) => f.layer.id === "issue-points") ??
        hits.find((f) => f.layer.id === "station-points") ??
        hits[0];
      const id =
        feature?.layer.source === "areas"
          ? (feature.properties.id as string | undefined)
          : undefined;
      if (hovered !== id) {
        if (hovered) animateHover(hovered, 0);
        hovered = id;
        if (id && feature?.layer.source === "areas") animateHover(id, 1);
      }
      instance.getCanvas().style.cursor = feature ? "pointer" : "";
      if (!feature) {
        tooltip.remove();
        return;
      }
      const content = document.createElement("div");
      content.textContent =
        feature.layer.id === "meter-points"
          ? `${feature.properties.code} · ${feature.properties.clientType} · Last reading: ${feature.properties.lastReading}`
          : feature.layer.id === "issue-points"
            ? (feature.properties.title ??
              ISSUE_TYPES[feature.properties.type as keyof typeof ISSUE_TYPES]
                ?.label ??
              "Issue")
            : feature.layer.id === "station-points"
              ? `${feature.properties.name} · ${ASSET_MARKERS[feature.properties.type as Asset["type"]].label} · Click to highlight linked meters`
              : `${feature.properties.name} · ${feature.properties.meterCount} meters`;
      tooltip.setLngLat(event.lngLat).setDOMContent(content).addTo(instance);
    });
    instance.on("mouseout", () => {
      window.clearTimeout(tooltipTimeout);
      if (hovered) animateHover(hovered, 0);
      hovered = undefined;
      instance.getCanvas().style.cursor = "";
      tooltip.remove();
    });
    instance.on("click", (event) => {
      if (!instance.getLayer("station-points")) return;
      const feature = instance.queryRenderedFeatures(event.point, {
        layers: ["issue-points"],
      })[0];
      if (feature) {
        latest.current.onIssue(String(feature.properties.id));
      } else {
        const asset = instance.queryRenderedFeatures(event.point, {
          layers: ["station-points"],
        })[0];
        if (asset) {
          const station = latest.current.data.assetList.find(
            (item) => item.id === asset.properties.id,
          );
          tooltip.remove();
          window.clearTimeout(tooltipTimeout);
          if (station) {
            latest.current.onStation(station);
            if (
              latest.current.data.meters &&
              !latest.current.data.meters.some(
                (meter) => meter.assetId === station.id,
              )
            ) {
              tooltip
                .setLngLat(event.lngLat)
                .setText("No meters linked")
                .addTo(instance);
              tooltipTimeout = window.setTimeout(() => tooltip.remove(), 2200);
            }
          }
          return;
        }
        const area = instance.queryRenderedFeatures(event.point, {
          layers: ["subregion-fill", "region-fill"],
        })[0];
        if (area) {
          const selected = latest.current.areas.find(
            (a) => a.id === area.properties.id,
          );
          if (selected) latest.current.onSelect(selected);
          tooltip.remove();
          window.clearTimeout(tooltipTimeout);
          return;
        }
      }
    });
    instance.on("contextmenu", (event) => {
      event.preventDefault();
      tooltip.remove();
      window.clearTimeout(tooltipTimeout);
      setContext({
        left: event.originalEvent.clientX,
        top: event.originalEvent.clientY,
        point: [event.lngLat.lng, event.lngLat.lat],
      });
    });
    const resize = new ResizeObserver(() => instance.resize());
    resize.observe(container.current);
    return () => {
      cancelAnimationFrame(pulseFrame);
      for (const frame of hoverFrames.values()) cancelAnimationFrame(frame);
      tooltip.remove();
      window.clearTimeout(tooltipTimeout);
      resize.disconnect();
      instance.remove();
      map.current = null;
    };
  }, []);
  const zoomRegion = () => {
    const selected = props.areas.find((a) => a.id === props.selectedId);
    const areas = selected
      ? [selected]
      : props.areas.filter((a) => !a.parentId);
    if (areas.length)
      map.current?.fitBounds(areaBounds(areas), {
        padding: 50,
        duration: window.matchMedia("(prefers-reduced-motion: reduce)").matches
          ? 0
          : 700,
      });
  };
  return (
    <Box sx={{ position: "relative" }}>
      <Menu
        open={!!context}
        onClose={() => setContext(null)}
        anchorReference="anchorPosition"
        anchorPosition={context ?? undefined}
      >
        <MenuItem
          onClick={() => {
            if (!context) return;
            const point = context.point;
            setContext(null);
            const area = reportArea(props.areas, props.selectedId, point);
            if (!area) {
              setHint("Choose a point inside the current scope.");
              return;
            }
            const nearest = props.data.assetList
              .filter((a) => a.region === area.region)
              .sort(
                (a, b) =>
                  Math.hypot(
                    a.coordinates[0] - point[0],
                    a.coordinates[1] - point[1],
                  ) -
                  Math.hypot(
                    b.coordinates[0] - point[0],
                    b.coordinates[1] - point[1],
                  ),
              )[0];
            if (!nearest) {
              setHint(
                "No network asset is available here. Wait for the map to load.",
              );
              return;
            }
            props.onCreate({
              coordinates: point,
              regionId: area.parentId!,
              segmentId: area.id,
              assetId: nearest.id,
            });
          }}
        >
          Report outage here
        </MenuItem>
      </Menu>
      <Snackbar
        open={!!hint}
        message={hint}
        autoHideDuration={3500}
        onClose={() => setHint("")}
      />
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
        Zoom to selection
      </Button>
    </Box>
  );
}
