// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState, useSyncExternalStore } from "react";
import { Terminal } from "lucide-react";
import { CopyAction } from "@/components/ui/copy-field";
import { useBackendHealth } from "@/lib/use-status";
import { useCurrentUser } from "@/components/current-user";
import { useNetworkStatus } from "@/lib/room-data";
import {
  DOCS_URL,
  PLATFORMS,
  detectPlatform,
  hubSetupCommand,
  hubSetupPrompt,
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

interface Props {
  className?: string;
}

/**
 * The guided client-only setup surface (`docs/agents.md` Steps 1 + 4): get
 * a coding agent or a terminal user: configure the CLI against this already
 * running hub, then verify it. It never offers to stand up another hub.
 *
 * The pill reflects whether this hub is answering right now. That's an
 * operator concern, not something the commands below can fix themselves:
 * they configure the viewer's own CLI, not this deployment.
 */
export function InstallPanel({ className }: Props) {
  const healthy = useBackendHealth(WAITING_POLL);
  const { network } = useNetworkStatus();
  const { principal } = useCurrentUser();

  // Server-rendered markup cannot know the OS or the page origin. Until the
  // client snapshot arrives, the prompt carries a placeholder host.
  const noSubscribe = () => () => {};
  const detectedPlatform = useSyncExternalStore(
    noSubscribe,
    () => detectPlatform(navigator.userAgent) as Platform,
    () => "unknown" as Platform,
  );
  const hubUrl = useSyncExternalStore(
    noSubscribe,
    () => window.location.origin,
    () => "<this-hub-url>",
  );
  const note = PLATFORMS.find(p => p.id === detectedPlatform)?.note;

  // This is a choice of recipient, not a platform picker: a running coding
  // agent gets a direct hub-aware handoff, while a human gets one terminal block.
  const [usePrompt, setUsePrompt] = useState(true);
  const setup = { hubUrl, authRequired: network?.auth?.enabled ?? null, principal };

  return (
    <section className={cn("rounded-xl border border-border bg-paper p-5", className)}>
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div className="flex min-w-0 items-start gap-3">
          <span className="flex size-9 flex-shrink-0 items-center justify-center rounded-lg bg-surface text-muted-foreground">
            <Terminal className="size-4" strokeWidth={1.75} />
          </span>
          <div className="min-w-0">
            <h2 className="text-ui font-medium text-text">Connect to this hub</h2>
            <p className="mt-0.5 text-label text-muted-foreground">
              This hub is already running. Hand the setup to your agent or run it yourself.
            </p>
          </div>
        </div>
        <ConnectionPill healthy={healthy} />
      </header>

      <div className="mt-4 flex items-center gap-1.5" role="group" aria-label="Setup method">
        <button
          type="button"
          aria-pressed={usePrompt}
          onClick={() => setUsePrompt(prev => !prev)}
          className={cn(
            "rounded-md border px-2.5 py-1 text-micro font-medium transition-colors",
            usePrompt
              ? "border-border2 bg-surface text-text"
              : "border-transparent text-muted-foreground hover:bg-hairline hover:text-text",
          )}
        >
          Coding agent
        </button>
        <button
          type="button"
          aria-pressed={!usePrompt}
          onClick={() => setUsePrompt(false)}
          className={cn(
            "rounded-md border px-2.5 py-1 text-micro font-medium transition-colors",
            !usePrompt
              ? "border-border2 bg-surface text-text"
              : "border-transparent text-muted-foreground hover:bg-hairline hover:text-text",
          )}
        >
          Terminal
        </button>
      </div>

      {usePrompt ? (
        <div className="mt-4">
          <p className="text-micro text-muted-foreground">
            Give this to the coding agent you already have open. It configures this hub directly.
          </p>
          <CopyAction value={hubSetupPrompt(setup)} label="Copy setup" className="mt-3" />
        </div>
      ) : (
        <>
          <div className="mt-4">
            <p className="text-micro text-muted-foreground">
              Install, connect, and verify in one paste.
            </p>
            <CopyAction value={hubSetupCommand(setup)} label="Copy setup" className="mt-3" />
          </div>

          {note && (
            <p className="mt-3 rounded-lg bg-surface px-3 py-2 text-micro text-muted-foreground">
              {note}
            </p>
          )}
        </>
      )}

      {!healthy && (
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
