import { useEffect, useRef, useState } from "react";
import { Alert, Box } from "@mui/material";
import maplibregl, {
  type GeoJSONSource,
  type Map as LibreMap,
} from "maplibre-gl";
import "maplibre-gl/dist/maplibre-gl.css";
import {
  hotspotCollection,
  hotspotLayers,
  visibleHotspotLayers,
  type HotspotMode,
} from "../charts/hotspots";
import { REGION_INFO, type OutageHotspot, type Region } from "../data/models";

interface Props {
  rows: OutageHotspot[];
  region: Region;
  mode: HotspotMode;
}
function fitRegion(instance: LibreMap, region: Region) {
  const [west, south, east, north] = REGION_INFO[region].bbox;
  instance.fitBounds(
    [
      [west, south],
      [east, north],
    ],
    { padding: 35, duration: 0 },
  );
}
function update(instance: LibreMap, props: Props) {
  const collection = hotspotCollection(props.rows);
  for (const source of ["hotspots", "hotspots-clustered"])
    (instance.getSource(source) as GeoJSONSource).setData(collection);
  const visible = visibleHotspotLayers(props.mode);
  for (const layer of hotspotLayers)
    instance.setLayoutProperty(
      layer.id,
      "visibility",
      visible.includes(layer.id) ? "visible" : "none",
    );
}
export function HotspotMap(props: Props) {
  const container = useRef<HTMLDivElement>(null);
  const map = useRef<LibreMap | null>(null);
  const latest = useRef(props);
  const lastRegion = useRef(props.region);
  const [error, setError] = useState("");
  useEffect(() => {
    latest.current = props;
    if (map.current?.getSource("hotspots")) update(map.current, props);
    if (lastRegion.current !== props.region) {
      lastRegion.current = props.region;
      if (map.current) fitRegion(map.current, props.region);
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
        "Map tiles could not load. The hotspot table remains available below.",
      ),
    );
    instance.on("load", () => {
      const data = hotspotCollection(latest.current.rows);
      instance.addSource("hotspots", { type: "geojson", data });
      instance.addSource("hotspots-clustered", {
        type: "geojson",
        data,
        cluster: true,
        clusterRadius: 45,
        clusterMaxZoom: 12,
        clusterProperties: { outageCount: ["+", ["get", "outageCount"]] },
      });
      for (const layer of hotspotLayers) instance.addLayer(layer);
      update(instance, latest.current);
      fitRegion(instance, latest.current.region);
    });
    instance.on("click", (event) => {
      if (!instance.getLayer("hotspot-points")) return;
      const layers =
        latest.current.mode === "heat"
          ? ["hotspot-heat-points"]
          : ["hotspot-clusters", "hotspot-points"];
      const feature = instance.queryRenderedFeatures(event.point, {
        layers,
      })[0];
      if (!feature || feature.geometry.type !== "Point") return;
      const coordinates = feature.geometry.coordinates as [number, number];
      if (feature.properties.cluster_id !== undefined) {
        void (instance.getSource("hotspots-clustered") as GeoJSONSource)
          .getClusterExpansionZoom(Number(feature.properties.cluster_id))
          .then((zoom) => instance.easeTo({ center: coordinates, zoom }))
          .catch(() =>
            setError(
              "Could not expand this cluster. Zoom in using the map controls.",
            ),
          );
        return;
      }
      const content = document.createElement("div");
      content.textContent = `${feature.properties.assetName} · ${feature.properties.outageCount} outages · ${feature.properties.durationMinutes} total minutes`;
      new maplibregl.Popup()
        .setLngLat(coordinates)
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
  return (
    <Box>
      <Box
        ref={container}
        aria-label={`Outage hotspots in ${REGION_INFO[props.region].name}`}
        sx={{ height: 380, width: "100%", bgcolor: "#e9eee5", borderRadius: 2 }}
      />
      {error && (
        <Alert severity="warning" sx={{ mt: 1 }}>
          {error}
        </Alert>
      )}
    </Box>
  );
}
