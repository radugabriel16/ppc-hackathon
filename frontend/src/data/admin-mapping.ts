import type {
  Alert,
  PoliciesConfig,
  ScenarioRun as RunDto,
  SimulatorStatus,
} from "../api/gen/types.gen";
import type {
  EffectivePolicy,
  RecentAlert,
  ScenarioRun,
  SimulatorState,
} from "./models";
import { requireValue } from "./api-client";

export function policyRows(dto: PoliciesConfig): EffectivePolicy[] {
  return Object.entries(requireValue(dto.categories, "policies.categories"))
    .sort(([a], [b]) => a.localeCompare(b))
    .map(([category, policy]) => ({
      category,
      backend: policy.backend ?? null,
      fallback: policy.fallback ?? null,
      maxSizeBytes: policy.maxSizeBytes ?? null,
      maxConcurrency: policy.maxConcurrency ?? null,
      encryption: policy.encryption ?? null,
      resumable: policy.resumable ?? null,
      chunkSizeBytes: policy.chunkSizeBytes ?? null,
    }));
}
export function simulatorState(dto: SimulatorStatus): SimulatorState {
  return {
    running: requireValue(dto.running, "simulator.running"),
    profile: dto.profile ?? null,
    readingsPerSecond: dto.readingsPerSecond ?? null,
  };
}
export function scenarioRun(dto: RunDto): ScenarioRun {
  return {
    id: requireValue(dto.id, "scenarioRun.id"),
    kind: dto.kind ?? null,
    profile: dto.profile ?? null,
    startedAt: dto.startedAt ?? null,
    endedAt: dto.endedAt ?? null,
    counters: dto.counters ?? {},
  };
}
export function recentAlert(dto: Alert): RecentAlert {
  return {
    id: requireValue(dto.id, "alert.id"),
    severity: dto.severity ?? null,
    message: requireValue(dto.message, "alert.message"),
    occurredAt: dto.occurredAt ?? null,
  };
}
