// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useRef, useState, type ReactElement, type ReactNode } from "react";
import { PreviewCard } from "@base-ui/react/preview-card";
import { AtSign, MessageSquare, MoreHorizontal, RotateCw, SquareTerminal } from "lucide-react";
import { useAgentOpener } from "@/components/agent-opener";
import { ScreenLines } from "@/components/agent-screen";
import { RestartDialog } from "@/components/machine-agents";
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from "@/components/ui/dropdown-menu";
import { Monogram } from "@/components/ui/monogram";
import type { MachineAgent, Runner } from "@/lib/api";
import { memberState, wantsScreen, type MemberKind } from "@/lib/agent-card";
import { copyText } from "@/lib/clipboard";
import { insertIntoComposer } from "@/lib/message-actions";
import { nameOf, useNames } from "@/lib/people";
import { Ago } from "@/lib/relative-time";
import { useRoomBoard, useRoomRoster } from "@/lib/room-data";
import { runnerName, useRunners } from "@/lib/runners";

/** How long a pointer rests on a name or avatar before its card opens. */
export const CARD_DELAY_MS = 350;

const bare = (h: string | null | undefined) => (h ?? "").replace(/^@/, "").toLowerCase();

/** One label and its value on a line; nothing when there's no value. */
function Row({ label, children, tone }: { label: string; children?: ReactNode; tone?: string }) {
  if (children == null || children === "") return null;
  return (
    <div className="flex gap-3 text-micro leading-5">
      <span className="w-14 shrink-0 text-faint">{label}</span>
      <span className="min-w-0 flex-1 truncate text-muted-foreground" style={tone ? { color: tone } : undefined}>
        {children}
      </span>
    </div>
  );
}

function Action({ icon: Icon, label, onClick }: { icon: typeof SquareTerminal; label: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-center gap-1.5 rounded px-1.5 py-1 text-micro text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
    >
      <Icon className="size-3.5" />
      {label}
    </button>
  );
}

/**
 * A member's card: who it is, whose it is and where it runs, whether it's OK,
 * and what it's on. The same card for an agent, a person and an engine,
 * wherever the member's name or avatar appears.
 *
 * An agent on this machine shows the last lines of its screen while it's
 * working, waiting for input or can't reply, read locally by the app. Nobody
 * else's agent ever shows a screen, and the screen never leaves this machine.
 */
export function AgentCard({
  room,
  handle,
  onRestart,
}: {
  room: string;
  handle: string;
  /** Asks to restart it. The dialog lives outside the card, which closes as the pointer leaves for it. */
  onRestart: (runner: Runner, agents: MachineAgent[]) => void;
}) {
  const { agents, presence, floors } = useRoomRoster(room);
  const { runners } = useRunners();
  const { board } = useRoomBoard(room);
  const names = useNames();
  const opener = useAgentOpener();

  const lc = bare(handle);
  const agent = agents.find((a) => a.handle.toLowerCase() === lc);
  const kind: MemberKind = agent ? (agent.adapter === "engine" ? "engine" : "agent") : "person";
  const p = presence.get(lc);
  const state = memberState(kind, p, agent?.kind);

  // Your own machines are the ones `useRunners` lists.
  const runner = agent?.runner ? runners.find((r) => r.id === agent.runner) : undefined;
  const machine = agent?.runner ? runnerName(runner, agent.runner) : null;
  // What its machine can restart: one that stopped or is gone, with what it takes to start it again.
  const restartable = (runner?.machine?.workspaces ?? [])
    .flatMap((w) => w.agents)
    .filter((a) => a.handle.toLowerCase() === lc && a.room === room && a.restartable);

  const held = [...board.epics, ...board.tasks].find((t) => bare(t.holder ?? t.assignee) === lc);
  const task = held?.title ?? floors.get(lc)?.title ?? p?.title?.trim() ?? null;
  const name = kind === "person" ? nameOf(names, lc) : undefined;
  const ownerName = agent?.owner ? nameOf(names, agent.owner) : undefined;
  const owner = agent?.owner ? (
    <>
      {ownerName ?? `@${agent.owner}`}
      {ownerName && <span className="ml-1.5 text-faint">@{agent.owner}</span>}
    </>
  ) : null;
  const active = p?.status === "working" || p?.kind === "slim" ? "now" : p?.last_seen ? <Ago at={p.last_seen} /> : null;
  const open = () => opener?.open(lc);

  return (
    <div className="flex flex-col gap-2.5" data-testid="agent-card">
      <div className="flex items-start gap-2.5">
        <Monogram
          handle={lc}
          kind={kind}
          className="mt-0.5 size-7 text-[11px]"
          presence={p?.kind}
          status={p?.status}
          mutePresence
        />
        <div className="min-w-0 flex-1">
          <div className="flex items-baseline gap-2">
            <span className="truncate text-label font-semibold text-text">{name ?? lc}</span>
            {name && <span className="text-micro text-faint">@{lc}</span>}
            <span className="ml-auto flex shrink-0 items-center gap-1.5 text-micro" style={{ color: state.tone }}>
              <span aria-hidden className="size-1.5 rounded-full" style={{ background: state.tone }} />
              {state.word}
            </span>
          </div>
          <p className="line-clamp-2 text-micro leading-snug text-muted-foreground">
            {kind === "person" ? "Person" : agent?.description || (kind === "engine" ? "Engine" : "Agent")}
          </p>
        </div>
      </div>

      <div className="flex flex-col">
        {kind === "agent" && <Row label="owner">{owner}</Row>}
        {kind === "agent" && <Row label="runs on">{machine ? [machine, agent?.framework].filter(Boolean).join(" · ") : null}</Row>}
        {kind === "engine" && <Row label="runs on">the hub</Row>}
        {state.key === "cant_reply" && (
          <Row label="why" tone="var(--red)">
            {p?.cant_reply_why}
          </Row>
        )}
        <Row label="task">{task}</Row>
        <Row label="active">{active}</Row>
      </div>

      {/* Asked only for one of your machines; the app then shows it only when
          that machine is this one. Anyone else's agent is never asked for. */}
      {runner && wantsScreen(kind, state) && <ScreenLines room={room} handle={lc} onOpen={open} />}

      <div className="-mx-1.5 -mb-1 flex items-center gap-0.5 border-t border-border pt-1.5">
        {/* Its terminal is on its own machine: only yours open from here. */}
        {kind === "agent" && runner && opener && <Action icon={SquareTerminal} label="Terminal" onClick={open} />}
        <Action icon={MessageSquare} label="Message" onClick={() => insertIntoComposer({ room, text: `@${lc} ` })} />
        {/* What changes the agent sits a step back, and asks first. */}
        <DropdownMenu>
          <DropdownMenuTrigger
            aria-label={`More for @${lc}`}
            className="ml-auto flex size-7 items-center justify-center rounded text-muted-foreground transition-colors hover:bg-hairline hover:text-text data-[popup-open]:bg-hairline"
          >
            <MoreHorizontal className="size-4" />
          </DropdownMenuTrigger>
          <DropdownMenuContent className="w-52">
            <DropdownMenuItem onClick={() => void copyText(`@${lc}`)}>
              <AtSign className="size-3.5" /> Copy @{lc}
            </DropdownMenuItem>
            {kind === "agent" && runner && restartable.length > 0 && (
              <DropdownMenuItem onClick={() => onRestart(runner, restartable)}>
                <RotateCw className="size-3.5" /> Restart…
              </DropdownMenuItem>
            )}
          </DropdownMenuContent>
        </DropdownMenu>
      </div>
    </div>
  );
}

/**
 * A member's card around any name or avatar: it opens after a short rest of
 * the pointer, or on keyboard focus, and stays open while the pointer is on it.
 * The trigger must take focus to open from the keyboard (a button, or a
 * `tabIndex={0}` element). Without a room it draws the trigger alone.
 */
export function AgentCardHover({
  room,
  handle,
  side = "bottom",
  children,
}: {
  /** The room, when the caller knows it; otherwise the room the page is in. */
  room?: string | null;
  handle: string;
  side?: "top" | "bottom" | "left" | "right";
  children: ReactElement;
}) {
  const opener = useAgentOpener();
  const [restart, setRestart] = useState<{ runner: Runner; agents: MachineAgent[] } | null>(null);
  const [open, setOpen] = useState(false);
  // A click on the name opens something bigger (the member's drawer, their
  // terminal), so the card gets out of its way at once rather than after its
  // close delay. It stays shut until the pointer leaves the name or focus does
  // (a keyboard click is Enter, with no pointer to leave), or the card would
  // open again over whatever the click opened.
  const clicked = useRef(false);
  const at = room ?? opener?.room;
  if (!at) return children;
  return (
    <>
      <PreviewCard.Root
        open={open}
        onOpenChange={next => {
          if (next && clicked.current) return;
          setOpen(next);
        }}
      >
        <PreviewCard.Trigger
          delay={CARD_DELAY_MS}
          closeDelay={150}
          render={children}
          onClick={() => {
            clicked.current = true;
            setOpen(false);
          }}
          onPointerLeave={() => {
            clicked.current = false;
          }}
          onBlur={() => {
            clicked.current = false;
          }}
        />
        <PreviewCard.Portal>
          <PreviewCard.Positioner side={side} align="start" sideOffset={8} collisionPadding={8} className="z-50">
            <PreviewCard.Popup className="w-80 rounded-lg border border-border bg-surface p-3 text-left shadow-xl outline-none">
              <AgentCard room={at} handle={handle} onRestart={(runner, agents) => setRestart({ runner, agents })} />
            </PreviewCard.Popup>
          </PreviewCard.Positioner>
        </PreviewCard.Portal>
      </PreviewCard.Root>
      {restart && <RestartDialog runner={restart.runner} agents={restart.agents} onClose={() => setRestart(null)} />}
    </>
  );
}
