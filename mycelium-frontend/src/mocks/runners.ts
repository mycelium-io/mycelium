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

import type { Framework, MachineReport, Runner, RunnerAgent, RunnerJob, RunnerJobKind } from "@/lib/api";

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
 * Every agent on the mock machine, the morning after herdr's server restarted:
 * @builder came back in its own pane and is working, @reviewer's pane is open
 * but empty (its session saved, so it can be resumed), the storefront
 * workspace has nothing syncing it, one old pane is gone, and herdr's server
 * is behind its client.
 */
function machineReport(): MachineReport {
  return {
    machine: "morgans-mbp",
    herdr: true,
    herdr_server: "0.8.0",
    herdr_client: "0.9.1",
    omnigent_url: null,
    workspaces: [
      {
        id: "w3",
        label: "checkout",
        host: "herdr",
        room: "checkout",
        synced_by: "runner",
        runner_keeps: true,
        agents: [
          {
            handle: "builder",
            room: "checkout",
            host: "herdr",
            ref: "w3:p1",
            state: "working",
            folder: "/Users/morgan/code/shop",
            session: "5f3c9e10-7b2a-4c11-9d8e-2b6a1fe0a1e2",
            kind: "claude",
            workspace: "w3",
            started_by: "runner",
            resumable: false,
          },
          {
            handle: "reviewer",
            room: "checkout",
            host: "herdr",
            ref: "w3:p2",
            state: "stopped",
            folder: "/Users/morgan/code/shop",
            session: "9b07c2d4-1e5f-4a8b-b3c6-7d9e0f1a44c0",
            kind: "claude",
            workspace: "w3",
            started_by: "runner",
            resumable: true,
            resume_command: "cd ~/code/shop && claude --resume 9b07c2d4-1e5f-4a8b-b3c6-7d9e0f1a44c0",
          },
        ],
      },
      {
        id: "w5",
        label: "storefront",
        host: "herdr",
        room: "storefront",
        synced_by: null,
        runner_keeps: false,
        agents: [
          {
            handle: "copywriter",
            room: "storefront",
            host: "herdr",
            ref: "w5:p1",
            state: "idle",
            folder: "/Users/morgan/code/website",
            session: null,
            kind: "claude",
            workspace: "w5",
            started_by: "you",
            resumable: false,
          },
          {
            // A CLI Mycelium can't resume: seen, stopped, unbound, never resumed.
            handle: "scribe",
            room: "storefront",
            host: "herdr",
            ref: "w5:p2",
            state: "stopped",
            folder: "/Users/morgan/code/website",
            session: null,
            kind: "codex",
            workspace: "w5",
            started_by: "you",
            resumes: false,
            resumable: false,
          },
        ],
      },
      {
        id: "gone",
        label: "Panes that are gone",
        host: "herdr",
        room: null,
        synced_by: null,
        runner_keeps: false,
        agents: [
          {
            handle: "poc-review",
            room: "checkout",
            host: "herdr",
            ref: "w2:pV",
            state: "gone",
            folder: null,
            session: null,
            kind: "claude",
            workspace: null,
            started_by: "you",
            resumable: false,
          },
        ],
      },
    ],
    problems: [],
  };
}

/** The problems a report shows, worked out as the runner would from its agents. */
function problemsOf(report: MachineReport): MachineReport["problems"] {
  const agents = report.workspaces.flatMap((w) => w.agents);
  const out: MachineReport["problems"] = [];
  const resumable = agents.filter((a) => a.resumable);
  if (resumable.length > 0) {
    out.push({
      kind: "stopped",
      text: `${resumable.map((a) => `@${a.handle}`).join(" and ")} stopped. ${resumable.length > 1 ? "Their sessions are" : "Its session is"} saved, so they can pick up where they left off.`,
      fix: "mycelium machine resume --all",
      handles: resumable.map((a) => a.handle),
      workspace: null,
    });
  }
  for (const w of report.workspaces) {
    const live = w.agents.filter((a) => ["working", "idle", "blocked"].includes(a.state));
    if (w.host === "herdr" && w.room && live.length > 0 && !w.synced_by && !w.runner_keeps) {
      out.push({
        kind: "unsynced",
        text: `Nothing keeps ${w.label} synced, so ${live.map((a) => `@${a.handle}`).join(" and ")} won't be woken by mentions and the room can't see whether they're busy.`,
        fix: `mycelium machine sync ${w.id} on`,
        handles: [],
        workspace: w.id,
      });
    }
  }
  const cannot = agents.filter((a) => a.state === "stopped" && a.resumes === false);
  if (cannot.length > 0) {
    const one = cannot.length === 1;
    out.push({
      kind: "unresumable",
      text: `${cannot.map((a) => `@${a.handle}`).join(" and ")} stopped, and Mycelium can't resume ${one ? "its agent CLI, so it" : "their agent CLIs, so they"} can't pick up where ${one ? "it" : "they"} left off. ${one ? "Start it again in its pane" : "Start each again in its pane"}; the room keeps ${one ? "its" : "their"} place.`,
      fix: null,
      handles: cannot.map((a) => a.handle),
      workspace: null,
    });
  }
  const lost = agents.filter((a) => a.state === "gone" && !a.resumable);
  if (lost.length > 0) {
    out.push({
      kind: "unresumable",
      text: `${lost.map((a) => `@${a.handle}`).join(" and ")} ${lost.length === 1 ? "has" : "have"} no pane any more and no saved session, so there's nothing to resume. Unbinding forgets the pane. ${lost.length === 1 ? "It stays" : "They stay"} in the room.`,
      fix: "mycelium machine unbind --gone",
      handles: lost.map((a) => a.handle),
      workspace: null,
    });
  }
  if (report.herdr_server && report.herdr_client && report.herdr_server < report.herdr_client) {
    out.push({
      kind: "herdr_update",
      text: `herdr's server (${report.herdr_server}) is older than its client (${report.herdr_client}). Updating restarts the server, which stops every agent in it; resume them after.`,
      fix: "herdr server stop  (then: mycelium machine resume --all)",
      handles: [],
      workspace: null,
    });
  }
  return out;
}

const machine = machineReport();

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
    const onMachine = machineAgent(spec.handle, spec.room);
    if (onMachine) onMachine.state = "stopped";
  } else if (job.kind === "resume") {
    const raw = job.spec as { all?: boolean; agents?: { handle: string; room: string | null }[] };
    const all = machine.workspaces.flatMap((w) => w.agents);
    const picked = raw.all ? all.filter((a) => a.resumable) : (raw.agents ?? []).map((a) => machineAgent(a.handle, a.room));
    for (const agent of picked) {
      if (agent) Object.assign(agent, { state: "idle", resumable: false });
    }
  } else if (job.kind === "sync") {
    const w = machine.workspaces.find((x) => x.id === spec.workspace);
    if (w) {
      const on = Boolean((job.spec as { on?: boolean }).on);
      Object.assign(w, { runner_keeps: on, synced_by: on ? "runner" : null });
    }
  } else if (job.kind === "unbind") {
    for (const w of machine.workspaces) {
      w.agents = (job.spec as { gone?: boolean }).gone
        ? w.agents.filter((a) => !(a.state === "gone" && !a.resumable))
        : w.agents.filter((a) => !(a.handle === spec.handle && (!spec.room || a.room === spec.room)));
    }
  } else if (job.kind === "session") {
    const agent = machineAgent(spec.handle, spec.room);
    if ((job.spec as { find?: boolean }).find) {
      job.result = {
        found: { id: "4d2a77e1-0c3b-4f9e-8a51-6e2b9c7d3f10", path: "~/.claude/projects/…", modified: iso(18) },
      };
    } else if (agent) {
      agent.session = String((job.spec as { session?: string }).session ?? "");
    }
  }
  machine.problems = problemsOf(machine);
}

function machineAgent(handle: string, room: string | null | undefined) {
  return machine.workspaces
    .flatMap((w) => w.agents)
    .find((a) => a.handle === handle && (!room || a.room === room));
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
  machine.problems = problemsOf(machine);
  return runners.map((r) => ({
    ...r,
    last_seen: new Date().toISOString(),
    ...(r.id === MOCK_RUNNER_ID ? { machine } : {}),
  }));
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
