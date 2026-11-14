import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { useSource } from "./context";
import { useSession } from "./hooks";
import type { SimulatorBackfill, SimulatorStart } from "./models";

export const ADMIN_REFRESH_MS = 10000;
export function usePolicies() {
  const source = useSource();
  const { data: session } = useSession();
  return useQuery({
    queryKey: ["admin", "policies"],
    queryFn: () => source.getPolicies(),
    enabled: session?.user.role === "MANAGER",
  });
}
export function useReloadPolicies() {
  const source = useSource();
  const cache = useQueryClient();
  return useMutation({
    mutationFn: () => source.reloadPolicies(),
    onSuccess: (policies) =>
      cache.setQueryData(["admin", "policies"], policies),
  });
}
export function useSimulatorStatus() {
  const source = useSource();
  const { data: session } = useSession();
  return useQuery({
    queryKey: ["admin", "simulator"],
    queryFn: () => source.getSimulatorStatus(),
    enabled: session?.user.role === "MANAGER",
    refetchInterval: ADMIN_REFRESH_MS,
  });
}
export function useSimulatorControls() {
  const source = useSource();
  const cache = useQueryClient();
  const onSuccess = () => cache.invalidateQueries({ queryKey: ["admin"] });
  const start = useMutation({
    mutationFn: (input: SimulatorStart) => source.startSimulator(input),
    onSuccess,
  });
  const stop = useMutation({
    mutationFn: () => source.stopSimulator(),
    onSuccess,
  });
  const backfill = useMutation({
    mutationFn: (input: SimulatorBackfill) => source.backfillSimulator(input),
    onSuccess,
  });
  return { start, stop, backfill };
}
export function useScenarioRuns(page: number, size: number) {
  const source = useSource();
  const { data: session } = useSession();
  return useQuery({
    queryKey: ["admin", "runs", page, size],
    queryFn: () => source.getScenarioRuns(page, size),
    enabled: session?.user.role === "MANAGER",
    refetchInterval: ADMIN_REFRESH_MS,
  });
}
export function useRecentAlerts() {
  const source = useSource();
  const { data: session } = useSession();
  return useQuery({
    queryKey: ["admin", "alerts"],
    queryFn: () => source.getRecentAlerts(),
    enabled: session?.user.role === "MANAGER",
    refetchInterval: ADMIN_REFRESH_MS,
  });
}
