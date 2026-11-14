import { useQuery } from "@tanstack/react-query";
import { useSource } from "./context";
import { REGIONS, type Region, type ForecastPoint } from "./models";
import { useRegion } from "./region-context";

export function useStorageBenchmark() {
  const source = useSource();
  return useQuery({
    queryKey: ["stats", "benchmark"],
    queryFn: () => source.getStorageBenchmark(),
  });
}
export function useStorageRecommendations() {
  const source = useSource();
  return useQuery({
    queryKey: ["stats", "recommendations"],
    queryFn: () => source.getStorageRecommendations(),
  });
}
export function useMeterConsumption(region: Region) {
  const source = useSource();
  const { subregionId, selectedRegion } = useRegion();
  return useQuery({
    queryKey: ["stats", "meters", selectedRegion, subregionId],
    queryFn: async () =>
      selectedRegion
        ? source.getMeterConsumption(region, subregionId)
        : (
            await Promise.all(REGIONS.map((r) => source.getMeterConsumption(r)))
          ).flat(),
  });
}
export function useOutageHotspots(region: Region) {
  const source = useSource();
  const { subregionId, selectedRegion } = useRegion();
  return useQuery({
    queryKey: ["stats", "hotspots", selectedRegion, subregionId],
    queryFn: async () =>
      selectedRegion
        ? source.getOutageHotspots(region, subregionId)
        : (
            await Promise.all(REGIONS.map((r) => source.getOutageHotspots(r)))
          ).flat(),
  });
}
export function useForecast(region: Region) {
  const source = useSource();
  const { subregionId, selectedRegion } = useRegion();
  return useQuery({
    queryKey: ["stats", "forecast", selectedRegion, subregionId],
    queryFn: async () => {
      if (selectedRegion) return source.getForecast(region, subregionId);
      const groups = await Promise.all(
        REGIONS.map((r) => source.getForecast(r)),
      );
      const first = groups.find((g) => g.length);
      if (!first) return [];
      return first.map((point): ForecastPoint => {
        const days = groups.map((group) =>
          group.find((d) => d.timestamp === point.timestamp),
        );
        const complete = days.every((d) => d && d.estimate !== null);
        return {
          ...point,
          estimate: complete
            ? days.reduce((sum, d) => sum + d!.estimate!, 0)
            : null,
          status: complete ? "READY" : "INSUFFICIENT_DATA",
          fallbackUsed: days.some((d) => d?.fallbackUsed),
        };
      });
    },
  });
}
