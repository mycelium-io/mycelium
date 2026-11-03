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
 *
 * `AgentScreenWindow` (agent-screen-window.tsx) is where it's opened.
 */

import { useEffect, useLayoutEffect, useMemo, useRef, useState, type CSSProperties } from "react";
import { Lock, SquareTerminal } from "lucide-react";
import { parseAnsi, readable, type AnsiStyle } from "@/lib/ansi";
import { placeOf } from "@/lib/agent-place";
import { terminalLink, useAgentScreen, useIsDesktop, useThisMachine } from "@/lib/desktop";
import { runnerName, useRunners } from "@/lib/runners";
import type { Runner } from "@/lib/api";
import { useAgentSession } from "@/lib/agent-session";
import { AgentSessionView, SessionUnavailable } from "@/components/agent-session-view";
import { buttonVariants } from "@/components/ui/button";

/** The footer's promise, which the code keeps: the runner sends the hub no screen. */
export const STREAMED_LOCALLY = "Streamed from this machine. Nothing is sent to the hub.";

export interface AgentScreenProps {
  room: string;
  handle: string;
  /** The machine its manifest names, when the caller knows it. */
  runner?: string | null;
  /** Whether the footer offers Open its terminal. Off where the caller puts
   *  that button somewhere more prominent of its own. */
  openLink?: boolean;
  /** Its session drawn as what it did, when its CLI has a converter, or its
   *  terminal. The terminal when unset. */
  view?: ScreenView;
  /** Asked to switch, from inside the rendered view. */
  onView?: (view: ScreenView) => void;
}

export type ScreenView = "rendered" | "terminal";

export function AgentScreen({
  room,
  handle,
  runner: runnerOf,
  openLink = true,
  view = "terminal",
  onView,
}: AgentScreenProps) {
  const desktop = useIsDesktop();
  const thisMachine = useThisMachine();
  const { runners } = useRunners();
  // The app is asked first: whether the agent has a terminal here is its
  // answer, from its own registry of agents, not a guess from the hub's list.
  const screen = useAgentScreen(desktop ? { room, handle } : null);
  const read = useAgentSession(desktop && view === "rendered" ? { room, handle } : null);
  const showTerminal = () => onView?.("terminal");

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
      {view === "rendered" && read.session ? (
        <AgentSessionView session={read.session} onShowTerminal={showTerminal} />
      ) : view === "rendered" && read.unavailable ? (
        <SessionUnavailable
          reason={read.unavailable}
          cli={cliOf(runners, room, handle, runnerOf)}
          onShowTerminal={showTerminal}
        />
      ) : (
        <Screen text={screen.text} error={screen.error} />
      )}
      {/* One quiet line, padded like the header: where the screen comes from,
          how fresh it is, and the way to type to it. */}
      <footer className="flex flex-wrap items-center gap-x-3 gap-y-1 border-t border-border px-5 py-2 text-micro text-faint">
        <Lock className="size-3 shrink-0" strokeWidth={2} aria-hidden />
        <span>{STREAMED_LOCALLY}</span>
        <Updated at={screen.at} />
        {openLink && (
          <a
            href={terminalLink(screen.pane ?? undefined)}
            className={buttonVariants({ variant: "ghost", size: "xs", className: "-mr-2 ml-auto" })}
          >
            <SquareTerminal className="size-3.5" />
            Open its terminal
          </a>
        )}
      </footer>
    </div>
  );
}

/** The name of the agent CLI @`handle` runs, from the machine that runs it. */
function cliOf(runners: Runner[], room: string, handle: string, runnerId?: string | null): string | null {
  for (const r of runners) {
    if (runnerId && r.id !== runnerId) continue;
    const agent = r.agents.find((a) => a.room === room && a.handle === handle);
    if (agent) return r.frameworks.find((f) => f.id === agent.framework)?.name ?? agent.framework;
  }
  return null;
}

function Note({ children }: { children: React.ReactNode }) {
  return <p className="px-4 py-3 text-label text-muted-foreground">{children}</p>;
}

/** How close to the bottom, in pixels, still counts as following the terminal. */
const FOLLOW_SLACK_PX = 24;

function Screen({ text, error }: { text: string | null; error: string | null }) {
  const lines = useMemo(() => (text ? parseAnsi(text) : []), [text]);
  // It reads the scrollback too, so it opens at the bottom, where the terminal
  // is now, and stays there as lines arrive. Scrolled up, it holds what was
  // on it then: the read is a rolling window, so new lines would push what's
  // being read up and off; back at the bottom, it follows again.
  const ref = useRef<HTMLPreElement | null>(null);
  const [held, setHeld] = useState<typeof lines | null>(null);
  const shown = held ?? lines;
  const surface = useSurface(ref, text !== null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (el && !held) el.scrollTop = el.scrollHeight;
  }, [lines, held]);
  if (error && text === null) return <Note>{error}</Note>;
  if (text === null) return <Note>Reading its terminal…</Note>;
  return (
    <pre
      ref={ref}
      onScroll={(e) => {
        const el = e.currentTarget;
        const atBottom = el.scrollHeight - el.scrollTop - el.clientHeight <= FOLLOW_SLACK_PX;
        if (atBottom) setHeld(null);
        else if (!held) setHeld(lines);
      }}
      aria-label="Its terminal"
      className="min-h-0 flex-1 overflow-auto bg-bg px-3 py-2 font-mono text-micro leading-snug text-text"
    >
      {shown.map((runs, i) => (
        <div key={i} className="min-h-[1lh] whitespace-pre">
          {runs.map((r, j) => (
            <span key={j} style={cssOf(r.style, surface)}>
              {r.text}
            </span>
          ))}
        </div>
      ))}
    </pre>
  );
}

/** How many of a screen's last lines a member's card shows. */
const CARD_LINES = 5;

/**
 * The last few lines of an agent's terminal, live, for its card: the same
 * local read the drawer makes, while the card is up. Nothing at all where the
 * drawer would show a note instead (outside the app, or an agent that doesn't
 * run on this machine), so someone else's agent never shows a screen. A click
 * opens the drawer.
 */
export function ScreenLines({ room, handle, onOpen }: { room: string; handle: string; onOpen?: () => void }) {
  const desktop = useIsDesktop();
  const screen = useAgentScreen(desktop ? { room, handle } : null);
  const lines = useMemo(() => {
    const all = screen.text ? parseAnsi(screen.text) : [];
    const used = all.filter((runs) => runs.some((r) => r.text.trim()));
    return used.slice(-CARD_LINES);
  }, [screen.text]);
  const shows = desktop && !screen.unasked && !screen.notHere && lines.length > 0;
  const box = useRef<HTMLButtonElement | null>(null);
  const surface = useSurface(box, shows);
  if (!shows) return null;
  return (
    <button
      ref={box}
      type="button"
      onClick={onOpen}
      aria-label={`Open @${handle}'s terminal`}
      data-testid="agent-card-screen"
      className="block w-full overflow-hidden rounded-md border border-border bg-bg px-2.5 py-2 text-left font-mono text-[11px] leading-[1.45] text-text transition-colors hover:border-border2"
    >
      {lines.map((runs, i) => (
        <span key={i} className="block truncate whitespace-pre">
          {runs.map((r, j) => (
            <span key={j} style={cssOf(r.style, surface)}>
              {r.text}
            </span>
          ))}
        </span>
      ))}
    </button>
  );
}

/** The colors a terminal view is drawn in, as the page has them now. */
interface Surface {
  fg: string;
  bg: string;
}

const THEME_SURFACE: Surface = { fg: "var(--text)", bg: "var(--bg)" };

/** `ref`'s own text and background colors, read from the page once it's
 *  `drawn` and again when the theme changes; the theme's names for them
 *  until then. */
function useSurface(ref: React.RefObject<HTMLElement | null>, drawn: boolean): Surface {
  const [surface, setSurface] = useState<Surface>(THEME_SURFACE);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !drawn) return;
    const read = () => {
      const style = getComputedStyle(el);
      const next = { fg: style.color, bg: style.backgroundColor };
      if (!next.fg || !next.bg) return;
      setSurface((prev) => (prev.fg === next.fg && prev.bg === next.bg ? prev : next));
    };
    read();
    // A theme is set on the page's root, or follows the system's.
    const root = new MutationObserver(read);
    root.observe(document.documentElement, { attributes: true });
    const system = window.matchMedia?.("(prefers-color-scheme: dark)");
    system?.addEventListener?.("change", read);
    return () => {
      root.disconnect();
      system?.removeEventListener?.("change", read);
    };
  }, [ref, drawn]);
  return surface;
}

function cssOf(s: AnsiStyle, surface: Surface = THEME_SURFACE): CSSProperties | undefined {
  const fg = s.inverse ? (s.bg ?? surface.bg) : s.fg;
  const bg = s.inverse ? (s.fg ?? surface.fg) : s.bg;
  const css: CSSProperties = {};
  // Colors picked for a dark terminal can vanish on a light page (white or
  // pale green text): each is made readable on what it's drawn on.
  if (fg || bg) css.color = readable(fg ?? surface.fg, bg ?? surface.bg);
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
  if (s > 1) return <span>updated {s}s ago</span>;
  return (
    <span className="inline-flex items-center gap-1.5 text-muted-foreground">
      <span aria-hidden className="size-1.5 rounded-full bg-green motion-safe:animate-pulse" />
      live
    </span>
  );
}
