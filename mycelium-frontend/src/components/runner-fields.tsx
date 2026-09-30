// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { Check, Download, Laptop, RefreshCw } from "lucide-react";
import { DMG_URL, useIsDesktop } from "@/lib/desktop";
import { useIsMac } from "@/lib/client-hooks";
import { rescanRunner, type Framework, type Runner } from "@/lib/api";
import {
  hostMissing,
  hostOf,
  jobSettled,
  sortFrameworks,
  useRunnerJob,
  useRunnersRevalidate,
} from "@/lib/runners";
import { addMachine } from "@/lib/my-machines";
import { CopyField } from "@/components/ui/copy-field";
import { Button } from "@/components/ui/button";

/** The one command that puts a machine on this page. */
export const CONNECT_COMMAND = "mycelium runner";

/**
 * What to do when none of your machines is connected: run one command, then
 * add the machine to this browser with the code it prints. Only machines
 * added here are listed, so nobody sees anyone else's (`my-machines.ts`).
 */
export function ConnectMachine({ compact = false }: { compact?: boolean }) {
  // In a browser on a Mac, the app is the short way: it connects this computer
  // itself, with herdr and the CLI inside. The command stays for everyone else.
  const mac = useIsMac();
  const desktop = useIsDesktop();
  const offerApp = mac && !desktop;
  return (
    <div className={`rounded-lg border border-dashed border-border ${compact ? "p-3" : "p-5"}`}>
      <div className="flex items-center gap-2">
        <Laptop className="size-4 text-muted-foreground" />
        <p className="text-label font-medium text-text">Connect this machine</p>
      </div>
      {offerApp && (
        <div className="mt-2 flex flex-wrap items-center gap-x-3 gap-y-1.5">
          <a
            href={DMG_URL}
            className="inline-flex h-7 items-center gap-1.5 rounded-md bg-accent px-2.5 text-label font-medium text-accent-fg transition-opacity hover:opacity-90"
          >
            <Download className="size-3.5" />
            Get Mycelium for Mac
          </a>
          <span className="text-micro text-muted-foreground">
            The app connects this computer for you. No terminal needed.
          </span>
        </div>
      )}
      <p className="mt-2 text-label leading-relaxed text-muted-foreground">
        {offerApp ? "Or run this in a terminal" : "Run this in a terminal"} on the computer your
        agents should run on, with herdr open. It looks for the agent CLIs you have installed and
        lets this page start them in herdr, where you can watch and type to them. It asks you
        there before it starts anything.
      </p>
      <CopyField value={CONNECT_COMMAND} className="mt-3 font-mono" />
      <AddMachineCode />
    </div>
  );
}

/** Add a machine to this browser by the code `mycelium runner` prints. */
export function AddMachineCode() {
  const [code, setCode] = useState("");
  return (
    <form
      className="mt-2 flex flex-wrap items-center gap-2"
      onSubmit={(e) => {
        e.preventDefault();
        addMachine(code);
        setCode("");
      }}
    >
      <label htmlFor="machine-code" className="text-micro text-muted-foreground">
        Then enter the code it prints:
      </label>
      <input
        id="machine-code"
        value={code}
        onChange={(e) => setCode(e.target.value)}
        placeholder="morgans-mbp-3f2a"
        spellCheck={false}
        autoComplete="off"
        className="h-7 min-w-0 flex-1 rounded bg-hairline px-2 font-mono text-micro text-text placeholder:text-faint focus:bg-bg focus:outline-none focus:ring-1 focus:ring-border"
      />
      <Button type="submit" variant="ghost" size="xs" disabled={!code.trim()}>
        Add
      </Button>
    </form>
  );
}

/** A machine whose host isn't running can start nothing; say so, and what to do. */
export function HostMissing({ runner }: { runner: Pick<Runner, "id" | "label" | "host"> }) {
  return (
    <p role="note" className="text-micro leading-relaxed text-yellow">
      {hostMissing(runner)}
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
 * be picked is shown; the rest of the scan (what isn't installed, or what the
 * machine's host can't start) is one line pointing at the Machines page, which
 * lists it all.
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
            ? `No agent CLI here that ${hostOf(runner).name} can start. Install one, then rescan.`
            : `Nothing can start here until ${hostOf(runner).name} is running.`}
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
        size={iconOnly ? "icon-sm" : "xs"}
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

