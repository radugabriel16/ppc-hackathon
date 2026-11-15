import { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useSource } from "./context";
import type { MeterReadingFilter, Region } from "./models";

export function usePageVisible() {
  const [visible, setVisible] = useState(() => document.visibilityState === "visible");
  useEffect(() => {
    const update = () => setVisible(document.visibilityState === "visible");
    document.addEventListener("visibilitychange", update);
    return () => document.removeEventListener("visibilitychange", update);
  }, []);
  return visible;
}

export function useReadingMeters(region?: Region, segmentId?: string) {
  const source = useSource();
  return useQuery({
    queryKey: ["meter-readings", "meters", region, segmentId],
    queryFn: () => source.getReadingMeters(region, segmentId),
  });
}

export function useMeterReadings(
  filter: MeterReadingFilter,
  refresh = false,
  enabled = true,
) {
  const source = useSource();
  const visible = usePageVisible();
  return useQuery({
    queryKey: ["meter-readings", "rows", filter, refresh],
    queryFn: () => source.getMeterReadings(filter),
    enabled: enabled && visible,
    refetchInterval: refresh && visible ? 2000 : false,
  });
}

export function useMeterReadingWindow(meterId: string) {
  const source = useSource();
  return useQuery({
    queryKey: ["meter-readings", "window", meterId],
    queryFn: () => source.getMeterReadingWindow(meterId),
  });
}
