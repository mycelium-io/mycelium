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
  LOGIN_COMMAND,
  NEXT_STEPS,
  PLATFORMS,
  PROMPT_COMMAND,
  configSetCommand,
  detectPlatform,
  type Platform,
} from "@/lib/install";
import { cn } from "@/lib/utils";

/** While the hub is down, the pill watches closer so it flips the moment it's
 *  back. Once connected, the default status-bar cadence is plenty. */
const WAITING_POLL = 4_000;

/** Live connection state, in the panel's own words. This hub either answers
 *  or it doesn't; there's no "not installed yet" state, since the page
 *  showing this panel is already being served by a hub. */
function ConnectionPill({ healthy }: { healthy: boolean | null }) {
  const state =
    healthy === null
      ? { label: "Checking this hub…", color: "var(--faint)", pulse: true }
      : healthy
        ? { label: "Hub reachable", color: "var(--green)", pulse: false }
        : { label: "Hub unreachable", color: "var(--yellow)", pulse: true };

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
  className?: string;
}

/**
 * The guided client-only setup surface (`docs/agents.md` Steps 1 + 4): get
 * the CLI, point it at this hub, and sign in if the hub asks for it. It never
 * offers to stand up a new hub, since this page is already served by one.
 *
 * The pill reflects whether this hub is answering right now. That's an
 * operator concern, not something the commands below can fix themselves:
 * they configure the viewer's own CLI, not this deployment.
 */
export function InstallPanel({ className }: Props) {
  const healthy = useBackendHealth(WAITING_POLL);

  // Server-rendered markup can't know the OS or this page's own origin, so
  // both land after mount to avoid a hydration mismatch. Until then, no
  // platform tab is preselected and the config command shows a placeholder
  // host. The origin is only a first guess, since some deployments front
  // the API on a different port than the UI, so it's there to edit.
  const [platform, setPlatform] = useState<Platform>("unknown");
  const [hubUrl, setHubUrl] = useState("<this-hub-url>");
  useEffect(() => {
    setPlatform(detectPlatform(navigator.userAgent));
    setHubUrl(window.location.origin);
  }, []);
  const note = PLATFORMS.find(p => p.id === platform)?.note;

  // "Prompt" is a fourth tab alongside the OS ones, not a fifth platform: it
  // swaps the manual steps for one line to hand a coding agent instead, same
  // as the landing page's prompt/curl toggle. Selected by default, same as
  // there. The detected OS tab stays highlighted underneath it (its own
  // independent toggle), so it's already right the moment you switch off Prompt.
  const [usePrompt, setUsePrompt] = useState(true);

  return (
    <section className={cn("rounded-xl border border-border bg-paper p-5", className)}>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex size-9 flex-shrink-0 items-center justify-center rounded-lg bg-surface text-muted-foreground">
            <Terminal className="size-4" strokeWidth={1.75} />
          </span>
          <div className="min-w-0">
            <h2 className="text-ui font-medium text-text">Connect your CLI to this hub</h2>
            <p className="mt-0.5 text-label text-muted-foreground">
              A few terminal commands to join the hub.
            </p>
          </div>
        </div>
        <ConnectionPill healthy={healthy} />
      </header>

      <div className="mt-4 flex items-center gap-1.5" role="group" aria-label="Install method">
        <button
          type="button"
          aria-pressed={usePrompt}
          onClick={() => setUsePrompt(true)}
          className={cn(
            "rounded-md border px-2.5 py-1 text-micro font-medium transition-colors",
            usePrompt
              ? "border-border2 bg-surface text-text"
              : "border-transparent text-muted-foreground hover:bg-hairline hover:text-text",
          )}
        >
          Prompt
        </button>
        {PLATFORMS.map(p => (
          <button
            key={p.id}
            type="button"
            aria-pressed={platform === p.id}
            onClick={() => {
              setUsePrompt(false);
              setPlatform(p.id);
            }}
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

      {usePrompt ? (
        <div className="mt-4">
          <p className="text-micro text-muted-foreground">
            Give this to a coding agent instead of a terminal. It reads{" "}
            <code className="font-mono">agents.md</code> and does the setup itself.
          </p>
          <CopyField value={PROMPT_COMMAND} className="mt-2" />
        </div>
      ) : (
        <>
          <ol className="mt-4 space-y-4">
            <Step n={1} title="Install the CLI">
              <p className="mt-0.5 text-micro text-muted-foreground">
                Drops the <code className="font-mono">mycelium</code> binary on your PATH.
              </p>
              <CopyField value={CLI_INSTALL_COMMAND} className="mt-2" />
            </Step>
            <Step n={2} title="Point it at this hub">
              <p className="mt-0.5 text-micro text-muted-foreground">This hub's address.</p>
              <CopyField value={configSetCommand(hubUrl)} className="mt-2" />
            </Step>
            <Step n={3} title="Sign in">
              <p className="mt-0.5 text-micro text-muted-foreground">
                Only needed if this hub requires it. The CLI will tell you if it doesn't.
              </p>
              <CopyField value={LOGIN_COMMAND} className="mt-2" />
            </Step>
          </ol>

          {note && (
            <p className="mt-3 rounded-lg bg-surface px-3 py-2 text-micro text-muted-foreground">
              {note}
            </p>
          )}
        </>
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
          The hub isn&apos;t answering right now, so the CLI may not be able to connect. Prefer
          the long version? Read the{" "}
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
