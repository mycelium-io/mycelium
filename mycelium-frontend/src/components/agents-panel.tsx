// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { AtSign, Check, FileText, Plus, UserPlus, Users } from "lucide-react";
import { ContextMenu, ContextMenuContent, ContextMenuItem, ContextMenuTrigger } from "@/components/ui/context-menu";
import { copyText } from "@/lib/clipboard";
import { inviteLink } from "@/lib/desktop";
import { type PresenceMember, type RoomFloor } from "@/lib/api";
import { floorLabel } from "@/lib/floors";
import { useRoomRoster } from "@/lib/room-data";
import { runnerName, useRunners } from "@/lib/runners";
import { AddMemberDialog, type MemberKind } from "@/components/add-member-dialog";
import { Button } from "@/components/ui/button";
import { Monogram } from "@/components/ui/monogram";
import { HerdrRam } from "@/components/ui/herdr-ram";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";
import { nameOf, useNames } from "@/lib/people";

interface Props {
  roomName: string;
  /** One-shot request to open the engine invite form — how the command palette
   * reaches it from anywhere in the room. */
  engineInvite?: boolean;
  onEngineInviteShown?: () => void;
  /** A handle to reveal, arrived at from search. The roster has no detail view,
   *  so the row scrolls into sight and marks itself instead of opening. */
  focusHandle?: string | null;
  onFocusConsumed?: () => void;
  /** Opens a memory as a room tab; an agent's right-click menu opens its profile. */
  onOpenMemory?: (key: string) => void;
}

/**
 * A member's right-click menu. It wraps the row's tooltip in an element that
 * draws no box (`contents`), since the tooltip already owns the row as its
 * trigger; a right-click on the row still bubbles here.
 */
function MemberMenu({
  handle,
  agent,
  onOpenMemory,
  children,
}: {
  handle: string;
  agent: boolean;
  onOpenMemory?: (key: string) => void;
  children: React.ReactNode;
}) {
  return (
    <ContextMenu>
      <ContextMenuTrigger>
        <div className="contents">{children}</div>
      </ContextMenuTrigger>
      <ContextMenuContent>
        {agent && onOpenMemory && (
          <ContextMenuItem icon={FileText} onClick={() => onOpenMemory(`agents/${handle}`)}>
            Open profile
          </ContextMenuItem>
        )}
        <ContextMenuItem icon={AtSign} onClick={() => void copyText(`@${handle}`)}>
          Copy @{handle}
        </ContextMenuItem>
      </ContextMenuContent>
    </ContextMenu>
  );
}

/** Minute-granular relative age; null under a minute (an actively-polling lease
 *  reads plainly as "awaiting" rather than churning a seconds counter). */
function relativeTime(iso: string): string | null {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return null;
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

/** One label/value line in a member card. Rendered only when it has a value. */
function DetailRow({
  label,
  value,
  color,
}: {
  label: string;
  value?: React.ReactNode;
  color?: string;
}) {
  if (value == null || value === "") return null;
  return (
    <div className="flex gap-2 text-micro leading-relaxed">
      <span className="w-16 shrink-0 whitespace-nowrap text-faint">{label}</span>
      <span className="min-w-0 flex-1 break-words" style={color ? { color } : undefined}>
        {value}
      </span>
    </div>
  );
}

/** Per-herdr-state accent for the roster's activity line, so the palette isn't
 *  uniformly cold: working reads warm, blocked hot, done green, idle muted. */
const HERDR_STATE_COLOR: Record<string, string> = {
  working: "var(--warning, #d19a45)",
  blocked: "var(--destructive, #d1495b)",
  done: "var(--success, #4c9a6a)",
  idle: "var(--muted-foreground)",
};

/** Whether a presence member is hosted in a herdr pane (by kind, or by carrying a
 *  known herdr state). */
function isHerdr(member: PresenceMember): boolean {
  return member.kind === "herdr" || (!!member.status && member.status in HERDR_STATE_COLOR);
}

/** How a member is hosted, in words — the honest expansion of the presence kind. */
function hostingLabel(member: PresenceMember): string {
  if (isHerdr(member)) return "herdr pane (not joined)";
  return member.kind === "slim" ? "SLIM socket" : "server-held await lease";
}

/** The presence half of a member card: how it's hosted, its live state and
 *  current task, any queued wake, and when it was last seen — the detail behind
 *  the compact row's halo. */
function presenceDetail(member?: PresenceMember): React.ReactNode {
  if (!member) return null;
  const age = member.last_seen ? relativeTime(member.last_seen) : null;
  const stateColor = HERDR_STATE_COLOR[member.status ?? ""];
  return (
    <>
      <DetailRow label="hosting" value={hostingLabel(member)} />
      <DetailRow label="state" value={member.status ?? undefined} color={stateColor} />
      <DetailRow label="task" value={member.title?.trim() || undefined} />
      <DetailRow
        label="wake"
        value={member.wake_pending ? "queued, held until idle" : undefined}
        color="var(--accent)"
      />
      <DetailRow
        label="last seen"
        value={member.kind === "slim" ? "now (live socket)" : (age ?? "awaiting")}
      />
    </>
  );
}

/** The hover card shown for any roster row: a monogram header plus a detail list
 *  (identity rows the caller passes + the shared presence rows). */
function MemberTooltipCard({
  handle,
  color,
  presence,
  children,
}: {
  handle: string;
  color?: string;
  presence?: PresenceMember;
  children?: React.ReactNode;
}) {
  return (
    <div className="flex flex-col gap-2">
      <div className="flex items-center gap-2">
        <Monogram
          handle={handle}
          color={color}
          className="size-6"
          presence={presence?.kind}
          status={presence?.status}
          wakePending={presence?.wake_pending}
          mutePresence
        />
        <span className="font-mono text-label font-semibold text-text">@{handle}</span>
        {presence && isHerdr(presence) && (
          <HerdrRam className="size-3 opacity-70" style={{ color: "var(--accent)" }} />
        )}
      </div>
      <div className="flex flex-col gap-0.5">
        {children}
        {presenceDetail(presence)}
      </div>
    </div>
  );
}

/**
 * Roster of who's in a room: the **people** (agent owners + anyone who's posted,
 * plus the handle you're acting as) and the **agents** (`agents/<handle>`
 * manifests). Pairs with the chat box (@-mention to invoke) and the event stream
 * (replies are badged) to make the whole register → list → invoke → reply loop
 * visible. Humans and agents share the monogram avatar, told apart by tint
 * (muted for people, accent for agents).
 *
 * Engines (aligner / synthesizer / hello) are backend-owned, so their separate
 * invitation action is a pure manifest write. A coding agent needs something on
 * the user's machine to start it: with a runner connected (`mycelium runner`)
 * the app queues that start through the hub; without one, the setup is copied
 * into an agent the user already has open.
 */
export function AgentsPanel({
  roomName,
  engineInvite = false,
  onEngineInviteShown,
  focusHandle = null,
  onFocusConsumed,
  onOpenMemory,
}: Props) {
  const [addOpen, setAddOpen] = useState(false);
  const [addKind, setAddKind] = useState<MemberKind>("machine");

  // Who's here, shared with the composer's `@` popover: agents from the room's
  // manifests, people from agent owners ∪ posters ∪ live presence ∪ you, and a
  // presence entry for whoever holds a SLIM socket or an `await` lease.
  const { agents, people, presence, floors, loading, refresh } = useRoomRoster(roomName);
  const { runners } = useRunners();
  const runnersById = useMemo(() => new Map(runners.map((r) => [r.id, r])), [runners]);

  useEffect(() => {
    if (!engineInvite) return;
    // One-shot: the parent asks specifically for an engine, rather than opening
    // the coding-agent handoff first.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setAddKind("engine");
    setAddOpen(true);
    onEngineInviteShown?.();
  }, [engineInvite, onEngineInviteShown]);

  // Arriving from search: mark the named row and scroll it into sight. The mark
  // outlives the request — a highlight that vanished with the URL parameter
  // would be gone before it was read.
  const [highlight, setHighlight] = useState<string | null>(null);
  const highlightRow = useRef<HTMLDivElement>(null);
  useEffect(() => {
    if (!focusHandle) return;
    // The highlight outlives focusHandle, which is cleared as soon as it is consumed.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setHighlight(focusHandle);
    onFocusConsumed?.();
  }, [focusHandle, onFocusConsumed]);
  useEffect(() => {
    if (!highlight) return;
    highlightRow.current?.scrollIntoView({ block: "center" });
  }, [highlight, loading]);

  // Re-tick once a minute so the minute-granular "seen Xm ago" labels advance
  // without a refetch (matches the label resolution — no sub-minute churn).
  const [, setNow] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setNow((n) => n + 1), 60_000);
    return () => clearInterval(t);
  }, []);

  // Poll the roster at the herdr sync bridge's cadence (~5s) so liveness halos
  // and queued-wake badges track the room near-live instead of lagging behind.
  useEffect(() => {
    const t = setInterval(refresh, 5_000);
    return () => clearInterval(t);
  }, [refresh]);

  // Agents by where they are in their life, not who owns them (a room's swarm is
  // nearly all one owner): **Engines** are the backend capabilities (aligner,
  // synthesizer), kept apart because they persist; every other agent — coding
  // agents and bridged A2A ones alike — is **Active** when it holds a live socket
  // or an await lease and **Idle** otherwise. Idle folds by default so the handful
  // working now leads, while the group count still says how large the room is.
  const agentGroups = useMemo(() => {
    const active: AgentSummary[] = [];
    const engines: AgentSummary[] = [];
    const idle: AgentSummary[] = [];
    for (const a of agents) {
      if (a.adapter === "engine") engines.push(a);
      else if (presence.get(a.handle.toLowerCase())) active.push(a);
      else idle.push(a);
    }
    return [
      { id: "active", label: "Active agents", agents: active },
      { id: "engines", label: "Engines", agents: engines },
      { id: "idle", label: "Idle agents", agents: idle },
    ].filter((g) => g.agents.length > 0);
  }, [agents, presence]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex h-8 flex-shrink-0 items-center gap-1 px-3">
        <span className="text-micro tabular text-muted-foreground">
          {people.length + agents.length} {people.length + agents.length === 1 ? "member" : "members"}
        </span>
        <InviteButton roomName={roomName} />
        <Button
          variant="ghost"
          size="xs"
          onClick={() => {
            setAddKind("machine");
            setAddOpen(true);
          }}
        >
          <Plus className="size-3" /> Add
        </Button>
        <AddMemberDialog
          open={addOpen}
          onOpenChange={setAddOpen}
          roomName={roomName}
          initialKind={addKind}
          onAdded={refresh}
        />
      </div>

      <div className="flex-1 overflow-y-auto">
        {loading &&
          ["w-20", "w-28", "w-16"].map((w, i) => (
            <div key={i} className="flex items-center gap-2.5 px-3 py-2.5">
              <Skeleton className="size-8 flex-shrink-0 rounded-full" />
              <div className="min-w-0 flex-1">
                <Skeleton className={`h-3 ${w}`} />
                <Skeleton className="mt-1.5 h-2.5 w-24" />
              </div>
            </div>
          ))}
        {!loading && agents.length === 0 && people.length === 0 && (
          <EmptyState
            size="sm"
            icon={Users}
            title="No members yet"
            description="Start an agent on your machine from Invite, or register one from the CLI. People appear once they own an agent or post."
            action={
              <code className="font-mono text-micro bg-surface px-1.5 py-0.5 text-accent border border-border rounded whitespace-nowrap">
                mycelium agent create
              </code>
            }
          />
        )}

        {/* One plain list under quiet labels: nothing folds, so every member
            is where you look for them. */}
        {people.length > 0 && (
          <>
            <SectionLabel count={people.length}>People</SectionLabel>
            {people.map((p) => {
              const marked = highlight === p.handle;
              return (
                <MemberMenu key={`person-${p.handle}`} handle={p.handle} agent={false}>
                  <PersonRow
                    person={p}
                    memberPresence={presence.get(p.handle)}
                    floor={floors.get(p.handle)}
                    marked={marked}
                    rowRef={marked ? highlightRow : undefined}
                  />
                </MemberMenu>
              );
            })}
          </>
        )}

        {agentGroups.map((group) => {
          // The owner the whole group shares, shown once in the header instead of
          // repeated down every row. Null when the group's owners differ.
          const owners = new Set(group.agents.map((a) => a.owner).filter(Boolean));
          const groupOwner = owners.size === 1 ? [...owners][0]! : null;
          return (
            // The idle swarm stays listed, dimmed, rather than folded away.
            <div key={group.id} className={group.id === "idle" ? "opacity-60" : undefined}>
              <SectionLabel count={group.agents.length} hint={groupOwner ? `@${groupOwner}` : undefined}>
                {group.label}
              </SectionLabel>
              {group.agents.map((a) => {
                  const marked = highlight === a.handle;
                  return (
                    <MemberMenu key={`agent-${a.handle}`} handle={a.handle} agent onOpenMemory={onOpenMemory}>
                    <AgentRow
                      agent={a}
                      groupOwner={groupOwner}
                      // Named only on your own machines: another person's
                      // computer isn't listed here, even by its id.
                      machine={
                        a.runner && runnersById.has(a.runner)
                          ? runnerName(runnersById.get(a.runner), a.runner)
                          : null
                      }
                      memberPresence={presence.get(a.handle.toLowerCase())}
                      floor={floors.get(a.handle.toLowerCase())}
                      marked={marked}
                      rowRef={marked ? highlightRow : undefined}
                    />
                    </MemberMenu>
                  );
                })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

/** Copy a link that invites a person into this room: it opens the desktop app
 *  when they have it, and offers the download or the browser when they don't. */
function InviteButton({ roomName }: { roomName: string }) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(inviteLink(window.location.origin, roomName));
      setCopied(true);
      setTimeout(() => setCopied(false), 1600);
    } catch {
      // Clipboard blocked: nothing to undo, the button just doesn't confirm.
    }
  };
  return (
    <Tooltip content="Copy a link that invites someone to this room">
      <Button variant="ghost" size="xs" className="ml-auto" onClick={copy}>
        {copied ? <Check className="size-3 text-green" /> : <UserPlus className="size-3" />}
        {copied ? "Copied" : "Invite"}
      </Button>
    </Tooltip>
  );
}

/** A quiet label over a roster group, as an editor's panel draws one: sentence
 *  case and a count, nothing to fold. */
function SectionLabel({
  children,
  count,
  hint,
}: {
  children: React.ReactNode;
  count?: number;
  /** An aside after the count, e.g. the owner a whole group shares. */
  hint?: string;
}) {
  return (
    <div className="flex h-7 w-full items-end gap-1.5 px-3 pb-1 text-micro font-medium text-faint">
      <span className="flex-shrink-0 whitespace-nowrap">{children}</span>
      {count !== undefined && <span className="flex-shrink-0 font-normal tabular">{count}</span>}
      {hint && (
        <span className="ml-auto min-w-0 truncate font-mono text-micro font-normal text-faint">
          {hint}
        </span>
      )}
    </div>
  );
}

type AgentSummary = ReturnType<typeof useRoomRoster>["agents"][number];
type RosterPerson = ReturnType<typeof useRoomRoster>["people"][number];

/** One person, one line, at the agent rows' density. Owns/posted/teams live in
 *  the hover tooltip. */
function PersonRow({
  person: p,
  memberPresence,
  floor,
  marked,
  rowRef,
}: {
  person: RosterPerson;
  memberPresence?: PresenceMember;
  floor?: RoomFloor;
  marked: boolean;
  rowRef?: React.Ref<HTMLDivElement>;
}) {
  const name = nameOf(useNames(), p.handle);
  // Whose turn it is beats how they are hosted: a person the floor was given to
  // is being waited on, which is the one thing the room needs to know.
  const meta = floor
    ? floorLabel(p.handle, floor)
    : memberPresence && isHerdr(memberPresence)
      ? (memberPresence.status ?? "alive")
      : memberPresence?.kind === "slim"
        ? "live"
        : memberPresence?.kind === "lease"
          ? "awaiting"
          : null;
  return (
    <Tooltip
      side="left"
      className="w-72 max-w-72 p-3"
      content={
        <MemberTooltipCard handle={p.handle} color="var(--avatar-neutral)" presence={memberPresence}>
          <DetailRow label="floor" value={floor ? floorLabel(p.handle, floor) : undefined} color="var(--accent)" />
          <DetailRow label="role" value={p.owns ? "owner" : "posted here"} />
          <DetailRow label="teams" value={p.teams.length > 0 ? p.teams.join(", ") : undefined} />
          {p.you && <DetailRow label="you" value="acting as this handle" color="var(--accent)" />}
        </MemberTooltipCard>
      }
    >
      <div
        ref={rowRef}
        className={`flex h-7 items-center gap-2 px-3 transition-colors hover:bg-hairline ${
          marked ? "bg-accent/15" : ""
        }`}
      >
        <Monogram handle={p.handle} color="var(--avatar-neutral)" className="size-5 text-[9px]" presence={memberPresence?.kind} status={memberPresence?.status} wakePending={memberPresence?.wake_pending} mutePresence />
        {/* Their name when they gave one, the handle quieter beside it. */}
        {name ? (
          <span className="flex min-w-0 shrink items-baseline gap-1.5">
            <span className="truncate text-label text-text">{name}</span>
            <span className="shrink-0 font-mono text-micro text-faint">@{p.handle}</span>
          </span>
        ) : (
          <span className="shrink-0 font-mono text-label text-text">@{p.handle}</span>
        )}
        {p.you && <span className="flex-shrink-0 text-micro font-medium text-accent">you</span>}
        {/* The floor's label names a task, which can be long: it is what gives
            way, never the handle it is about (the tooltip carries it whole). */}
        {meta && <span className="ml-auto min-w-0 truncate text-micro text-faint">{meta}</span>}
      </div>
    </Tooltip>
  );
}

/** The one terse thing to show at the end of a compact row: what an engine is,
 *  or how present a worker is. The avatar halo already carries live/awaiting, so
 *  this stays short — the full story is in the row's hover tooltip. */
function rowMeta(
  a: AgentSummary,
  presence?: PresenceMember,
  floor?: RoomFloor,
  machine?: string | null,
): string | null {
  // Whose turn it is beats what the row is: a member the floor was given to is
  // being waited on, and that reads the same for a persona as for a session.
  if (floor) return floorLabel(a.handle, floor);
  if (a.adapter === "engine") return a.kind ?? "engine";
  if (a.adapter === "a2a") return null; // the a2a badge already labels it
  if (presence && isHerdr(presence)) return presence.status ?? "alive";
  if (presence?.kind === "slim") return "live";
  if (presence?.kind === "lease") return "awaiting";
  if (machine) return `on ${machine}`;
  return null;
}

/**
 * One agent, one line. The dense roster reads as a scannable column of handles,
 * not a stack of cards: a small avatar, the handle, and a terse right-aligned
 * status. The owner is hoisted to the group header (nearly every agent in a room
 * shares one), so a row only tags an owner when it breaks from the group's; the
 * description and full owner/team live in the hover tooltip rather than on every
 * row.
 */
function AgentRow({
  agent: a,
  groupOwner,
  memberPresence,
  floor,
  marked,
  rowRef,
  machine = null,
}: {
  agent: AgentSummary;
  /** The owner shared by the row's group, if any — omitted from the row itself. */
  groupOwner: string | null;
  memberPresence?: PresenceMember;
  floor?: RoomFloor;
  marked: boolean;
  rowRef?: React.Ref<HTMLDivElement>;
  /** The machine the app started this agent on, by name. */
  machine?: string | null;
}) {
  const meta = rowMeta(a, memberPresence, floor, machine);
  const oddOwner = a.owner && a.owner !== groupOwner ? a.owner : null;
  const adapter = a.adapter === "engine" && a.kind ? `engine · ${a.kind}` : a.adapter;
  const cli = a.adapter === "engine" || a.adapter === "a2a" ? undefined : (a.framework ?? undefined);
  return (
    <Tooltip
      side="left"
      className="w-72 max-w-72 p-3"
      content={
        <MemberTooltipCard handle={a.handle} presence={memberPresence}>
          <DetailRow label="floor" value={floor ? floorLabel(a.handle, floor) : undefined} color="var(--accent)" />
          <DetailRow label="owner" value={a.owner ? `@${a.owner}` : undefined} />
          <DetailRow label="team" value={a.team ?? undefined} />
          <DetailRow label="runs" value={cli} />
          <DetailRow label="adapter" value={adapter} />
          <DetailRow label="machine" value={machine ?? undefined} />
          <DetailRow
            label="skills"
            value={a.adapter === "a2a" && a.a2a_skills?.length ? a.a2a_skills.join(", ") : undefined}
          />
          <DetailRow label="about" value={a.description} />
        </MemberTooltipCard>
      }
    >
      <div
        ref={rowRef}
        className={`flex h-7 items-center gap-2 px-3 transition-colors hover:bg-hairline ${
          marked ? "bg-accent/15" : ""
        }`}
      >
        <Monogram handle={a.handle} className="size-5 text-[9px]" presence={memberPresence?.kind} status={memberPresence?.status} wakePending={memberPresence?.wake_pending} mutePresence />
        <span className="shrink-0 font-mono text-label text-text">{a.handle}</span>
        {a.adapter === "a2a" && (
          <span className="inline-flex flex-shrink-0 items-center rounded border border-accent/30 bg-accent-soft/40 px-1 text-[9px] font-medium leading-tight text-accent">
            a2a
          </span>
        )}
        {oddOwner && (
          <span className="truncate font-mono text-micro text-faint">@{oddOwner}</span>
        )}
        {meta && <span className="ml-auto min-w-0 truncate text-micro text-faint">{meta}</span>}
      </div>
    </Tooltip>
  );
}

