import { use as registerCharts, init } from "echarts/core";
import {
  BarChart,
  HeatmapChart,
  LineChart,
  ScatterChart,
} from "echarts/charts";
import {
  AriaComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  TooltipComponent,
  VisualMapComponent,
} from "echarts/components";
import { SVGRenderer } from "echarts/renderers";

registerCharts([
  BarChart,
  HeatmapChart,
  LineChart,
  ScatterChart,
  AriaComponent,
  DataZoomComponent,
  GridComponent,
  LegendComponent,
  MarkAreaComponent,
  TooltipComponent,
  VisualMapComponent,
  SVGRenderer,
]);
export { init };
