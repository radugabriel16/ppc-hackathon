import { useEffect, useRef, useState } from "react";
import { Box } from "@mui/material";
import type { EChartsOption } from "echarts";
import { init } from "../charts/runtime";
import { ErrorNotice } from "./common";

export function StatisticsChart({
  option,
  label,
  height = 340,
}: {
  option: EChartsOption;
  label: string;
  height?: number;
}) {
  const container = useRef<HTMLDivElement>(null);
  const [error, setError] = useState<unknown>();
  const latest = useRef(option);
  const chart = useRef<ReturnType<typeof init> | null>(null);
  useEffect(() => {
    latest.current = option;
    try {
      chart.current?.setOption(option, { notMerge: true });
    } catch (error) {
      setError(error);
    }
  }, [option]);
  useEffect(() => {
    if (!container.current) return;
    let observer: ResizeObserver | undefined;
    try {
      const instance = init(container.current, undefined, { renderer: "svg" });
      chart.current = instance;
      instance.setOption(latest.current);
      observer = new ResizeObserver(() => instance.resize());
      observer.observe(container.current);
    } catch (error) {
      setError(error);
    }
    return () => {
      observer?.disconnect();
      chart.current?.dispose();
      chart.current = null;
    };
  }, []);
  return (
    <>
      <Box
        ref={container}
        role="img"
        aria-label={label}
        sx={{ width: "100%", height, minWidth: 0 }}
      />
      {error !== undefined && <ErrorNotice error={error} />}
    </>
  );
}
