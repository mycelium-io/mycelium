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

import { DEMO_PERSON, isDemoScenario } from "./demo";
import type {
  Framework,
  MachineAgent,
  MachineProblem,
  MachineReport,
  Runner,
  RunnerAgent,
  RunnerJob,
  RunnerJobKind,
} from "@/lib/api";

const iso = (minutesAgo: number) => new Date(Date.now() - minutesAgo * 60_000).toISOString();

const FRAMEWORKS: Framework[] = [
  {
    id: "claude",
    name: "Claude Code",
    command: "claude",
    path: "/Users/morgan/.local/bin/claude",
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

export const MOCK_RUNNER_ID = "morgans-mbp";

/**
 * Every agent on the mock machine, the morning after herdr's server restarted
 * without its integrations: @builder was started again, @reviewer's and
 * @scribe's panes are open but empty, one old pane is gone, and herdr's server
 * is older than Mycelium needs.
 */
const machine: MachineReport = {
  machine: "morgans-mbp",
  herdr: true,
  herdr_server: "0.8.0",
  herdr_client: "0.9.3",
  herdr_minimum: "0.9.3",
  runner: true,
  missing_integrations: ["claude", "opencode"],
  workspaces: [
    {
      id: "w3",
      label: "checkout",
      room: "checkout",
      agents: [
        machineAgent("builder", "checkout", "w3:p1", "working", "claude", "/Users/morgan/code/shop"),
        machineAgent("reviewer", "checkout", "w3:p2", "stopped", "claude", "/Users/morgan/code/shop"),
      ],
    },
    {
      id: "w5",
      label: "storefront",
      room: "storefront",
      agents: [
        machineAgent("scribe", "storefront", "w5:p1", "stopped", "opencode", "/Users/morgan/code/website"),
      ],
    },
    {
      id: "gone",
      label: "Panes that are gone",
      room: null,
      agents: [machineAgent("poc-review", "checkout", "w2:pV", "gone", "claude", null)],
    },
  ],
  problems: [],
};

function machineAgent(
  handle: string,
  room: string,
  pane: string,
  state: MachineAgent["state"],
  kind: string,
  folder: string | null,
): MachineAgent {
  const open = state !== "gone";
  return {
    handle,
    room,
    pane,
    state,
    kind,
    folder,
    workspace: open ? pane.split(":")[0] : null,
    restores: open ? false : null,
    restartable: (state === "stopped" || state === "gone") && folder !== null,
  };
}

/** The problems, worked out as the runner would from the agents. */
function problemsOf(report: MachineReport): MachineProblem[] {
  const agents = report.workspaces.flatMap((w) => w.agents);
  const names = (list: MachineAgent[]) => list.map((a) => `@${a.handle}`).join(" and ");
  const out: MachineProblem[] = [];
  const stopped = agents.filter((a) => a.restartable);
  if (stopped.length > 0) {
    out.push({
      kind: "stopped",
      text: `${names(stopped)} stopped. Restarting starts ${stopped.length === 1 ? "it" : "each"} again in its folder, as itself, to catch up from the room.`,
      fix: "mycelium machine restart --all",
      handles: stopped.map((a) => a.handle),
    });
  }
  const lost = agents.filter((a) => a.state === "gone" && !a.restartable);
  if (lost.length > 0) {
    out.push({
      kind: "lost",
      text: `${names(lost)} ${lost.length === 1 ? "has" : "have"} no pane any more and nothing to restart it from. Unbinding forgets the pane. ${lost.length === 1 ? "It stays" : "They stay"} in the room.`,
      fix: "mycelium machine unbind --gone",
      handles: lost.map((a) => a.handle),
    });
  }
  const without = agents.filter((a) => a.restores === false);
  if (report.missing_integrations.length > 0) {
    out.push({
      kind: "no_restore",
      text: `If herdr restarts, ${names(without)} won't come back on their own: herdr's integration for ${report.missing_integrations.join(", ")} isn't installed (or is out of date). Installing it adds a hook to that agent CLI's own settings.`,
      fix: "mycelium machine integrations --install",
      handles: without.map((a) => a.handle),
    });
  }
  out.push({
    kind: "herdr_update",
    text: `herdr's server is ${report.herdr_server}, out of date: Mycelium needs ${report.herdr_minimum} or newer. This machine has ${report.herdr_client}, which starts when the old server stops. Restarting herdr's server stops the agents in it; those with herdr's integration come back on their own, and the rest can be restarted from here.`,
    fix: "herdr server stop",
    handles: [],
  });
  return out;
}

machine.problems = problemsOf(machine);

const runners: Runner[] = [
  {
    id: MOCK_RUNNER_ID,
    label: "morgans-mbp",
    owner: "operator",
    platform: "darwin-arm64",
    version: "0.14.0",
    herdr: true,
    roots: ["/Users/morgan/code/shop", "/Users/morgan/code/website"],
    frameworks: FRAMEWORKS,
    agents: [
      {
        handle: "builder",
        room: "checkout",
        framework: "claude",
        status: "working",
        pane: "w3:p1",
        cwd: "/Users/morgan/code/shop",
        started_at: iso(42),
        detail: null,
      },
    ],
    machine,
    connected: true,
    last_seen: iso(0),
    started_at: iso(90),
  },
];

// The demo is recorded as Sam, on Sam's machine, before @builder exists.
if (isDemoScenario()) {
  Object.assign(runners[0], {
    label: "sams-mbp",
    host: "omnigent",
    owner: DEMO_PERSON.handle,
    roots: [`${DEMO_PERSON.home}/code/shop`, `${DEMO_PERSON.home}/code/website`],
    agents: [],
  });
}

interface StoredJob extends Omit<RunnerJob, "status" | "updated_at"> {
  /** When the mock job settles, and how. */
  failWith: string | null;
}

const jobs: StoredJob[] = [
  {
    id: "job-0001",
    runner: MOCK_RUNNER_ID,
    kind: "launch",
    spec: { room: "checkout", handle: "builder", framework: "claude", cwd: "/Users/morgan/code/shop" },
    result: { pane: "w3:p1" },
    error: null,
    created_by: "operator",
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
  } else if (job.kind === "restart") {
    const named = (job.spec as { agents?: { handle: string; room: string }[] }).agents ?? [];
    for (const a of machine.workspaces.flatMap((w) => w.agents)) {
      if (named.some((n) => n.handle === a.handle && n.room === a.room)) {
        Object.assign(a, { state: "idle", restartable: false });
      }
    }
    machine.problems = problemsOf(machine);
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
