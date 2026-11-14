import { useEffect, useRef, useState } from "react";
import { Alert, Box, Button } from "@mui/material";
import maplibregl from "maplibre-gl";
import type { GeoJSONSource, Map as LibreMap } from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import type { Asset, MapData, Region } from "../data/models";
import type { GeographySelectionProps } from "./GeographyExplorer";
import { areaBounds, areaFeatures } from "./map-geography";

interface Props extends GeographySelectionProps {
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
  (map.getSource("areas") as GeoJSONSource)?.setData(areaFeatures(props.areas));
  const selected = props.areas.find((a) => a.id === props.selectedId);
  const parentId = selected?.parentId ?? selected?.id;
  for (const kind of ["region", "subregion"]) {
    for (const suffix of ["fill", "line"]) {
      const id = `${kind}-${suffix}`;
      const isRegion = kind === "region";
      map.setLayerZoomRange(
        id,
        isRegion || parentId ? 0 : 7.3,
        isRegion && !parentId ? 7.3 : 24,
      );
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
  map.removeFeatureState({ source: "areas" }, "selected");
  if (selected)
    map.setFeatureState(
      { source: "areas", id: selected.id },
      { selected: true },
    );
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
  const previousSelection = useRef<string | undefined>(undefined);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  useEffect(() => {
    latest.current = props;
    if (map.current?.isStyleLoaded()) {
      update(map.current, props);
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
        const progress = reduced ? 1 : Math.min((now - start) / 150, 1);
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
    instance.on("error", () =>
      setError(
        "Map tiles could not load. Check your connection; the issue list remains available.",
      ),
    );
    instance.on("load", () => {
      setError("");
      setReady(true);
      for (const id of ["assets", "issues", "outages", "areas"])
        instance.addSource(id, { type: "geojson", data: empty });
      for (const kind of ["region", "subregion"]) {
        instance.addLayer({
          id: `${kind}-fill`,
          type: "fill",
          source: "areas",
          paint: {
            "fill-color": "#176747",
            "fill-opacity": [
              "case",
              ["boolean", ["feature-state", "selected"], false],
              0.3,
              [
                "interpolate",
                ["linear"],
                ["number", ["feature-state", "hover"], 0],
                0,
                kind === "region" ? 0.1 : 0.07,
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
            "line-color": "#176747",
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
          const progress = Math.min((now - start) / 1400, 1);
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
      const feature = instance.queryRenderedFeatures(event.point, {
        layers: ["subregion-fill", "region-fill"],
      })[0];
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
      content.textContent = `${feature.properties.name} · ${feature.properties.meterCount} meters`;
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
