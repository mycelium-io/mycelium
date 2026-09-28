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

/** How often the machine list is read: close to the runner's heartbeat. */
const RUNNERS_POLL = 5_000;
/** A job being followed moves in seconds; one that settled stops polling. */
const JOB_POLL = 1_000;
const JOBS_POLL = 5_000;

const NO_RUNNERS: Runner[] = [];
const NO_JOBS: RunnerJob[] = [];

export const RUNNERS_KEY = ["runners"] as const;

export function useRunners() {
  const { data, isLoading, mutate } = useSWR(RUNNERS_KEY, fetchRunners, {
    refreshInterval: RUNNERS_POLL,
  });
  const refresh = useCallback(() => {
    void mutate();
  }, [mutate]);
  const runners = data ?? NO_RUNNERS;
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

/** Frameworks a machine can start right now: installed, startable by herdr,
 *  and herdr running there. Empty on a machine without herdr. */
export function launchable(runner: Runner): Framework[] {
  if (!runner.herdr) return [];
  return runner.frameworks.filter((f) => f.installed && f.launchable);
}

/** What a machine without herdr is told. herdr is the only way it starts agents. */
export function herdrMissing(runner: Pick<Runner, "id" | "label">): string {
  return `herdr isn't running on ${runnerName(runner)}. Install it from https://herdr.dev and start it, then this machine can start agents.`;
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
  }
}

export const JOB_STATUS_LABEL: Record<RunnerJob["status"], string> = {
  queued: "Waiting for the machine",
  running: "Starting",
  done: "Done",
  failed: "Failed",
};

/** A runner's display name: its label, or its id when the label is empty. */
export function runnerName(runner: Pick<Runner, "id" | "label"> | undefined, id?: string | null) {
  return runner?.label || runner?.id || id || "a machine";
}
