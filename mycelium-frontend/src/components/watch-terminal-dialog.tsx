// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState } from "react";
import {
  ApiError,
  closeWatch,
  fetchRunnerJob,
  readWatch,
  watchRunnerAgent,
  type TerminalScreen,
  type WatchStarted,
} from "@/lib/api";
import { parseAnsi, type AnsiStyle } from "@/lib/ansi";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";

/** The agent whose terminal is watched, and the machine it runs on. */
export interface WatchTarget {
  room: string;
  handle: string;
  runner: { id: string; name: string };
}

interface Props {
  target: WatchTarget | null;
  onClose: () => void;
}

/**
 * An agent's terminal, live and read-only. Opening it asks the agent's machine,
 * which asks the person there; nothing is shown until they say yes. Closing it
 * tells the machine to stop sending.
 */
export function WatchTerminalDialog({ target, onClose }: Props) {
  return (
    <Dialog
      open={target !== null}
      onOpenChange={(next) => {
        if (!next) onClose();
      }}
    >
      <DialogContent className="grid-cols-1 sm:max-w-5xl [&>*]:min-w-0">
        {/* Mounted per opening: each one is its own watch, asked for again. */}
        {target && <Watching key={`${target.runner.id}/${target.room}/${target.handle}`} target={target} />}
      </DialogContent>
    </Dialog>
  );
}

type Phase =
  | { kind: "asking" }
  | { kind: "waiting" }
  | { kind: "live" }
  | { kind: "ended"; why: string };

/** Watch one terminal until the dialog closes or the watch ends. */
export function Watching({ target }: { target: WatchTarget }) {
  const { room, handle, runner } = target;
  const [phase, setPhase] = useState<Phase>({ kind: "asking" });
  const [screen, setScreen] = useState<TerminalScreen | null>(null);

  useEffect(() => {
    const abort = new AbortController();
    let watching: WatchStarted | null = null;
    const over = (why: string) => {
      if (!abort.signal.aborted) setPhase({ kind: "ended", why });
    };
    const pause = (ms: number) => new Promise((r) => setTimeout(r, ms));

    // Whether the machine has answered: the job waits while it asks.
    const followJob = async (id: string) => {
      while (!abort.signal.aborted) {
        const job = await fetchRunnerJob(runner.id, id).catch(() => null);
        if (job?.status === "failed") return over(job.error ?? `${runner.name} didn't share it.`);
        if (job?.status === "done") return;
        if (job?.status === "waiting") setPhase((p) => (p.kind === "asking" ? { kind: "waiting" } : p));
        await pause(1000);
      }
    };

    // Each newer screen, held by the hub until one comes.
    const followScreens = async (watch: WatchStarted) => {
      let after = 0;
      while (!abort.signal.aborted) {
        try {
          const read = await readWatch(runner.id, watch, after, abort.signal);
          if (read.screen) {
            after = read.screen.seq;
            setScreen(read.screen);
            setPhase((p) => (p.kind === "ended" ? p : { kind: "live" }));
          }
          if (read.ended) return over(read.ended);
        } catch (err) {
          if (abort.signal.aborted) return;
          if (err instanceof ApiError && err.status === 404) return over("The watch is gone.");
          await pause(2000);
        }
      }
    };

    // A tick later, so a mount that is undone at once (React's dev double run)
    // never puts a question on the machine.
    const start = setTimeout(() => {
      void (async () => {
        try {
          const started = await watchRunnerAgent(runner.id, room, handle);
          watching = started;
          if (abort.signal.aborted) {
            void closeWatch(runner.id, started).catch(() => {});
            return;
          }
          void followJob(started.job.id);
          void followScreens(started);
        } catch (err) {
          over(err instanceof Error ? err.message : "Couldn't ask to watch it.");
        }
      })();
    }, 0);

    return () => {
      clearTimeout(start);
      abort.abort();
      if (watching) void closeWatch(runner.id, watching).catch(() => {});
    };
  }, [room, handle, runner.id, runner.name]);

  return (
    <>
      <DialogHeader>
        <DialogTitle>@{handle}&rsquo;s terminal</DialogTitle>
        <DialogDescription>
          {phase.kind === "asking" && `Asking ${runner.name}…`}
          {phase.kind === "waiting" &&
            `Waiting for a yes on ${runner.name}. Its terminal is only shared once someone there agrees.`}
          {phase.kind === "live" && `Live from ${runner.name}, in ${room}. Read-only: nothing typed here reaches it.`}
          {phase.kind === "ended" && phase.why}
        </DialogDescription>
      </DialogHeader>
      <ScreenView screen={screen} />
    </>
  );
}

function css(style: AnsiStyle): React.CSSProperties {
  const fg = style.inverse ? (style.bg ?? "var(--bg)") : style.fg;
  const bg = style.inverse ? (style.fg ?? "var(--text)") : style.bg;
  return {
    color: fg,
    backgroundColor: bg,
    fontWeight: style.bold ? 600 : undefined,
    opacity: style.dim ? 0.6 : undefined,
    fontStyle: style.italic ? "italic" : undefined,
    textDecoration: style.underline ? "underline" : undefined,
  };
}

function ScreenView({ screen }: { screen: TerminalScreen | null }) {
  const lines = useMemo(() => (screen ? parseAnsi(screen.text) : []), [screen]);
  return (
    <div
      role="log"
      aria-label="Terminal"
      aria-live="off"
      className="h-[60vh] overflow-auto rounded-lg border border-border bg-[#0b0f14] p-3 font-mono text-[12px] leading-[1.35] text-[#d6dde6]"
    >
      {!screen && <p className="text-faint">Nothing to show yet.</p>}
      <pre className="m-0 whitespace-pre">
        {lines.map((runs, i) => (
          <div key={i}>
            {runs.length === 0
              ? " "
              : runs.map((run, j) => (
                  <span key={j} style={css(run.style)}>
                    {run.text}
                  </span>
                ))}
          </div>
        ))}
      </pre>
    </div>
  );
}
