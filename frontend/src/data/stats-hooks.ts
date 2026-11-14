import { useQuery } from "@tanstack/react-query";
import { useSource } from "./context";
import type { Region } from "./models";

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
  return useQuery({
    queryKey: ["stats", "meters", region],
    queryFn: () => source.getMeterConsumption(region),
  });
}
export function useOutageHotspots(region: Region) {
  const source = useSource();
  return useQuery({
    queryKey: ["stats", "hotspots", region],
    queryFn: () => source.getOutageHotspots(region),
  });
}
export function useForecast(region: Region) {
  const source = useSource();
  return useQuery({
    queryKey: ["stats", "forecast", region],
    queryFn: () => source.getForecast(region),
  });
}
