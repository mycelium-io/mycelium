// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * An agent's terminal as it is right now, read-only, wherever people look at
 * the agent: the Members rail, its row on Machines, and the channel while it
 * works. The desktop app reads it from herdr on this machine and hands it to
 * this page; nothing about it goes to the hub, and the footer says so.
 * Typing stays in the app's agents terminal (Open its terminal).
 *
 *   <AgentScreen room handle />        the view, or where the agent runs instead
 *   <AgentScreenDrawer … />            the same, in a drawer
 */

import { useEffect, useMemo, useState, type CSSProperties } from "react";
import { SquareTerminal } from "lucide-react";
import { parseAnsi, type AnsiStyle } from "@/lib/ansi";
import { placeOf } from "@/lib/agent-place";
import { terminalLink, useAgentScreen, useIsDesktop, useThisMachine } from "@/lib/desktop";
import { runnerName, useRunners } from "@/lib/runners";
import { buttonVariants } from "@/components/ui/button";
import { DetailDrawer } from "@/components/detail-drawer";

/** The footer's promise, which the code keeps: the runner sends the hub no screen. */
export const STREAMED_LOCALLY = "Streamed from this machine. Nothing is sent to the hub.";

interface Props {
  room: string;
  handle: string;
  /** The machine its manifest names, when the caller knows it. */
  runner?: string | null;
}

export function AgentScreen({ room, handle, runner: runnerOf }: Props) {
  const desktop = useIsDesktop();
  const thisMachine = useThisMachine();
  const { runners } = useRunners();
  // The app is asked first: whether the agent has a terminal here is its
  // answer, from its own registry of agents, not a guess from the hub's list.
  const screen = useAgentScreen(desktop ? { room, handle } : null);

  if (!desktop) {
    return <Note>An agent&apos;s terminal shows in the desktop app, for agents on that computer.</Note>;
  }
  if (screen.unasked) {
    // In the app, but showing a hub elsewhere (client mode), whose pages can't
    // ask the app for anything. The agents terminal still opens from the app.
    return (
      <Note>
        {`Terminals show here when this app runs your hub, not yet when it's connected to one elsewhere. ` +
          `To see @${handle}, open the agents terminal from the bar at the bottom.`}
      </Note>
    );
  }
  if (screen.notHere) {
    // Not on this machine: say where it runs, from what the hub knows.
    const place = placeOf(runners, thisMachine, room, handle, runnerOf);
    if (place.kind === "yours") {
      return (
        <Note>
          @{handle} runs on {runnerName(place.runner)}. Its terminal shows in the desktop app there, never through the
          hub.
        </Note>
      );
    }
    if (place.kind === "theirs") {
      return <Note>@{handle} runs on someone else&apos;s machine. Its terminal is theirs, and shows only there.</Note>;
    }
    return (
      <Note>
        @{handle} isn&apos;t running in a terminal Mycelium can see on this machine. An agent started from Members → Add
        runs in one.
      </Note>
    );
  }
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <Screen text={screen.text} error={screen.error} />
      <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-4 py-2 text-micro text-muted-foreground">
        <span>{STREAMED_LOCALLY}</span>
        <Updated at={screen.at} />
        <a
          href={terminalLink(screen.pane ?? undefined)}
          className={buttonVariants({
            variant: "secondary",
            size: "sm",
            className: "ml-auto",
          })}
        >
          <SquareTerminal className="size-3.5" />
          Open its terminal
        </a>
      </footer>
    </div>
  );
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-3 text-label text-muted-foreground">{children}</p>;
}

function Screen({ text, error }: { text: string | null; error: string | null }) {
  const lines = useMemo(() => (text ? parseAnsi(text) : []), [text]);
  if (error && text === null) return <Note>{error}</Note>;
  if (text === null) return <Note>Reading its terminal…</Note>;
  return (
    <pre
      aria-label="Its terminal"
      className="min-h-0 flex-1 overflow-auto bg-bg px-3 py-2 font-mono text-micro leading-snug text-text"
    >
      {lines.map((runs, i) => (
        <div key={i} className="min-h-[1lh] whitespace-pre">
          {runs.map((r, j) => (
            <span key={j} style={cssOf(r.style)}>
              {r.text}
            </span>
          ))}
        </div>
      ))}
    </pre>
  );
}

function cssOf(s: AnsiStyle): CSSProperties | undefined {
  const fg = s.inverse ? (s.bg ?? "var(--bg)") : s.fg;
  const bg = s.inverse ? (s.fg ?? "var(--text)") : s.bg;
  const css: CSSProperties = {};
  if (fg) css.color = fg;
  if (bg) css.backgroundColor = bg;
  if (s.bold) css.fontWeight = 600;
  if (s.dim) css.opacity = 0.6;
  if (s.italic) css.fontStyle = "italic";
  if (s.underline) css.textDecoration = "underline";
  return Object.keys(css).length ? css : undefined;
}

/** "updated 2s ago", kept current between reads. */
function Updated({ at }: { at: number | null }) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const t = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(t);
  }, []);
  if (at === null) return null;
  const s = Math.max(0, Math.round((now - at) / 1000));
  return <span className="text-faint">{s <= 1 ? "live" : `updated ${s}s ago`}</span>;
}

export function AgentScreenDrawer({ open, onClose, ...props }: Props & { open: boolean; onClose: () => void }) {
  return (
    <DetailDrawer
      open={open}
      onClose={onClose}
      wide
      title={`@${props.handle}`}
      subtitle={`Its terminal, in ${props.room}`}
    >
      <div className="flex h-full flex-col">
        <AgentScreen {...props} />
      </div>
    </DetailDrawer>
  );
}
