import {
  keepPreviousData,
  useMutation,
  useQuery,
  useQueryClient,
  type QueryClient,
} from "@tanstack/react-query";
import { useSource } from "./context";
import { AppError } from "./errors";
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
export function useMap(region: Region) {
  const source = useSource();
  return useQuery({
    queryKey: ["map", region],
    queryFn: () => source.getMap(region),
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
  return useQuery({
    queryKey: ["files", filter],
    queryFn: () => source.getFiles(filter),
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
