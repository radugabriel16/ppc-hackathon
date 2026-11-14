import {
  CATEGORIES,
  type EffectivePolicy,
  type RecentAlert,
  type ScenarioRun,
  type SimulatorBackfill,
  type SimulatorStart,
  type SimulatorState,
} from "./models";

// UI-oriented state for the explicitly selected local demo, independent of HTTP DTOs.
export class DemoAdministration {
  private status: SimulatorState = {
    running: false,
    profile: null,
    readingsPerSecond: null,
  };
  private runs: ScenarioRun[] = [];
  private alerts: RecentAlert[] = [];
  constructor(private readonly authorize: () => void) {}
  async getPolicies(): Promise<EffectivePolicy[]> {
    this.authorize();
    return CATEGORIES.map((category) => ({
      category,
      backend: "s3",
      fallback: "ftp",
      maxSizeBytes: 1073741824,
      maxConcurrency: 3,
      encryption: "AES-256",
      resumable: true,
      chunkSizeBytes: 16777216,
    }));
  }
  reloadPolicies() {
    return this.getPolicies();
  }
  async getSimulatorStatus() {
    this.authorize();
    return { ...this.status };
  }
  async startSimulator(input: SimulatorStart) {
    this.authorize();
    await this.stopSimulator();
    this.status = { running: true, ...input };
    this.runs.unshift({
      id: crypto.randomUUID(),
      kind: "SIMULATOR",
      profile: input.profile,
      startedAt: new Date().toISOString(),
      endedAt: null,
      counters: { readings: 0 },
    });
    return { ...this.status };
  }
  async stopSimulator() {
    this.authorize();
    this.status = { running: false, profile: null, readingsPerSecond: null };
    for (const run of this.runs)
      if (run.kind === "SIMULATOR" && run.endedAt === null)
        run.endedAt = new Date().toISOString();
    return { ...this.status };
  }
  async backfillSimulator(input: SimulatorBackfill) {
    this.authorize();
    const now = new Date().toISOString();
    const run: ScenarioRun = {
      id: crypto.randomUUID(),
      kind: "BACKFILL",
      profile: input.anomaly,
      startedAt: now,
      endedAt: now,
      counters: { anomalies: 1 },
    };
    this.runs.unshift(run);
    this.alerts.unshift({
      id: crypto.randomUUID(),
      severity: "WARNING",
      message: `Demo ${input.anomaly} anomaly in historical readings.`,
      occurredAt: now,
    });
    return run;
  }
  async getScenarioRuns(page: number, size: number) {
    this.authorize();
    return {
      items: this.runs.slice(page * size, (page + 1) * size),
      page,
      size,
      totalElements: this.runs.length,
      totalPages: Math.ceil(this.runs.length / size),
    };
  }
  async getRecentAlerts() {
    this.authorize();
    return [...this.alerts];
  }
}
