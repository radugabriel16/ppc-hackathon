import { useEffect, useRef, useState } from "react";
import { Alert, Box, Button, Menu, MenuItem, Snackbar } from "@mui/material";
import maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as LibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { CreateIssue, MapData, Region } from "../data/models";
import type { GeographySelectionProps } from "./GeographyExplorer";
import { areaBounds, areaFeatures, reportArea } from "./map-geography";
import { ISSUE_TYPES } from "./issue-presentation";
import { meterFeatures } from "./meter-features";

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
}
const empty = { type: "FeatureCollection" as const, features: [] };
const issueFilter = (resolved: boolean): maplibregl.ExpressionSpecification =>
  resolved ? ["has", "status"] : ["!=", ["get", "status"], "RESOLVED"];
function update(map: LibreMap, props: Props) {
  (map.getSource("assets") as GeoJSONSource)?.setData(props.data.assets);
  (map.getSource("issues") as GeoJSONSource)?.setData(props.data.issues);
  (map.getSource("outages") as GeoJSONSource)?.setData(props.data.outages);
  (map.getSource("areas") as GeoJSONSource)?.setData(
    areaFeatures(props.areas, props.selectedId),
  );
  (map.getSource("meters") as GeoJSONSource)?.setData(
    meterFeatures(props.data.meters ?? []),
  );
  const selected = props.areas.find((a) => a.id === props.selectedId);
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
    assets: ["asset-points", "asset-lines"],
    issues: ["issue-points", "issue-selected"],
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
    }
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
      for (const id of ["assets", "issues", "outages", "areas", "meters"])
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
      const meterCanvas = document.createElement("canvas");
      meterCanvas.width = meterCanvas.height = 24;
      const meterContext = meterCanvas.getContext("2d");
      if (meterContext) {
        meterContext.fillStyle = "#2378aa";
        meterContext.beginPath();
        meterContext.arc(12, 12, 10, 0, Math.PI * 2);
        meterContext.fill();
        meterContext.strokeStyle = "#fff";
        meterContext.lineWidth = 3;
        meterContext.stroke();
        instance.addImage("meter", meterContext.getImageData(0, 0, 24, 24), {
          pixelRatio: 2,
        });
      }
      instance.addLayer({
        id: "meter-points",
        type: "symbol",
        source: "meters",
        layout: {
          "icon-image": "meter",
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
        ctx.fillStyle = info.color;
        ctx.beginPath();
        ctx.arc(20, 20, 18, 0, Math.PI * 2);
        ctx.fill();
        ctx.strokeStyle = "#fff";
        ctx.lineWidth = 2;
        ctx.stroke();
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
        id: "issue-selected",
        type: "circle",
        source: "issues",
        paint: {
          "circle-radius": 17,
          "circle-color": "#f1cf41",
          "circle-opacity": 0.6,
          "circle-stroke-color": "#493e05",
          "circle-stroke-width": 2,
        },
      });
      instance.addLayer({
        id: "issue-points",
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
      const hits = instance.queryRenderedFeatures(event.point, {
        layers: [
          "meter-points",
          "issue-points",
          "subregion-fill",
          "region-fill",
        ],
      });
      const feature =
        hits.find((f) => f.layer.id === "meter-points") ?? hits[0];
      const id = feature?.properties.id as string | undefined;
      if (hovered !== id) {
        if (hovered) animateHover(hovered, 0);
        hovered = id;
        if (id) animateHover(id, 1);
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
            : `${feature.properties.name} · ${feature.properties.meterCount} meters`;
      tooltip.setLngLat(event.lngLat).setDOMContent(content).addTo(instance);
    });
    instance.on("mouseout", () => {
      if (hovered) animateHover(hovered, 0);
      hovered = undefined;
      instance.getCanvas().style.cursor = "";
      tooltip.remove();
    });
    instance.on("click", (event) => {
      if (!instance.getLayer("asset-points")) return;
      const feature = instance.queryRenderedFeatures(event.point, {
        layers: ["issue-points"],
      })[0];
      if (feature) {
        latest.current.onIssue(String(feature.properties.id));
      } else {
        const area = instance.queryRenderedFeatures(event.point, {
          layers: ["subregion-fill", "region-fill"],
        })[0];
        if (area) {
          const selected = latest.current.areas.find(
            (a) => a.id === area.properties.id,
          );
          if (selected) latest.current.onSelect(selected);
          tooltip.remove();
          return;
        }
      }
    });
    instance.on("contextmenu", (event) => {
      event.preventDefault();
      tooltip.remove();
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
