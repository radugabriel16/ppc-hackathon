import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { useSource } from "./context";
import { AppError } from "./errors";
import { REGIONS } from "./models";
import { useRegion } from "./region-context";
import type {
  CaseFilter,
  CreateIssue,
  FileFilter,
  IssueStatus,
  Region,
  LoginInput,
  Session,
} from "./models";

async function cacheSession(cache: QueryClient, session: Session | null) {
  await cache.cancelQueries();
  cache.removeQueries({
    predicate: (query) => query.queryKey[0] !== "session",
  });
  cache.setQueryData(["session"], session);
}
export function useDemoMode() {
  return useSource().kind === "demo";
}
export function useDataMode() {
  return useSource().kind;
}
export function useSession() {
  const source = useSource();
  return useQuery({
    queryKey: ["session"],
    queryFn: () => source.getSession(),
    staleTime: Infinity,
  });
}
export function useLogin() {
  const source = useSource();
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (input: LoginInput) => source.login(input),
    onSuccess: (session) => cacheSession(cache, session),
  });
}
export function useLogout() {
  const source = useSource();
  const cache = useQueryClient();
  return useMutation({
    mutationFn: () => source.logout(),
    onSuccess: () => cacheSession(cache, null),
  });
}
export function useGeography() {
  const source = useSource();
  return useQuery({
    queryKey: ["geography"],
    queryFn: () => source.getGeography(),
    staleTime: Infinity,
  });
}
export function useMap(region: Region, national = false) {
  const source = useSource();
  const { subregionId } = useRegion();
  return useQuery({
    queryKey: [
      "map",
      national ? "ROMANIA" : region,
      ...(subregionId ? [subregionId] : []),
    ],
    queryFn: async () => {
      if (!national) return source.getMap(region, subregionId);
      const maps = await Promise.all(REGIONS.map((r) => source.getMap(r)));
      return {
        assets: {
          type: "FeatureCollection" as const,
          features: maps.flatMap((m) => m.assets.features),
        },
        issues: {
          type: "FeatureCollection" as const,
          features: maps.flatMap((m) => m.issues.features),
        },
        outages: {
          type: "FeatureCollection" as const,
          features: maps.flatMap((m) => m.outages.features),
        },
        assetList: maps.flatMap((m) => m.assetList),
        issueList: maps.flatMap((m) => m.issueList),
      };
    },
    placeholderData: keepPreviousData,
  });
}
export function useCreateIssue() {
  const source = useSource();
  const cache = useQueryClient();
  return useMutation({
    mutationFn: (input: CreateIssue) => source.createIssue(input),
    onSuccess: () => {
      void cache.invalidateQueries({ queryKey: ["map"] });
      void cache.invalidateQueries({ queryKey: ["statistics"] });
    },
  });
}
export function useUpdateIssue() {
  const source = useSource();
  const cache = useQueryClient();
  return useMutation({
    mutationFn: async (input: {
      id: string;
      status: IssueStatus;
      version: number;
      simulateConflict?: boolean;
    }) => {
      try {
        return await source.updateIssue(input);
      } catch (error) {
        if (error instanceof AppError && error.status === 409)
          throw new AppError(409, {
            ...error.body,
            message: "someone else already took this issue",
          });
        throw error;
      }
    },
    onSettled: () =>
      Promise.all([
        cache.invalidateQueries({ queryKey: ["map"] }),
        cache.invalidateQueries({ queryKey: ["statistics"] }),
      ]),
  });
}
export function useFiles(filter: FileFilter) {
  const source = useSource();
  const { subregionId } = useRegion();
  const scoped = { ...filter, subregionId };
  return useQuery({
    queryKey: ["files", scoped],
    queryFn: () => source.getFiles(scoped),
    refetchInterval: 5000,
  });
}
export function useFile(id?: string) {
  const source = useSource();
  return useQuery({
    queryKey: ["file", id],
    queryFn: () => source.getFile(id!),
    enabled: !!id,
    refetchInterval: (query) =>
      query.state.data?.status === "VERIFYING" ? 1000 : false,
  });
}
export function useCases(filter: CaseFilter) {
  const source = useSource();
  return useQuery({
    queryKey: ["cases", filter],
    queryFn: () => source.getCases(filter),
  });
}
export function useStatistics(region: Region) {
  const source = useSource();
  return useQuery({
    queryKey: ["statistics", region],
    queryFn: () => source.getStatistics(region),
    refetchInterval: 5000,
  });
}
