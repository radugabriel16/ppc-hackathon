// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { Asset, GeographicArea, MapData } from "../data/models";
import type { LayerSpecification } from "maplibre-gl";
import { NetworkMap } from "./NetworkMap";
import { pointAssetFixtures } from "./test-fixtures/point-assets";
import { geographicAreas } from "../data/api-mapping";
import { mockRegions } from "../mocks/fixtures";

const fake = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => void>(),
  sources: new Map<string, { setData: ReturnType<typeof vi.fn> }>(),
  layers: new Map<string, LayerSpecification>(),
  rendered: [] as { properties: { id: string } }[],
  renderedAssets: [] as { properties: { id: string; type: string } }[],
  renderedIssues: [] as { properties: { id: string } }[],
  onCreate: vi.fn(),
  setLayerZoomRange: vi.fn(),
  setFilter: vi.fn(),
  fitBounds: vi.fn(),
  easeTo: vi.fn(),
  setPaintProperty: vi.fn(),
  tooltipText: vi.fn(),
  tooltipRemove: vi.fn(),
}));
vi.mock("maplibre-gl", () => ({
  default: {
    Map: class {
      on(event: string, handler: (...args: unknown[]) => void) {
        fake.handlers.set(event, handler);
      }
      addControl() {}
      addSource(id: string) {
        fake.sources.set(id, { setData: vi.fn() });
      }
      getSource(id: string) {
        return fake.sources.get(id);
      }
      addLayer(layer: LayerSpecification) {
        fake.layers.set(layer.id, layer);
      }
      getLayer(id: string) {
        return fake.layers.get(id);
      }
      setLayerZoomRange(...args: unknown[]) {
        fake.setLayerZoomRange(...args);
      }
      setFilter(...args: unknown[]) {
        fake.setFilter(...args);
      }
      setPaintProperty(...args: unknown[]) {
        fake.setPaintProperty(...args);
      }
      setLayoutProperty() {}
      removeFeatureState() {}
      setFeatureState() {}
      getFeatureState() {
        return {};
      }
      fitBounds(...args: unknown[]) {
        fake.fitBounds(...args);
      }
      easeTo(...args: unknown[]) {
        fake.easeTo(...args);
      }
      getZoom() {
        return 8;
      }
      isStyleLoaded() {
        return true;
      }
      queryRenderedFeatures(_point: unknown, options: { layers: string[] }) {
        if (options.layers[0] === "issue-points") return fake.renderedIssues;
        if (options.layers[0] === "station-points") return fake.renderedAssets;
        return fake.rendered;
      }
      remove() {}
      resize() {}
      addImage() {}
    },
    Popup: class {
      remove() {
        fake.tooltipRemove();
      }
      setLngLat() {
        return this;
      }
      setText(text: string) {
        fake.tooltipText(text);
        return this;
      }
      addTo() {
        return this;
      }
    },
    NavigationControl: class {},
    AttributionControl: class {},
    LngLatBounds: class {
      extend() {
        return this;
      }
    },
  },
}));
beforeEach(() => {
  fake.handlers.clear();
  fake.sources.clear();
  fake.layers.clear();
  fake.rendered = [];
  fake.renderedAssets = [];
  fake.renderedIssues = [];
  fake.onCreate.mockReset();
  fake.setLayerZoomRange.mockReset();
  fake.setFilter.mockReset();
  fake.fitBounds.mockReset();
  fake.easeTo.mockReset();
  fake.setPaintProperty.mockReset();
  fake.tooltipText.mockReset();
  fake.tooltipRemove.mockReset();
  vi.stubGlobal("matchMedia", () => ({
    matches: true,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  vi.stubGlobal(
    "IntersectionObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.stubGlobal(
    "ResizeObserver",
    class {
      observe() {}
      disconnect() {}
    },
  );
  vi.spyOn(HTMLCanvasElement.prototype, "getContext").mockReturnValue(null);
});
afterEach(() => {
  cleanup();
  sessionStorage.clear();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});
const region: GeographicArea = {
  id: "region",
  code: "BANAT",
  name: "Banat",
  region: "BANAT",
  parentId: null,
  meterCount: 8,
  geometry: {
    type: "MultiPolygon",
    coordinates: [
      [
        [
          [20, 44],
          [22, 44],
          [22, 46],
          [20, 46],
          [20, 44],
        ],
      ],
    ],
  },
};
const segment = { ...region, id: "segment", parentId: region.id };
const empty = { type: "FeatureCollection" as const, features: [] };
const data: MapData = {
  assets: empty,
  issues: {
    type: "FeatureCollection",
    features: [
      {
        type: "Feature",
        geometry: { type: "Point", coordinates: [20.123456, 45.123456] },
        properties: { id: "issue", type: "ML_FORECAST", status: "OPEN" },
      },
    ],
  },
  outages: empty,
  assetList: [
    {
      id: "asset",
      name: "Asset",
      type: "SUBSTATION",
      region: "BANAT",
      coordinates: [21, 45],
    },
  ],
  issueList: [],
  meters: Array.from({ length: 8 }, (_, i) => ({
    id: `m-${i}`,
    assetId: "asset",
    code: `M-${i}`,
    segmentId: segment.id,
    coordinates: [20.5 + i / 100, 45],
    clientType: "RESIDENTIAL",
    lastReading: { kWh: 1.5, timestamp: "2026-11-14T20:00:00Z" },
  })),
};
function show() {
  const onSelect = vi.fn();
  render(
    <NetworkMap
      data={data}
      region="BANAT"
      areas={[region, segment]}
      selectedId={segment.id}
      onSelect={onSelect}
      resolved={false}
      layers={{ assets: true, issues: true, outages: true }}
      onCreate={fake.onCreate}
      onIssue={vi.fn()}
      onStation={vi.fn()}
    />,
  );
  act(() => fake.handlers.get("load")!());
  return onSelect;
}
function context(point: [number, number]) {
  act(() =>
    fake.handlers.get("contextmenu")!({
      preventDefault: vi.fn(),
      originalEvent: { clientX: 100, clientY: 100 },
      lngLat: { lng: point[0], lat: point[1] },
    }),
  );
  fireEvent.click(screen.getByRole("menuitem", { name: "Report outage here" }));
}
it("uses the context menu only inside scope and forwards the exact clicked point, not the nearest asset coordinate", () => {
  const onSelect = show();
  act(() =>
    fake.handlers.get("click")!({
      point: {},
      lngLat: { lng: 20.7, lat: 45.2 },
    }),
  );
  expect(fake.onCreate).not.toHaveBeenCalled();
  fake.rendered = [{ properties: { id: region.id } }];
  act(() => fake.handlers.get("click")!({ point: {} }));
  expect(onSelect).toHaveBeenCalledWith(region);
  context([19, 43]);
  expect(
    screen.getByText("Choose a point inside the current scope."),
  ).toBeTruthy();
  expect(fake.onCreate).not.toHaveBeenCalled();
  context([20.123456, 45.123456]);
  expect(fake.onCreate).toHaveBeenCalledExactlyOnceWith({
    coordinates: [20.123456, 45.123456],
    regionId: "region",
    segmentId: "segment",
    assetId: "asset",
  });
});
it("renders segment meters without a station selection and keeps issue coordinates and icons unchanged", () => {
  show();
  const meters = fake.sources.get("meters")!.setData.mock.calls.at(-1)![0];
  expect(meters.features).toHaveLength(8);
  expect(fake.sources.get("issues")!.setData).toHaveBeenLastCalledWith(
    data.issues,
  );
  expect(fake.layers.get("issue-icons")!.layout).not.toHaveProperty(
    "icon-offset",
  );
  expect(fake.layers.get("issue-icons")!.layout).toHaveProperty("icon-image");
});

it("highlights only linked meters while retaining every meter and station on selection changes", () => {
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  const station = data.assetList[0];
  const other = {
    ...station,
    id: "other",
    type: "TRANSFORMER" as const,
    coordinates: [21.2, 45] as [number, number],
  };
  const onStation = vi.fn();
  const props = {
    data: {
      ...data,
      assets: assetFeatures([station, other]),
      assetList: [station, other],
      meters: data.meters!.map((meter, index) =>
        index < 2 ? { ...meter, assetId: other.id } : meter,
      ),
    },
    region: "BANAT" as const,
    areas: [region, segment],
    selectedId: segment.id,
    onSelect: vi.fn(),
    resolved: false,
    layers: { assets: true, issues: true, outages: true },
    onCreate: fake.onCreate,
    onIssue: vi.fn(),
    onStation,
  };
  const view = render(<NetworkMap {...props} />);
  act(() => fake.handlers.get("load")!());
  const stations = fake.sources.get("stations")!.setData.mock.calls.at(-1)![0];
  fake.renderedAssets = [
    { properties: { id: station.id, type: "SUBSTATION" } },
  ];
  act(() => fake.handlers.get("click")!({ point: {} }));
  expect(onStation).toHaveBeenCalledWith(station);
  view.rerender(<NetworkMap {...props} station={station} />);
  let meters = fake.sources.get("meters")!.setData.mock.calls.at(-1)![0];
  expect(meters.features).toHaveLength(8);
  expect(meters.features[0].properties).toMatchObject({
    code: "M-0",
    clientType: "RESIDENTIAL",
    lastReading: expect.stringContaining("1.5 kWh"),
    highlighted: false,
  });
  expect(
    meters.features.filter(
      (feature: { properties: { highlighted: boolean } }) =>
        feature.properties.highlighted,
    ),
  ).toHaveLength(6);
  expect(fake.sources.get("stations")!.setData).toHaveBeenLastCalledWith(
    stations,
  );
  expect(fake.fitBounds).toHaveBeenLastCalledWith(expect.anything(), {
    padding: 80,
    maxZoom: 15,
    duration: 700,
  });
  expect(fake.layers.get("meter-points")!.layout).toHaveProperty("icon-size", [
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
  ]);
  view.rerender(<NetworkMap {...props} station={other} />);
  meters = fake.sources.get("meters")!.setData.mock.calls.at(-1)![0];
  expect(meters.features).toHaveLength(8);
  expect(
    meters.features.filter(
      (feature: { properties: { highlighted: boolean } }) =>
        feature.properties.highlighted,
    ),
  ).toHaveLength(2);
  expect(fake.sources.get("stations")!.setData).toHaveBeenLastCalledWith(
    stations,
  );
  view.rerender(<NetworkMap {...props} />);
  expect(
    fake.sources.get("meters")!.setData.mock.calls.at(-1)![0].features,
  ).toHaveLength(8);
  expect(fake.sources.get("stations")!.setData).toHaveBeenLastCalledWith(
    stations,
  );
});

function assetFeatures(assets: Asset[]): MapData["assets"] {
  return {
    type: "FeatureCollection",
    features: assets.map((asset) => ({
      type: "Feature",
      id: asset.id,
      geometry: { type: "Point", coordinates: asset.coordinates },
      properties: { id: asset.id, name: asset.name, type: asset.type },
    })),
  };
}

const fixtureAreas = geographicAreas(mockRegions);
it.each(fixtureAreas.filter((area) => area.parentId))(
  "renders every point asset in $name in a separate station layer before and after clicks",
  (area) => {
    const assets = pointAssetFixtures.filter(
      (asset) => asset.segmentId === area.id,
    );
    expect(assets.length).toBeGreaterThan(0);
    const scopedData: MapData = {
      ...data,
      assets: assetFeatures(assets),
      assetList: assets,
      meters: data.meters!.map((meter, index) => ({
        ...meter,
        segmentId: area.id,
        assetId: assets[index % assets.length].id,
      })),
    };
    const onStation = vi.fn();
    const props = {
      data: scopedData,
      region: area.region,
      areas: fixtureAreas,
      selectedId: area.id,
      onSelect: vi.fn(),
      resolved: false,
      layers: { assets: true, issues: true, outages: true },
      onCreate: fake.onCreate,
      onIssue: vi.fn(),
      onStation,
    };
    const view = render(<NetworkMap {...props} />);
    act(() => fake.handlers.get("load")!());
    const stations = fake.sources
      .get("stations")!
      .setData.mock.calls.at(-1)![0];
    expect(
      stations.features.map((feature: { id: string }) => feature.id),
    ).toEqual(assets.map((asset) => asset.id));
    expect(
      stations.features.map(
        (feature: { properties: { type: string } }) => feature.properties.type,
      ),
    ).toEqual(assets.map((asset) => asset.type));
    expect(
      stations.features.every(
        (feature: { properties: { kind: string } }) =>
          feature.properties.kind === "STATION",
      ),
    ).toBe(true);
    expect(fake.layers.get("station-points")).toMatchObject({
      source: "stations",
    });
    expect(fake.layers.get("meter-points")).toMatchObject({ source: "meters" });
    expect([...fake.layers.keys()].indexOf("station-points")).toBeLessThan(
      [...fake.layers.keys()].indexOf("issue-points"),
    );
    expect(
      fake.sources.get("meters")!.setData.mock.calls.at(-1)![0].features,
    ).toHaveLength(8);
    for (const asset of assets) {
      fake.renderedAssets = [
        { properties: { id: asset.id, type: asset.type } },
      ];
      act(() => fake.handlers.get("click")!({ point: {} }));
      expect(onStation).toHaveBeenLastCalledWith(asset);
      view.rerender(<NetworkMap {...props} station={asset} />);
      expect(fake.sources.get("stations")!.setData).toHaveBeenLastCalledWith(
        stations,
      );
      expect(
        fake.sources.get("meters")!.setData.mock.calls.at(-1)![0].features,
      ).toHaveLength(8);
    }
    expect(
      fake.setFilter.mock.calls.some(([id]) => id === "station-points"),
    ).toBe(false);
  },
);

it("keeps point assets at country and region scopes while hiding meters", () => {
  const props = {
    data: { ...data, assets: assetFeatures(data.assetList) },
    region: "BANAT" as const,
    areas: [region, segment],
    onSelect: vi.fn(),
    onStation: vi.fn(),
    onIssue: vi.fn(),
    resolved: false,
    layers: { assets: true, issues: true, outages: true },
    onCreate: fake.onCreate,
  };
  const view = render(<NetworkMap {...props} />);
  act(() => fake.handlers.get("load")!());
  expect(
    fake.sources.get("stations")!.setData.mock.calls.at(-1)![0].features,
  ).toHaveLength(1);
  expect(
    fake.sources.get("meters")!.setData.mock.calls.at(-1)![0].features,
  ).toHaveLength(0);
  view.rerender(<NetworkMap {...props} selectedId={region.id} />);
  expect(
    fake.sources.get("stations")!.setData.mock.calls.at(-1)![0].features,
  ).toHaveLength(1);
  expect(
    fake.sources.get("meters")!.setData.mock.calls.at(-1)![0].features,
  ).toHaveLength(0);
});

it("gives overlapping issues the click while the station remains available independently", () => {
  const onIssue = vi.fn();
  const onStation = vi.fn();
  render(
    <NetworkMap
      data={{ ...data, assets: assetFeatures(data.assetList) }}
      region="BANAT"
      areas={[region, segment]}
      selectedId={segment.id}
      onSelect={vi.fn()}
      onStation={onStation}
      onIssue={onIssue}
      resolved={false}
      layers={{ assets: true, issues: true, outages: true }}
      onCreate={fake.onCreate}
    />,
  );
  act(() => fake.handlers.get("load")!());
  fake.renderedIssues = [{ properties: { id: "issue" } }];
  fake.renderedAssets = [{ properties: { id: "asset", type: "SUBSTATION" } }];
  act(() => fake.handlers.get("click")!({ point: {} }));
  expect(onIssue).toHaveBeenCalledWith("issue");
  expect(onStation).not.toHaveBeenCalled();
  fake.renderedIssues = [];
  act(() => fake.handlers.get("click")!({ point: {} }));
  expect(onStation).toHaveBeenCalledWith(data.assetList[0]);
});

it("shows a short tooltip for an asset with no linked meters without hiding assets", () => {
  vi.useFakeTimers();
  const asset = {
    ...data.assetList[0],
    id: "unlinked",
    type: "LINE_SEGMENT" as const,
  };
  render(
    <NetworkMap
      data={{ ...data, assets: assetFeatures([asset]), assetList: [asset] }}
      region="BANAT"
      areas={[region, segment]}
      selectedId={segment.id}
      onSelect={vi.fn()}
      onStation={vi.fn()}
      onIssue={vi.fn()}
      resolved={false}
      layers={{ assets: true, issues: true, outages: true }}
      onCreate={fake.onCreate}
    />,
  );
  act(() => fake.handlers.get("load")!());
  fake.renderedAssets = [{ properties: { id: asset.id, type: asset.type } }];
  act(() => fake.handlers.get("click")!({ point: {}, lngLat: {} }));
  expect(fake.tooltipText).toHaveBeenCalledWith("No meters linked");
  const removes = fake.tooltipRemove.mock.calls.length;
  act(() => vi.advanceTimersByTime(2200));
  expect(fake.tooltipRemove).toHaveBeenCalledTimes(removes + 1);
  expect(
    fake.sources.get("stations")!.setData.mock.calls.at(-1)![0].features,
  ).toHaveLength(1);
});

it("waits for its own sources before applying props when the base style is already ready", () => {
  const props = {
    data,
    region: "BANAT" as const,
    areas: [region, segment],
    selectedId: segment.id,
    onSelect: vi.fn(),
    resolved: false,
    layers: { assets: true, issues: true, outages: true },
    onCreate: fake.onCreate,
    onIssue: vi.fn(),
    onStation: vi.fn(),
  };
  const view = render(<NetworkMap {...props} />);
  view.rerender(<NetworkMap {...props} data={{ ...data }} />);
  expect(fake.setLayerZoomRange).not.toHaveBeenCalled();
  act(() => fake.handlers.get("load")!());
  expect(fake.setLayerZoomRange).toHaveBeenCalled();
});

it("stops the shared animation when the last open manual report is taken and never starts it for other types", () => {
  sessionStorage.setItem("region-outline-pulsed", "1");
  const frames = vi.fn(() => 99);
  const cancel = vi.fn();
  vi.stubGlobal("requestAnimationFrame", frames);
  vi.stubGlobal("cancelAnimationFrame", cancel);
  vi.stubGlobal("matchMedia", () => ({
    matches: false,
    addEventListener: vi.fn(),
    removeEventListener: vi.fn(),
  }));
  const manualData: MapData = {
    ...data,
    issues: {
      ...data.issues,
      features: [
        {
          ...data.issues.features[0],
          properties: { id: "manual", type: "OUTAGE_REPORT", status: "OPEN" },
        },
      ],
    },
  };
  const props = {
    data: manualData,
    region: "BANAT" as const,
    areas: [region, segment],
    onSelect: vi.fn(),
    resolved: false,
    layers: { assets: true, issues: true, outages: true },
    onCreate: fake.onCreate,
    onIssue: vi.fn(),
    onStation: vi.fn(),
  };
  const view = render(<NetworkMap {...props} />);
  act(() => fake.handlers.get("load")!());
  expect(frames).toHaveBeenCalledOnce();
  view.rerender(
    <NetworkMap
      {...props}
      data={{
        ...manualData,
        issues: {
          ...manualData.issues,
          features: [
            {
              ...manualData.issues.features[0],
              properties: {
                id: "manual",
                type: "OUTAGE_REPORT",
                status: "IN_PROGRESS",
              },
            },
          ],
        },
      }}
    />,
  );
  expect(cancel).toHaveBeenCalledWith(99);
  expect(fake.setPaintProperty).toHaveBeenCalledWith(
    "issue-pulse",
    "circle-stroke-opacity",
    0,
  );
  view.rerender(<NetworkMap {...props} data={data} />);
  expect(frames).toHaveBeenCalledOnce();
});
