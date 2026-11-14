import { useQuery } from "@tanstack/react-query";
import { useSource } from "./context";
import type { Region } from "./models";
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
  const { subregionId } = useRegion();
  return useQuery({
    queryKey: ["stats", "meters", region, subregionId],
    queryFn: () => source.getMeterConsumption(region, subregionId),
  });
}
export function useOutageHotspots(region: Region) {
  const source = useSource();
  const { subregionId } = useRegion();
  return useQuery({
    queryKey: ["stats", "hotspots", region, subregionId],
    queryFn: () => source.getOutageHotspots(region, subregionId),
  });
}
export function useForecast(region: Region) {
  const source = useSource();
  const { subregionId } = useRegion();
  return useQuery({
    queryKey: ["stats", "forecast", region, subregionId],
    queryFn: () => source.getForecast(region, subregionId),
  });
}
