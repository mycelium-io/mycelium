// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Mock runners: one connected machine, and a job queue that moves by itself.
 *
 * A real job waits for the machine to pick it up and then runs; here a job's
 * status is read off its age (queued, then running, then done), so the app
 * shows the same progression without a runner. Finishing a launch puts the
 * agent on the machine and in the room's roster; finishing a stop marks it
 * stopped.
 */

import type { Framework, Runner, RunnerAgent, RunnerJob, RunnerJobKind } from "@/lib/api";

const iso = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();

const FRAMEWORKS: Framework[] = [
  {
    id: "claude",
    name: "Claude Code",
    command: "claude",
    path: "/Users/julia/.local/bin/claude",
    version: "2.4.1",
    installed: true,
    launchable: true,
    note: null,
  },
  {
    id: "opencode",
    name: "opencode",
    command: "opencode",
    path: "/opt/homebrew/bin/opencode",
    version: "0.9.3",
    installed: true,
    launchable: true,
    note: null,
  },
  {
    id: "codex",
    name: "Codex CLI",
    command: "codex",
    path: null,
    version: null,
    installed: false,
    launchable: false,
    note: "Not found on PATH.",
  },
];

export const MOCK_RUNNER_ID = "julias-mbp";

const runners: Runner[] = [
  {
    id: MOCK_RUNNER_ID,
    label: "julias-mbp",
    owner: "julia",
    platform: "darwin-arm64",
    version: "0.14.0",
    herdr: true,
    roots: ["/Users/julia/code/atlas", "/Users/julia/code/mycelium"],
    frameworks: FRAMEWORKS,
    agents: [
      {
        handle: "backfill",
        room: "atlas-migration",
        framework: "claude",
        status: "working",
        pane: "w3:p1",
        cwd: "/Users/julia/code/atlas",
        started_at: iso(42),
        detail: null,
      },
    ],
    connected: true,
    last_seen: iso(0),
    started_at: iso(90),
  },
];

interface StoredJob extends Omit<RunnerJob, "status" | "updated_at"> {
  /** When the mock job settles, and how. */
  failWith: string | null;
}

const jobs: StoredJob[] = [
  {
    id: "job-0001",
    runner: MOCK_RUNNER_ID,
    kind: "launch",
    spec: { room: "atlas-migration", handle: "backfill", framework: "claude", cwd: "/Users/julia/code/atlas" },
    result: { pane: "w3:p1" },
    error: null,
    created_by: "julia",
    created_at: iso(42),
    failWith: null,
  },
  {
    id: "job-0000",
    runner: MOCK_RUNNER_ID,
    kind: "scan",
    spec: {},
    result: { frameworks: 2 },
    error: null,
    created_by: null,
    created_at: iso(90),
    failWith: null,
  },
];

let seq = 2;
const applied = new Set<string>(["job-0000", "job-0001"]);

/** Queued for the first second, running until 2.5s, then settled. */
function statusOf(job: StoredJob): RunnerJob["status"] {
  const age = Date.now() - Date.parse(job.created_at);
  if (age < 1_000) return "queued";
  if (age < 2_500) return "running";
  return job.failWith ? "failed" : "done";
}

/** Carry out what a settled job did to its machine, once. */
function settle(job: StoredJob): void {
  if (applied.has(job.id) || statusOf(job) !== "done") return;
  applied.add(job.id);
  const runner = runners.find((r) => r.id === job.runner);
  if (!runner) return;
  const spec = job.spec as Record<string, string>;
  if (job.kind === "launch") {
    runner.agents = runner.agents.filter((a) => !(a.room === spec.room && a.handle === spec.handle));
    const agent: RunnerAgent = {
      handle: spec.handle,
      room: spec.room,
      framework: spec.framework,
      status: "idle",
      pane: `w4:p${runner.agents.length + 1}`,
      cwd: spec.cwd ?? runner.roots[0] ?? null,
      started_at: new Date().toISOString(),
      detail: null,
    };
    runner.agents.push(agent);
  } else if (job.kind === "stop") {
    const agent = runner.agents.find((a) => a.room === spec.room && a.handle === spec.handle);
    if (agent) agent.status = "stopped";
  }
}

function view(job: StoredJob): RunnerJob {
  settle(job);
  const status = statusOf(job);
  const { failWith, ...rest } = job;
  return {
    ...rest,
    status,
    error: status === "failed" ? failWith : null,
    updated_at: new Date().toISOString(),
  };
}

export function listRunners(): Runner[] {
  for (const j of jobs) settle(j);
  return runners.map((r) => ({ ...r, last_seen: new Date().toISOString() }));
}

export function getRunner(id: string): Runner | undefined {
  return listRunners().find((r) => r.id === id);
}

export function listJobs(runner: string): RunnerJob[] {
  return jobs
    .filter((j) => j.runner === runner)
    .map(view)
    .sort((a, b) => b.created_at.localeCompare(a.created_at));
}

export function getJob(runner: string, id: string): RunnerJob | undefined {
  const job = jobs.find((j) => j.runner === runner && j.id === id);
  return job ? view(job) : undefined;
}

export function queueJob(
  runner: string,
  kind: RunnerJobKind,
  spec: Record<string, unknown>,
  createdBy: string | null = null,
  failWith: string | null = null,
): RunnerJob {
  const job: StoredJob = {
    id: `job-${String(seq++).padStart(4, "0")}`,
    runner,
    kind,
    spec,
    result: null,
    error: null,
    created_by: createdBy,
    created_at: new Date().toISOString(),
    failWith,
  };
  jobs.push(job);
  return view(job);
}

/** The machine an agent in a room was started on, if the app started it. */
export function runnerAgentOf(room: string, handle: string): { runner: string; framework: string } | null {
  for (const r of runners) {
    const a = r.agents.find((x) => x.room === room && x.handle === handle);
    if (a) return { runner: r.id, framework: a.framework };
  }
  return null;
}

/** Agents a machine started in a room that the room's fixtures don't list. */
export function launchedHandles(room: string): { handle: string; runner: string; framework: string }[] {
  return runners.flatMap((r) =>
    r.agents
      .filter((a) => a.room === room)
      .map((a) => ({ handle: a.handle, runner: r.id, framework: a.framework })),
  );
}
