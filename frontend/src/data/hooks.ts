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
  IssueFilter,
  Region,
  LoginInput,
  Session,
  Issue,
  MapData,
  Page,
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
export function useMapMeters(region: Region, segmentId?: string) {
  const source = useSource();
  return useQuery({
    queryKey: ["map-meters", region, segmentId],
    enabled: !!segmentId,
    queryFn: async () => {
      if (!source.getMapMeters)
        throw new Error("Segment meter data is unavailable in this data mode.");
      return source.getMapMeters(region, segmentId!);
    },
  });
}
export function useIssues(filter: IssueFilter, enabled = true) {
  const source = useSource();
  return useQuery({
    queryKey: ["issues", filter],
    enabled,
    queryFn: async () => {
      if (!source.getIssues)
        throw new Error("Issues listing requires API mode.");
      return source.getIssues(filter);
    },
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
      void cache.invalidateQueries({ queryKey: ["issues"] });
      void cache.invalidateQueries({ queryKey: ["files"] });
      void cache.invalidateQueries({ queryKey: ["file"] });
    },
  });
}
function patchMapIssue(
  old: MapData | undefined,
  id: string,
  patch: Partial<Issue>,
) {
  return old
    ? {
        ...old,
        issueList: old.issueList.map((issue) =>
          issue.id === id ? { ...issue, ...patch } : issue,
        ),
        issues: {
          ...old.issues,
          features: old.issues.features.map((feature) =>
            feature.properties?.id === id && patch.status
              ? {
                  ...feature,
                  properties: { ...feature.properties, status: patch.status },
                }
              : feature,
          ),
        },
      }
    : old;
}
function patchIssuePage(
  old: Page<Issue> | undefined,
  id: string,
  patch: Partial<Issue>,
) {
  return old
    ? {
        ...old,
        items: old.items.map((issue) =>
          issue.id === id ? { ...issue, ...patch } : issue,
        ),
      }
    : old;
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
    onMutate: async (input) => {
      await Promise.all([
        cache.cancelQueries({ queryKey: ["map"] }),
        cache.cancelQueries({ queryKey: ["issues"] }),
      ]);
      const maps = cache.getQueriesData<MapData>({ queryKey: ["map"] });
      const issues = cache.getQueriesData<Page<Issue>>({
        queryKey: ["issues"],
      });
      cache.setQueriesData<MapData>({ queryKey: ["map"] }, (old) =>
        patchMapIssue(old, input.id, { status: input.status }),
      );
      cache.setQueriesData<Page<Issue>>({ queryKey: ["issues"] }, (old) =>
        patchIssuePage(old, input.id, { status: input.status }),
      );
      return { maps, issues };
    },
    onError: (_error, input, context) => {
      for (const [key, previous] of context?.maps ?? []) {
        const issue = previous?.issueList.find((i) => i.id === input.id);
        if (!issue) continue;
        cache.setQueryData<MapData>(key, (current) =>
          patchMapIssue(current, input.id, issue),
        );
      }
      for (const [key, previous] of context?.issues ?? []) {
        const issue = previous?.items.find((i) => i.id === input.id);
        if (!issue) continue;
        cache.setQueryData<Page<Issue>>(key, (current) =>
          patchIssuePage(current, input.id, issue),
        );
      }
    },
    onSuccess: (updated) => {
      cache.setQueriesData<MapData>({ queryKey: ["map"] }, (old) =>
        patchMapIssue(old, updated.id, updated),
      );
      cache.setQueriesData<Page<Issue>>({ queryKey: ["issues"] }, (old) =>
        patchIssuePage(old, updated.id, updated),
      );
    },
    onSettled: () =>
      Promise.all([
        cache.invalidateQueries({ queryKey: ["map"] }),
        cache.invalidateQueries({ queryKey: ["statistics"] }),
        cache.invalidateQueries({ queryKey: ["issues"] }),
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
