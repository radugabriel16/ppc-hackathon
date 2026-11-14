import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSource } from "./context";
import type { ForecastRunCreate, ForecastRun } from "./models";

export function useForecastRun(id?: string) {
  const source = useSource();
  return useQuery({
    queryKey: ["forecast-run", id],
    enabled: !!id && !!source.getForecastRun,
    queryFn: () => source.getForecastRun!(id!),
    refetchInterval: (query) =>
      query.state.data?.status === "RUNNING" ? 1500 : false,
  });
}

export function useGenerateForecast() {
  const source = useSource();
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (input: ForecastRunCreate) => {
      if (!source.createForecastRun)
        throw new Error("Forecast runs require API mode.");
      return source.createForecastRun(input);
    },
    onSuccess: async (run: ForecastRun) => {
      cache.setQueryData(["forecast-run", run.id], run);
      await Promise.all(
        ["map", "issues", "forecast-thresholds", "alerts", "stats"].map((key) =>
          cache.invalidateQueries({ queryKey: [key] }),
        ),
      );
    },
  });
}

export function useThresholds() {
  const source = useSource();
  return useQuery({
    queryKey: ["forecast-thresholds"],
    enabled: !!source.getForecastThresholds,
    queryFn: () => source.getForecastThresholds!(),
  });
}

export function useEditThreshold() {
  const source = useSource();
  const cache = useQueryClient();
  return useMutation({
    mutationFn: ({
      segmentId,
      value,
    }: {
      segmentId: string;
      value: number;
    }) => {
      if (!source.updateForecastThreshold)
        throw new Error("Threshold editing requires API mode.");
      return source.updateForecastThreshold(segmentId, value);
    },
    onSuccess: () =>
      cache.invalidateQueries({ queryKey: ["forecast-thresholds"] }),
  });
}
