// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Runner server state: the machines that checked in with this hub, their
 * recent jobs, and one job followed while it runs.
 *
 * The same contract as `room-data.ts`: SWR hooks, one cache entry per
 * resource, no component-held polling. Runners are hub-wide rather than per
 * room, so their keys start with `"runners"` instead of `"room"`.
 */

import { useCallback, useMemo } from "react";
import useSWR, { useSWRConfig } from "swr";
import {
  fetchRunnerJob,
  fetchRunnerJobs,
  fetchRunners,
  type Framework,
  type Runner,
  type RunnerJob,
} from "@/lib/api";
import { useMyMachines } from "@/lib/my-machines";
import { usePrincipal } from "@/components/current-user";

/** How often the machine list is read: close to the runner's heartbeat. */
const RUNNERS_POLL = 5_000;
/** A job being followed moves in seconds; one that settled stops polling. */
const JOB_POLL = 1_000;
const JOBS_POLL = 5_000;

const NO_RUNNERS: Runner[] = [];
const NO_JOBS: RunnerJob[] = [];

export const RUNNERS_KEY = ["runners"] as const;

/** Whether `runner` is one of yours: added to this browser, or owned by who you say you are. */
export function isMine(runner: Runner, mine: string[], principal: string): boolean {
  return mine.includes(runner.id) || (!!principal && runner.owner?.toLowerCase() === principal);
}

/** Your machines: never anyone else's, even when the hub lists them (see `my-machines.ts`).
 *  `enabled: false` reads nothing, for a surface that needs them only sometimes. */
export function useRunners({ enabled = true }: { enabled?: boolean } = {}) {
  const { data, isLoading, mutate } = useSWR(enabled ? RUNNERS_KEY : null, fetchRunners, {
    refreshInterval: RUNNERS_POLL,
  });
  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);
  const mine = useMyMachines();
  const principal = usePrincipal();
  const runners = useMemo(
    () => (data ?? NO_RUNNERS).filter((r) => isMine(r, mine, principal)),
    [data, mine, principal],
  );
  const connected = useMemo(() => runners.filter((r) => r.connected), [runners]);
  return { runners, connected, loading: isLoading, refresh };
}

export function useRunnerJobs(runner: string | null) {
  const { data, isLoading, mutate } = useSWR(
    runner ? (["runners", runner, "jobs"] as const) : null,
    () => fetchRunnerJobs(runner!),
    { refreshInterval: JOBS_POLL },
  );
  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);
  return { jobs: data ?? NO_JOBS, loading: isLoading, refresh };
}

export function jobSettled(job: RunnerJob | null | undefined): boolean {
  return job?.status === "done" || job?.status === "failed";
}

/** Follow one job until it is done or has failed. */
export function useRunnerJob(runner: string | null, jobId: string | null) {
  const { data, error } = useSWR(
    runner && jobId ? (["runner-job", runner, jobId] as const) : null,
    () => fetchRunnerJob(runner!, jobId!),
    { refreshInterval: (job) => (jobSettled(job) ? 0 : JOB_POLL) },
  );
  return { job: data ?? null, error };
}

/** Refetch the machine list and every jobs list, e.g. after queuing a job. */
export function useRunnersRevalidate(): () => void {
  const { mutate } = useSWRConfig();
  return useCallback(() => {
    void mutate((key) => Array.isArray(key) && key[0] === "runners");
  }, [mutate]);
}

/** Frameworks as a picker lists them: startable first, then found, then missing. */
export function sortFrameworks(frameworks: Framework[]): Framework[] {
  const rank = (f: Framework) => (f.installed ? (f.launchable ? 0 : 1) : 2);
  return [...frameworks].sort((a, b) => rank(a) - rank(b) || a.name.localeCompare(b.name));
}

/** Frameworks a machine can start right now: installed, startable by its host,
 *  and its host running there. Empty on a machine whose host isn't running. */
export function launchable(runner: Runner): Framework[] {
  if (!runner.herdr) return [];
  return runner.frameworks.filter((f) => f.installed && f.launchable);
}

/**
 * What the app says about a runner's host: its name, where the agents it
 * starts show up, and what to do when it isn't running. Every screen asks
 * here rather than naming a host, so a new host is one entry.
 */
interface HostCopy {
  name: string;
  /** Where you watch and type to an agent it started. */
  where: string;
  /** The next step when it isn't running on a machine. */
  start: string;
}

const HOSTS: Record<string, HostCopy> = {
  herdr: {
    name: "herdr",
    where: "a herdr terminal",
    start: "Install it from https://herdr.dev and start it",
  },
  omnigent: {
    name: "Omnigent",
    where: "an Omnigent session",
    start: "Start it there with `omnigent start`",
  },
};

/** The host a runner starts agents on. A runner that doesn't say is herdr's. */
export function hostOf(runner: Pick<Runner, "host">): HostCopy {
  const id = runner.host || "herdr";
  return HOSTS[id] ?? { name: id, where: `${id}`, start: `Start ${id} there` };
}

/** Whether a runner starts agents in herdr, which is what a swarm needs. */
export function startsInHerdr(runner: Pick<Runner, "host">): boolean {
  return (runner.host || "herdr") === "herdr";
}

/** What a machine whose host isn't running is told. */
export function hostMissing(runner: Pick<Runner, "id" | "label" | "host">): string {
  const host = hostOf(runner);
  return `${host.name} isn't running on ${runnerName(runner)}. ${host.start}, then this machine can start agents.`;
}

/** A job said in a few words, for status lines. */
export function describeJob(job: RunnerJob): string {
  const spec = job.spec as Record<string, unknown>;
  const handle = typeof spec.handle === "string" ? `@${spec.handle}` : null;
  switch (job.kind) {
    case "launch":
      return `Start ${handle ?? "an agent"}`;
    case "stop":
      return `Stop ${handle ?? "an agent"}`;
    case "scan":
      return "Scan for agent CLIs";
    case "swarm":
      return typeof spec.room === "string" ? `Start a swarm in ${spec.room}` : "Start a swarm";
    case "restart": {
      if (spec.all) return "Restart every stopped agent";
      const agents = Array.isArray(spec.agents) ? (spec.agents as { handle?: string }[]) : [];
      return agents.length === 1 ? `Restart @${agents[0].handle}` : `Restart ${agents.length} agents`;
    }
    case "rename":
      return `Rename ${handle ?? "an agent"} to ${String(spec.name ?? "")}`;
    case "unbind":
      return spec.gone ? "Forget panes that are gone" : `Unbind ${handle ?? "an agent"}`;
    case "integrations":
      return "Install herdr's integrations";
  }
}

export const JOB_STATUS_LABEL: Record<RunnerJob["status"], string> = {
  queued: "Waiting for the machine",
  running: "Starting",
  waiting: "Waiting for a yes on the machine",
  done: "Done",
  failed: "Failed",
};

/** A runner's display name: its label, or its id when the label is empty. */
export function runnerName(runner: Pick<Runner, "id" | "label"> | undefined, id?: string | null) {
  return runner?.label || runner?.id || id || "a machine";
}
