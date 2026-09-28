// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Laptop, RefreshCw } from "lucide-react";
import { rescanRunner, type Framework, type Runner } from "@/lib/api";
import {
  herdrMissing,
  jobSettled,
  sortFrameworks,
  useRunnerJob,
  useRunnersRevalidate,
} from "@/lib/runners";
import { CopyField } from "@/components/ui/copy-field";
import { Button } from "@/components/ui/button";

/** The one command that puts a machine on this page. */
export const CONNECT_COMMAND = "mycelium runner";

/**
 * What to do when no machine is connected: run one command. The page follows
 * the runner list, so it moves on by itself once the machine checks in.
 */
export function ConnectMachine({ compact = false }: { compact?: boolean }) {
  return (
    <div className={`rounded-lg border border-dashed border-border ${compact ? "p-3" : "p-5"}`}>
      <div className="flex items-center gap-2">
        <Laptop className="size-4 text-muted-foreground" />
        <p className="text-label font-medium text-text">Connect this machine</p>
      </div>
      <p className="mt-1.5 text-label leading-relaxed text-muted-foreground">
        Run this in a terminal on the computer your agents should run on, with herdr open. It
        looks for the agent CLIs you have installed and lets this page start them in herdr, where
        you can watch and type to them. This page updates once it connects.
      </p>
      <CopyField value={CONNECT_COMMAND} className="mt-3 font-mono" />
    </div>
  );
}

/** A machine without herdr can start nothing; say so, and where to get it. */
export function HerdrMissing({ runner }: { runner: Pick<Runner, "id" | "label"> }) {
  return (
    <p role="note" className="rounded-lg border border-border bg-bg px-3 py-2 text-label leading-relaxed text-muted-foreground">
      {herdrMissing(runner)}
    </p>
  );
}

/** Pick one of the connected machines. Hidden when there is only one. */
export function MachinePicker({
  runners,
  value,
  onChange,
  label = "Machine",
}: {
  runners: Runner[];
  value: string | null;
  onChange: (id: string) => void;
  label?: string;
}) {
  if (runners.length < 2) return null;
  return (
    <div className="space-y-1.5">
      <label htmlFor="runner-machine" className="block text-micro font-medium text-muted-foreground">
        {label}
      </label>
      <select
        id="runner-machine"
        value={value ?? ""}
        onChange={(e) => onChange(e.target.value)}
        className="w-full rounded-lg border border-border bg-bg px-3 py-2 text-label text-text outline-none hover:border-border2 focus:border-accent"
      >
        {runners.map((r) => (
          <option key={r.id} value={r.id}>
            {r.label || r.id}
          </option>
        ))}
      </select>
    </div>
  );
}

/**
 * The agent CLIs this machine can start, as one row of choices. Only what can
 * be picked is shown; the rest of the scan (what isn't installed, or what herdr
 * can't start) is one line pointing at the Machines page, which lists it all.
 */
export function FrameworkPicker({
  runner,
  value,
  onChange,
  usable = (f) => runner.herdr && f.installed && f.launchable,
}: {
  runner: Runner;
  value: string | null;
  onChange: (id: string) => void;
  usable?: (f: Framework) => boolean;
}) {
  const frameworks = sortFrameworks(runner.frameworks);
  const choices = frameworks.filter(usable);
  const blocked = frameworks.filter((f) => f.installed && !usable(f));
  return (
    <div className="space-y-1.5">
      <div className="flex items-center gap-2">
        <span id="runner-framework-label" className="text-micro font-medium text-muted-foreground">
          Agent CLI
        </span>
        <RescanButton runner={runner} className="ml-auto" />
      </div>
      {choices.length === 0 ? (
        <p className="text-label text-muted-foreground">
          {runner.herdr
            ? "No agent CLI here that herdr can start. Install one, then rescan."
            : "Nothing can start here until herdr is running."}
        </p>
      ) : (
        <div role="radiogroup" aria-labelledby="runner-framework-label" className="flex flex-wrap gap-1.5">
          {choices.map((f) => {
            const picked = value === f.id;
            const version = shortVersion(f.version);
            return (
              <button
                key={f.id}
                type="button"
                role="radio"
                aria-checked={picked}
                aria-label={f.name}
                title={f.path ?? undefined}
                onClick={() => onChange(f.id)}
                className={`flex items-center gap-1.5 rounded-md border px-2.5 py-1 text-label transition-colors ${
                  picked
                    ? "border-accent bg-accent/10 text-text"
                    : "border-border text-muted-foreground hover:border-border2 hover:text-text"
                }`}
              >
                {picked && <Check className="size-3 text-accent" />}
                <span className="font-medium">{f.name}</span>
                {version && <span className="font-mono text-micro text-faint">{version}</span>}
              </button>
            );
          })}
        </div>
      )}
      {blocked.length > 0 && (
        <p className="text-micro text-muted-foreground">
          Also installed, can&apos;t start here: {blocked.map((f) => f.name).join(", ")}.{" "}
          <Link href="/machines" className="text-accent hover:underline">
            See why
          </Link>
        </p>
      )}
    </div>
  );
}

/** "2.1.280 (Claude Code)" or "codex-cli 0.9.1" read as just the version number. */
export function shortVersion(version: string | null | undefined): string | null {
  if (!version) return null;
  return version.match(/\d+(?:\.\d+)+/)?.[0] ?? version.slice(0, 12);
}

/** Ask the machine to scan again, and say so while it does. */
export function RescanButton({
  runner,
  className,
  iconOnly = false,
}: {
  runner: Runner;
  className?: string;
  /** Just the icon, named for screen readers and on hover. */
  iconOnly?: boolean;
}) {
  const [jobId, setJobId] = useState<string | null>(null);
  const [queueError, setError] = useState<string | null>(null);
  const revalidate = useRunnersRevalidate();
  const { job } = useRunnerJob(runner.id, jobId);
  const running = jobId !== null && !jobSettled(job);
  const error = queueError ?? (job?.status === "failed" ? (job.error ?? "The scan failed") : null);

  // A finished scan changed the machine's framework list: read it again.
  const settled = jobSettled(job);
  useEffect(() => {
    if (settled) revalidate();
  }, [settled, revalidate]);

  const scan = async () => {
    setError(null);
    try {
      const queued = await rescanRunner(runner.id);
      setJobId(queued.id);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not ask the machine to scan");
    }
  };

  return (
    <span className={`flex items-center gap-2 ${className ?? ""}`}>
      {error && <span className="text-micro text-red">{error}</span>}
      <Button
        type="button"
        variant="ghost"
        size={iconOnly ? "icon-sm" : "sm"}
        onClick={scan}
        disabled={running || !runner.connected}
        aria-label={iconOnly ? (running ? "Scanning for agent CLIs" : "Rescan for agent CLIs") : undefined}
        title={iconOnly ? "Rescan for agent CLIs" : undefined}
      >
        <RefreshCw className={`size-3 ${running ? "animate-spin" : ""}`} />
        {!iconOnly && (running ? "Scanning…" : "Rescan")}
      </Button>
    </span>
  );
}

/** Where on the machine the agent works: one of its allowed folders, or a path inside one. */
export function FolderField({
  runner,
  value,
  onChange,
  id = "runner-folder",
}: {
  runner: Runner;
  value: string;
  onChange: (path: string) => void;
  id?: string;
}) {
  const listId = `${id}-roots`;
  return (
    <div className="space-y-1.5">
      <label htmlFor={id} className="block text-micro font-medium text-muted-foreground">
        Folder{" "}
        {runner.roots.length > 0 && (
          <span className="font-normal text-faint">inside {runner.roots.join(" or ")}</span>
        )}
      </label>
      <input
        id={id}
        list={listId}
        value={value}
        onChange={(e) => onChange(e.target.value)}
        spellCheck={false}
        placeholder={runner.roots[0] ?? "/path/to/project"}
        className="w-full rounded-lg border border-border bg-bg px-3 py-2 font-mono text-label text-text outline-none transition-colors placeholder:text-muted-foreground hover:border-border2 focus:border-accent"
      />
      <datalist id={listId}>
        {runner.roots.map((r) => (
          <option key={r} value={r} />
        ))}
      </datalist>
      {runner.roots.length === 0 && (
        <p className="text-micro leading-snug text-muted-foreground">
          This machine allows no folders yet. Start the runner with --root &lt;folder&gt;.
        </p>
      )}
    </div>
  );
}

