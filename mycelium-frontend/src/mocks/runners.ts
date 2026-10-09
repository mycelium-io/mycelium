// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Mock runners: one connected machine, and a job queue that moves by itself.
 *
 * A real job waits for the machine to pick it up and then runs; here a job's
 * status is read off its age (queued, then running, then done), so the app
 * shows the same progression without a runner. Finishing a launch puts the
 * agent on the machine and in the room's roster; finishing a stop marks it
 * stopped. A second machine, a remote Mac mini, is paired with a
 * device; pairing this browser with it (any well-formed code) adds another.
 */

import { DEMO_PERSON, isDemoScenario } from "./demo";
import { LEARN_PERSON, LEARN_ROOTS, isLearnScenario } from "./learn";
import type {
  Framework,
  MachineAgent,
  MachineProblem,
  MachineReport,
  Runner,
  RunnerAgent,
  RunnerJob,
  RunnerJobKind,
  RunnerPairing,
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

/** A remote machine: it starts what a paired device asks for without approval. */
export const MOCK_MINI_ID = "studio-mini";

if (!isDemoScenario() && !isLearnScenario()) {
  runners.push({
    id: MOCK_MINI_ID,
    label: "studio-mini",
    owner: "operator",
    platform: "darwin-arm64",
    version: "0.14.0",
    herdr: true,
    roots: ["/Users/morgan/models"],
    frameworks: FRAMEWORKS,
    agents: [],
    pairings: [
      {
        name: "work laptop",
        key: "59802479f5b1936d",
        paired_at: iso(60 * 24 * 3),
        expires_at: new Date(Date.now() + 87 * 24 * 3_600_000).toISOString(),
        folders: ["/Users/morgan/models"],
        clis: ["opencode"],
        swarms: false,
      },
    ],
    connected: true,
    last_seen: iso(0),
    started_at: iso(600),
  });
}

// The demo is recorded as Sam, on Sam's machine, before @builder exists.
if (isDemoScenario()) {
  Object.assign(runners[0], {
    label: "sams-mbp",
    owner: DEMO_PERSON.handle,
    roots: [`${DEMO_PERSON.home}/code/shop`, `${DEMO_PERSON.home}/code/website`],
    agents: [],
  });
}

// A Learn take is recorded as Sam too, on a machine that asks before it starts
// anything (the dialog shows the yes being given).
if (isLearnScenario()) {
  Object.assign(runners[0], {
    label: "sams-mbp",
    owner: LEARN_PERSON.handle,
    roots: LEARN_ROOTS,
    agents: [],
  });
}

interface StoredJob extends Omit<RunnerJob, "status" | "updated_at"> {
  /** When the mock job settles, and how. */
  failWith: string | null;
  /** What a failed start reports: the step it stopped at, why, and its terminal. */
  failResult?: Record<string, unknown> | null;
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

/** Queued for the first second, running until 2.5s, then settled; a Learn
 *  take's launch waits on a yes first. */
function statusOf(job: StoredJob): RunnerJob["status"] {
  const age = Date.now() - Date.parse(job.created_at);
  if (isLearnScenario() && (job.kind === "launch" || job.kind === "swarm")) {
    if (age < 1_000) return "queued";
    if (age < 3_200) return "waiting";
    if (age < 4_600) return "running";
    return job.failWith ? "failed" : "done";
  }
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
  } else if (job.kind === "pair") {
    const r = job.result as unknown as RunnerPairing;
    const pairing: RunnerPairing = {
      name: r.name,
      key: r.key,
      paired_at: r.paired_at,
      expires_at: r.expires_at,
      folders: r.folders,
      clis: r.clis,
      swarms: r.swarms,
    };
    runner.pairings = [...(runner.pairings ?? []).filter((p) => p.key !== pairing.key), pairing];
  }
}

/** The step a running start has reached, as a runner reports it: a terminal
 *  opened, then its shell and the agent CLI in it. */
function stepOf(job: StoredJob): Record<string, unknown> | null {
  if (job.kind !== "launch") return null;
  const age = Date.now() - Date.parse(job.created_at);
  return { step: age < 1_700 ? "terminal" : "shell" };
}

function view(job: StoredJob): RunnerJob {
  settle(job);
  const status = statusOf(job);
  const { failWith, failResult, ...rest } = job;
  const result =
    status === "failed" ? (failResult ?? rest.result) : status === "running" ? (stepOf(job) ?? rest.result) : rest.result;
  return {
    ...rest,
    status,
    result,
    error: status === "failed" ? failWith : null,
    updated_at: new Date().toISOString(),
  };
}

/**
 * How a mock start ends, read off its handle so a failure can be seen without
 * a machine: `slow-…` has a terminal whose shell never reaches a prompt, and
 * `update-…` an agent CLI stopped at an update prompt. Anything else starts.
 */
export function mockStartOutcome(
  handle: string,
  cli: string,
  machine: string,
): { failWith: string; failResult: Record<string, unknown> } | null {
  if (handle.startsWith("slow-")) {
    return {
      failWith: `${cli} couldn't start on ${machine}: the terminal opened for @${handle} didn't reach a shell prompt within 30 seconds. It's still open in herdr (pane w5:p1). When it shows a prompt, start @${handle} again: it goes back to that terminal.`,
      failResult: {
        step: "shell",
        why: "shell",
        pane: "w5:p1",
        detail: "agent target pane w5:p1 is not an available shell",
      },
    };
  }
  if (handle.startsWith("update-")) {
    return {
      failWith: `${cli} didn't finish starting on ${machine}. Often it's waiting for an update, a sign-in or a first-run question. It's still open in herdr (pane w7:p1): answer what it shows there, then start @${handle} again.`,
      failResult: {
        step: "agent",
        why: "cli",
        pane: "w7:p1",
        screen: `A new version of ${cli} is available (1.4.0 -> 1.5.2).\n\n  1. Update now\n  2. Skip this version\n\nPress enter to continue`,
        detail: "agent target pane w7:p1 is not an available shell",
      },
    };
  }
  return null;
}

export function listRunners(): Runner[] {
  for (const j of jobs) settle(j);
  return runners.map((r) => ({ ...r, last_seen: new Date().toISOString() }));
}

/** Pair a device with the Mac mini, as its runner would once it checked the proof. */
export async function pairDevice(body: Record<string, unknown>): Promise<RunnerJob> {
  const key = (body.key ?? {}) as { x?: string; y?: string };
  const b64 = (t: string) => Uint8Array.from(atob(t.replace(/-/g, "+").replace(/_/g, "/")), (c) => c.charCodeAt(0));
  const point = new Uint8Array([4, ...b64(key.x ?? ""), ...b64(key.y ?? "")]);
  const digest = new Uint8Array(await crypto.subtle.digest("SHA-256", point));
  const id = Array.from(digest, (b) => b.toString(16).padStart(2, "0")).join("").slice(0, 16);
  const pairing: RunnerPairing = {
    name: String(body.name ?? "this device"),
    key: id,
    paired_at: new Date().toISOString(),
    expires_at: new Date(Date.now() + 90 * 24 * 3_600_000).toISOString(),
    folders: [],
    clis: [],
    swarms: false,
  };
  const spec = { offer: String(body.code_id ?? ""), name: pairing.name, key };
  return queueJob(MOCK_MINI_ID, "pair", spec, null, null, { label: "studio-mini", ...pairing });
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
  result: Record<string, unknown> | null = null,
  failResult: Record<string, unknown> | null = null,
): RunnerJob {
  const job: StoredJob = {
    id: `job-${String(seq++).padStart(4, "0")}`,
    runner,
    kind,
    spec,
    result,
    error: null,
    created_by: createdBy,
    created_at: new Date().toISOString(),
    failWith,
    failResult,
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
