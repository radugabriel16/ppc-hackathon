// @vitest-environment jsdom
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { GeographicArea, MapData } from "../data/models";
import { NetworkMap } from "./NetworkMap";

const fake = vi.hoisted(() => ({
  handlers: new Map<string, (...args: unknown[]) => void>(),
  sources: new Map<string, { setData: ReturnType<typeof vi.fn> }>(),
  layers: new Map<string, { layout?: Record<string, unknown> }>(),
  rendered: [] as { properties: { id: string } }[],
  onCreate: vi.fn(),
  setLayerZoomRange: vi.fn(),
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
      addLayer(layer: { id: string; layout?: Record<string, unknown> }) {
        fake.layers.set(layer.id, layer);
      }
      getLayer(id: string) {
        return fake.layers.get(id);
      }
      setLayerZoomRange(...args: unknown[]) {
        fake.setLayerZoomRange(...args);
      }
      setFilter() {}
      setPaintProperty() {}
      setLayoutProperty() {}
      removeFeatureState() {}
      setFeatureState() {}
      getFeatureState() {
        return {};
      }
      fitBounds() {}
      isStyleLoaded() {
        return true;
      }
      queryRenderedFeatures(_point: unknown, options: { layers: string[] }) {
        return options.layers.length === 1 &&
          options.layers[0] === "issue-points"
          ? []
          : fake.rendered;
      }
      remove() {}
      resize() {}
      addImage() {}
    },
    Popup: class {
      remove() {}
    },
    NavigationControl: class {},
    AttributionControl: class {},
  },
}));
beforeEach(() => {
  fake.handlers.clear();
  fake.sources.clear();
  fake.layers.clear();
  fake.rendered = [];
  fake.onCreate.mockReset();
  fake.setLayerZoomRange.mockReset();
  vi.stubGlobal("matchMedia", () => ({ matches: true }));
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
it("renders eight meter points and type icons without shifting issue coordinates", () => {
  show();
  const meters = fake.sources.get("meters")!.setData.mock.calls.at(-1)![0];
  expect(meters.features).toHaveLength(8);
  expect(meters.features[0].properties).toMatchObject({
    code: "M-0",
    clientType: "RESIDENTIAL",
    lastReading: expect.stringContaining("1.5 kWh"),
  });
  expect(fake.sources.get("issues")!.setData).toHaveBeenLastCalledWith(
    data.issues,
  );
  expect(fake.layers.get("issue-points")!.layout).not.toHaveProperty(
    "icon-offset",
  );
  expect(fake.layers.get("issue-points")!.layout).toHaveProperty("icon-image");
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
  };
  const view = render(<NetworkMap {...props} />);
  view.rerender(<NetworkMap {...props} data={{ ...data }} />);
  expect(fake.setLayerZoomRange).not.toHaveBeenCalled();
  act(() => fake.handlers.get("load")!());
  expect(fake.setLayerZoomRange).toHaveBeenCalled();
});
