// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { ArrowRight, Terminal } from "lucide-react";
import { CopyField } from "@/components/ui/copy-field";
import { useBackendHealth } from "@/lib/use-status";
import {
  CLI_INSTALL_COMMAND,
  DOCS_URL,
  NEXT_STEPS,
  PLATFORMS,
  STACK_INSTALL_COMMAND,
  detectPlatform,
  type Platform,
} from "@/lib/install";
import { cn } from "@/lib/utils";

/** While there's no hub, the panel watches for one closely enough that it flips
 *  over on its own the moment `mycelium install` finishes. Once connected the
 *  default status-bar cadence is plenty. */
const WAITING_POLL = 4_000;

/** Live connection state, in the panel's own words. */
function ConnectionPill({ healthy }: { healthy: boolean | null }) {
  const state =
    healthy === null
      ? { label: "Checking for a hub…", color: "var(--faint)", pulse: true }
      : healthy
        ? { label: "Hub connected", color: "var(--green)", pulse: false }
        : { label: "No hub yet", color: "var(--yellow)", pulse: true };

  return (
    <span
      role="status"
      className="inline-flex items-center gap-2 rounded-full border border-border px-2.5 py-1 text-micro text-muted-foreground"
    >
      <span
        className={cn("inline-block size-1.5 rounded-full", state.pulse && "animate-pulse")}
        style={{ background: state.color }}
      />
      {state.label}
    </span>
  );
}

function Step({ n, title, children }: { n: number; title: string; children: React.ReactNode }) {
  return (
    <li className="flex gap-3">
      <span className="mt-0.5 flex size-6 flex-shrink-0 items-center justify-center rounded-md bg-surface font-mono text-micro font-semibold text-muted-foreground">
        {n}
      </span>
      <div className="min-w-0 flex-1">
        <div className="text-label font-medium text-text">{title}</div>
        {children}
      </div>
    </li>
  );
}

interface Props {
  /** `page` fills a route; `inline` sits inside the dashboard's content column. */
  variant?: "page" | "inline";
  className?: string;
}

/**
 * The guided install surface: the two commands to paste, live detection of the
 * hub coming up, and what to do once it has.
 *
 * The browser can't run the install, so "is the CLI installed" is inferred from
 * the backend answering — a healthy hub means `mycelium install` ran. That's the
 * honest limit of this flow, and the panel says so rather than pretending to
 * inspect the machine.
 */
export function InstallPanel({ variant = "inline", className }: Props) {
  const healthy = useBackendHealth(WAITING_POLL);

  // Server-rendered markup can't know the OS, so the detected platform lands
  // after mount; until then no tab is preselected and the commands (identical
  // on macOS and Linux) read the same either way.
  const [platform, setPlatform] = useState<Platform>("unknown");
  useEffect(() => {
    setPlatform(detectPlatform(navigator.userAgent));
  }, []);
  const note = PLATFORMS.find(p => p.id === platform)?.note;

  return (
    <section
      className={cn(
        "rounded-xl border border-border bg-paper",
        variant === "page" ? "p-6" : "p-5",
        className,
      )}
    >
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex size-9 flex-shrink-0 items-center justify-center rounded-lg bg-surface text-muted-foreground">
            <Terminal className="size-4" strokeWidth={1.75} />
          </span>
          <div className="min-w-0">
            <h2 className="text-ui font-medium text-text">Get the CLI</h2>
            <p className="mt-0.5 text-label text-muted-foreground">
              Two commands in a terminal. This page notices the moment your hub comes up.
            </p>
          </div>
        </div>
        <ConnectionPill healthy={healthy} />
      </header>

      <div className="mt-4 flex items-center gap-1.5" role="group" aria-label="Platform">
        {PLATFORMS.map(p => (
          <button
            key={p.id}
            type="button"
            aria-pressed={platform === p.id}
            onClick={() => setPlatform(p.id)}
            className={cn(
              "rounded-md border px-2.5 py-1 text-micro font-medium transition-colors",
              platform === p.id
                ? "border-border2 bg-surface text-text"
                : "border-transparent text-muted-foreground hover:bg-hairline hover:text-text",
            )}
          >
            {p.label}
          </button>
        ))}
      </div>

      <ol className="mt-4 space-y-4">
        <Step n={1} title="Install the CLI">
          <p className="mt-0.5 text-micro text-muted-foreground">
            Drops the <code className="font-mono">mycelium</code> binary on your PATH.
          </p>
          <CopyField value={CLI_INSTALL_COMMAND} className="mt-2" />
        </Step>
        <Step n={2} title="Bring up the stack">
          <p className="mt-0.5 text-micro text-muted-foreground">
            Pulls the images, asks for your LLM key, and writes{" "}
            <code className="font-mono">~/.mycelium/config.toml</code>.
          </p>
          <CopyField value={STACK_INSTALL_COMMAND} className="mt-2" />
        </Step>
      </ol>

      {note && (
        <p className="mt-3 rounded-lg bg-surface px-3 py-2 text-micro text-muted-foreground">{note}</p>
      )}

      {healthy ? (
        <div className="mt-5 border-t border-border pt-4">
          <div className="text-label font-medium text-text">Next: your first room</div>
          <ol className="mt-3 space-y-3">
            {NEXT_STEPS.map(step => (
              <li key={step.title}>
                <div className="flex flex-wrap items-baseline gap-x-2">
                  <span className="text-label text-text">{step.title}</span>
                  <a
                    href={step.href}
                    target="_blank"
                    rel="noreferrer"
                    className="text-micro text-accent hover:underline"
                  >
                    docs
                  </a>
                </div>
                <p className="text-micro text-muted-foreground">{step.body}</p>
                <CopyField value={step.command} className="mt-1.5" />
              </li>
            ))}
          </ol>
          <Link
            href="/"
            className="mt-4 inline-flex items-center gap-1.5 text-label font-medium text-accent hover:underline"
          >
            Open the command center
            <ArrowRight className="size-3.5" />
          </Link>
        </div>
      ) : (
        <p className="mt-5 border-t border-border pt-4 text-micro text-muted-foreground">
          The browser can&apos;t run the install for you, so this is a guided flow: it watches for the
          hub answering rather than inspecting your machine. Prefer the long version? Read the{" "}
          <a
            href={`${DOCS_URL}/index.html#quickstart`}
            target="_blank"
            rel="noreferrer"
            className="text-accent hover:underline"
          >
            quickstart
          </a>
          .
        </p>
      )}
    </section>
  );
}
