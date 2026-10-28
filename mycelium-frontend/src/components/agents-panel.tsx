// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import {
  AtSign,
  Check,
  Clock,
  Eye,
  FileText,
  Pause,
  Pencil,
  Play,
  Plus,
  Square,
  SquareTerminal,
  UserMinus,
  UserPlus,
  Users,
} from "lucide-react";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { copyText } from "@/lib/clipboard";
import { inviteLink } from "@/lib/desktop";
import {
  controlAgent,
  logFetchError,
  removeRoomPerson,
  type AgentControlVerb,
  type AgentPause,
  type PresenceMember,
  type RoomFloor,
  type RoomSubscription,
  type RoomOther,
} from "@/lib/api";
import { floorLabel } from "@/lib/floors";
import { useRoom, useRoomRoster, useScheduledHandles } from "@/lib/room-data";
import { runnerName, useRunners } from "@/lib/runners";
import { AddMemberDialog, type MemberKind } from "@/components/add-member-dialog";
import { UnregisterAgentDialog, type UnregisterTarget } from "@/components/unregister-agent-dialog";
import { RenameAgentDialog } from "@/components/rename-agent-dialog";
import { AgentScreenDrawer } from "@/components/agent-screen";
import { Button } from "@/components/ui/button";
import { Monogram } from "@/components/ui/monogram";
import { AgentCardHover } from "@/components/agent-card";
import { EmptyState } from "@/components/empty-state";
import { FadeScroll } from "@/components/ui/fade-scroll";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";
import { nameOf, useNames } from "@/lib/people";
import { usePrincipal } from "@/components/current-user";
import { useHubAddress } from "@/lib/hub-address";

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
 * A member's right-click menu. It wraps the row's card in an element that
 * draws no box (`contents`), since the card already owns the row as its
 * trigger; a right-click on the row still bubbles here.
 */
function MemberMenu({
  handle,
  agent,
  onOpenMemory,
  onWatch,
  onRename,
  onControl,
  canStop = false,
  paused = false,
  onUnregister,
  onRemove,
  removeLabel = "Remove from room",
  children,
}: {
  handle: string;
  agent: boolean;
  onOpenMemory?: (key: string) => void;
  /** Agents that run in a terminal: opens it, live and read-only. */
  onWatch?: () => void;
  /** Agents an engine isn't: opens the form for `agent rename`. */
  onRename?: () => void;
  /** Your own agents, or one nobody owns: pause or resume it. */
  onControl?: (verb: AgentControlVerb) => void;
  /** Your own agents only: stop it too. */
  canStop?: boolean;
  /** It's paused now, so the menu offers Resume rather than Pause. */
  paused?: boolean;
  /** Agents only: opens the confirmation for `agent rm`. */
  onUnregister?: () => void;
  /** People only: takes them out of the room until they join again. */
  onRemove?: () => void;
  /** What the remove item says: in a shared room, posting rejoins them. */
  removeLabel?: string;
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
        {agent && onWatch && (
          <ContextMenuItem icon={SquareTerminal} onClick={onWatch}>
            Watch terminal
          </ContextMenuItem>
        )}
        <ContextMenuItem icon={AtSign} onClick={() => void copyText(`@${handle}`)}>
          Copy @{handle}
        </ContextMenuItem>
        {agent && onRename && (
          <ContextMenuItem icon={Pencil} onClick={onRename}>
            Rename…
          </ContextMenuItem>
        )}
        {agent && onControl && (
          <>
            <ContextMenuSeparator />
            {paused ? (
              <ContextMenuItem icon={Play} onClick={() => onControl("resume")}>
                Resume
              </ContextMenuItem>
            ) : (
              <ContextMenuItem icon={Pause} onClick={() => onControl("pause")}>
                Pause
              </ContextMenuItem>
            )}
            {canStop && (
              <ContextMenuItem icon={Square} onClick={() => onControl("stop")}>
                Stop…
              </ContextMenuItem>
            )}
          </>
        )}
        {agent && onUnregister && (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem icon={UserMinus} destructive onClick={onUnregister}>
              Unregister…
            </ContextMenuItem>
          </>
        )}
        {!agent && onRemove && (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem icon={UserMinus} destructive onClick={onRemove}>
              {removeLabel}
            </ContextMenuItem>
          </>
        )}
      </ContextMenuContent>
    </ContextMenu>
  );
}

/** Per-herdr-state accent for the roster's activity line, so the palette isn't
 *  uniformly cold: working reads warm, blocked hot, done green, idle muted. */
const HERDR_STATE_COLOR: Record<string, string> = {
  working: "var(--yellow)",
  blocked: "var(--red)",
  done: "var(--green)",
  idle: "var(--muted-foreground)",
};

/** Whether a presence member is hosted in a herdr pane (by kind, or by carrying a
 *  known herdr state). */
function isHerdr(member: PresenceMember): boolean {
  return member.kind === "herdr" || (!!member.status && member.status in HERDR_STATE_COLOR);
}

/**
 * Roster of who's in a room: the **people** (recorded by the hub when they
 * joined: made the room, were added, or posted as a person), the **agents**
 * (`agents/<handle>` manifests) and, quietly, **others**: handles that hold a
 * task or are present but are neither. Pairs with the chat box (@-mention to invoke) and the event stream
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
  const [unregistering, setUnregistering] = useState<UnregisterTarget | null>(null);
  const [renaming, setRenaming] = useState<string | null>(null);
  // The agent whose terminal is open in the drawer, with the machine its manifest names.
  const [watching, setWatching] = useState<{ handle: string; runner: string | null } | null>(null);

  // Who's here, shared with the composer's `@` popover: agents from the room's
  // manifests, people from the hub's record of who joined, others who hold a
  // task or are present, and a presence entry for whoever holds a SLIM socket
  // or an `await` lease.
  const { agents, people, others, presence, floors, subscriptions, paused, loading, refresh } =
    useRoomRoster(roomName);
  const { room } = useRoom(roomName);
  const me = usePrincipal();
  // Pause, resume and stop are the owner's alone (the hub refuses anyone
  // else). One with no owner on record ("unknown" says the same) can be
  // paused by anyone, but stopped by nobody: a stop closes a pane on someone's
  // machine.
  const ownerOf = (a: AgentSummary) => {
    const owner = (a.owner ?? "").replace(/^@/, "").toLowerCase();
    return owner && owner !== "unknown" ? owner : null;
  };
  const controls = (a: AgentSummary): AgentControlVerb[] | null => {
    if (a.adapter === "engine" || !me) return null;
    const owner = ownerOf(a);
    if (owner === me) return ["pause", "resume", "stop"];
    return owner ? null : ["pause", "resume"];
  };
  const control = (handle: string, verb: AgentControlVerb) => {
    if (verb === "stop" && !window.confirm(`Stop @${handle} and close its pane? It stays in the room.`)) return;
    controlAgent(roomName, handle, verb, me)
      .catch(logFetchError(`controlAgent(${roomName}, ${handle}, ${verb})`))
      .finally(refresh);
  };
  const removePerson = (handle: string) => {
    removeRoomPerson(roomName, handle)
      .catch(logFetchError(`removeRoomPerson(${roomName}, ${handle})`))
      .finally(refresh);
  };
  const scheduled = useScheduledHandles(roomName);
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
        <span className="text-micro tabular text-faint">
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
        <UnregisterAgentDialog
          roomName={roomName}
          target={unregistering}
          onClose={() => setUnregistering(null)}
          onUnregistered={refresh}
        />
        <RenameAgentDialog
          roomName={roomName}
          handle={renaming}
          onClose={() => setRenaming(null)}
          onRenamed={refresh}
        />
        {watching && (
          <AgentScreenDrawer
            open
            onClose={() => setWatching(null)}
            room={roomName}
            handle={watching.handle}
            runner={watching.runner}
          />
        )}
      </div>

      <FadeScroll className="flex-1">
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
        {!loading && agents.length === 0 && people.length === 0 && others.length === 0 && (
          <EmptyState
            size="sm"
            icon={Users}
            title="No members yet"
            description="Start an agent on your machine from Add, or register one from the CLI. People are listed once they make the room, post in it or are added."
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
                <MemberMenu
                  key={`person-${p.handle}`}
                  handle={p.handle}
                  agent={false}
                  onRemove={() => removePerson(p.handle)}
                  removeLabel={
                    room?.is_public === false ? "Remove from room" : "Remove (they rejoin if they post)"
                  }
                >
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
                  // Named only on your own machines: another person's
                  // computer isn't listed here, even by its id.
                  const machine =
                    a.runner && runnersById.has(a.runner)
                      ? runnerName(runnersById.get(a.runner), a.runner)
                      : null;
                  // Engines and A2A members answer from the hub, with no terminal to watch.
                  const watch =
                    a.adapter === "engine" || a.adapter === "a2a"
                      ? undefined
                      : () => setWatching({ handle: a.handle, runner: a.runner ?? null });
                  return (
                    <MemberMenu
                      key={`agent-${a.handle}`}
                      handle={a.handle}
                      agent
                      onOpenMemory={onOpenMemory}
                      onWatch={watch}
                      onRename={a.adapter === "engine" ? undefined : () => setRenaming(a.handle)}
                      onControl={controls(a) ? (verb) => control(a.handle, verb) : undefined}
                      canStop={controls(a)?.includes("stop") ?? false}
                      paused={paused.has(a.handle.toLowerCase())}
                      onUnregister={() =>
                        setUnregistering({
                          handle: a.handle,
                          runner: a.runner && machine ? { id: a.runner, name: machine } : null,
                        })
                      }
                    >
                    <AgentRow
                      agent={a}
                      groupOwner={groupOwner}
                      machine={machine}
                      memberPresence={presence.get(a.handle.toLowerCase())}
                      floor={floors.get(a.handle.toLowerCase())}
                      subscriptions={subscriptions.get(a.handle.toLowerCase())}
                      paused={paused.get(a.handle.toLowerCase())}
                      schedules={scheduled.get(a.handle.toLowerCase()) ?? 0}
                      marked={marked}
                      rowRef={marked ? highlightRow : undefined}
                      onOpen={watch}
                    />
                    </MemberMenu>
                  );
                })}
            </div>
          );
        })}

        {/* Neither a person nor an agent here, but holding a task or present:
            an agent with no manifest in this room, say. Listed quietly so it
            isn't lost, never as a person. */}
        {others.length > 0 && (
          <div className="opacity-60">
            <SectionLabel count={others.length}>Others</SectionLabel>
            {others.map((o) => (
              <MemberMenu key={`other-${o.handle}`} handle={o.handle} agent={false}>
                <OtherRow
                  other={o}
                  memberPresence={presence.get(o.handle.toLowerCase())}
                  marked={highlight === o.handle}
                  rowRef={highlight === o.handle ? highlightRow : undefined}
                />
              </MemberMenu>
            ))}
          </div>
        )}
      </FadeScroll>
    </div>
  );
}

/** Copy a link that invites a person into this room: it opens the desktop app
 *  when they have it, and offers the download or the browser when they don't. */
function InviteButton({ roomName }: { roomName: string }) {
  const [copied, setCopied] = useState(false);
  const hub = useHubAddress();
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(inviteLink(hub, roomName));
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
        <span className="ml-auto min-w-0 truncate text-micro font-normal text-faint">
          {hint}
        </span>
      )}
    </div>
  );
}

/** Every row's name, in a column of one width: what is said about each member
 *  then starts at the same place down the whole list. A longer name is cut,
 *  and the row's tooltip has it whole. */
const NAME_COLUMN = "flex w-32 flex-shrink-0 items-center gap-1.5 min-w-0";
/** What is said about the member, after the name column. */
const META_COLUMN = "min-w-0 flex-1 truncate text-micro text-faint";

type AgentSummary = ReturnType<typeof useRoomRoster>["agents"][number];
type RosterPerson = ReturnType<typeof useRoomRoster>["people"][number];

/** One handle in Others: present or holding a task, but neither a person nor an
 *  agent in this room. Quieter than a member row, and nothing to manage. */
function OtherRow({
  other: o,
  memberPresence,
  marked,
  rowRef,
}: {
  other: RoomOther;
  memberPresence?: PresenceMember;
  marked: boolean;
  rowRef?: React.Ref<HTMLDivElement>;
}) {
  const why = [o.present && "here now", o.holds_task && "holds a task"].filter(Boolean).join(" · ");
  return (
    <AgentCardHover handle={o.handle} side="left">
      <div
        tabIndex={0}
        ref={rowRef}
        className={`flex h-7 items-center gap-2 px-3 transition-colors hover:bg-hairline ${
          marked ? "bg-accent/15" : ""
        }`}
      >
        <Monogram handle={o.handle} color="var(--avatar-neutral)" className="size-5 text-[9px]" presence={memberPresence?.kind} status={memberPresence?.status} mutePresence />
        <span className={NAME_COLUMN}>
          <span className="truncate text-label text-text">@{o.handle}</span>
        </span>
        <span className={META_COLUMN}>{why}</span>
      </div>
    </AgentCardHover>
  );
}

/** One person, one line, at the agent rows' density. More about them is in
 *  their card (`AgentCardHover`). */
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
    <AgentCardHover handle={p.handle} side="left">
      <div
        tabIndex={0}
        ref={rowRef}
        className={`flex h-7 items-center gap-2 px-3 transition-colors hover:bg-hairline ${
          marked ? "bg-accent/15" : ""
        }`}
      >
        <Monogram handle={p.handle} color="var(--avatar-neutral)" className="size-5 text-[9px]" presence={memberPresence?.kind} status={memberPresence?.status} wakePending={memberPresence?.wake_pending} mutePresence />
        {/* Their name when they gave one (the handle is in the card), and
            whether it's you, in the name column. */}
        <span className={NAME_COLUMN}>
          <span className="truncate text-label text-text">{name ?? `@${p.handle}`}</span>
          {p.you && <span className="flex-shrink-0 text-micro font-medium text-accent">you</span>}
        </span>
        {/* The floor's label names a task, which can be long: it is what gives
            way, never the name (the card carries it whole). */}
        {meta && <span className={META_COLUMN}>{meta}</span>}
      </div>
    </AgentCardHover>
  );
}

/** The one terse thing to show at the end of a compact row: what an engine is,
 *  or how present a worker is. The avatar halo already carries live/awaiting, so
 *  this stays short — the full story is in the row's card. */
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
  // An agent that can't reply needs a person, whatever else it's doing; its card says why.
  if (presence?.can_reply === false) return "can't reply";
  if (presence && isHerdr(presence)) return presence.status === "blocked" ? "waiting for input" : (presence.status ?? "alive");
  if (presence?.kind === "slim") return "live";
  if (presence?.kind === "lease") return "awaiting";
  if (machine) return `on ${machine}`;
  return null;
}

/**
 * One agent, one line. The dense roster reads as a scannable column of handles,
 * not a stack of cards: a small avatar, the handle, and a terse status in a
 * column that starts at the same place on every row. The owner is hoisted to the group header (nearly every agent in a room
 * shares one), so a row only tags an owner when it breaks from the group's; the
 * description and full owner live in its card rather than on every row.
 */
function AgentRow({
  agent: a,
  groupOwner,
  memberPresence,
  floor,
  subscriptions,
  paused,
  schedules = 0,
  marked,
  rowRef,
  machine = null,
  onOpen,
}: {
  agent: AgentSummary;
  /** The owner shared by the row's group, if any — omitted from the row itself. */
  groupOwner: string | null;
  memberPresence?: PresenceMember;
  floor?: RoomFloor;
  /** What it subscribed to: woken when these happen, without anyone asking it. */
  subscriptions?: RoomSubscription[];
  /** Its pause, while it's paused: nothing wakes it until it's resumed. */
  paused?: AgentPause;
  /** How many live schedules wake this agent; a clock shows when there is one. */
  schedules?: number;
  marked: boolean;
  rowRef?: React.Ref<HTMLDivElement>;
  /** The machine the app started this agent on, by name. */
  machine?: string | null;
  /** Opens its terminal, for an agent that runs in one. */
  onOpen?: () => void;
}) {
  // A pause says why it isn't answering, which beats what it was doing.
  const meta = paused ? "paused" : rowMeta(a, memberPresence, floor, machine);
  const oddOwner = a.owner && a.owner !== groupOwner ? a.owner : null;
  return (
    <AgentCardHover handle={a.handle} side="left">
      <div
        ref={rowRef}
        role={onOpen ? "button" : undefined}
        // Focusable either way: focus opens its card.
        tabIndex={0}
        aria-label={onOpen ? `Watch @${a.handle}'s terminal` : undefined}
        onClick={onOpen}
        onKeyDown={onOpen ? (e) => (e.key === "Enter" || e.key === " ") && (e.preventDefault(), onOpen()) : undefined}
        className={`flex h-7 items-center gap-2 px-3 transition-colors hover:bg-hairline ${
          onOpen ? "cursor-pointer" : ""
        } ${marked ? "bg-accent/15" : ""}`}
      >
        <Monogram handle={a.handle} className="size-5 text-[9px]" presence={memberPresence?.kind} status={memberPresence?.status} wakePending={memberPresence?.wake_pending} mutePresence kind={a.adapter === "engine" ? "engine" : "agent"} />
        <span className={NAME_COLUMN}>
          <span className="truncate text-label text-text">{a.handle}</span>
          {schedules > 0 && (
            <Clock
              aria-label={`${schedules} schedule${schedules === 1 ? "" : "s"}`}
              className="size-3 shrink-0 text-faint"
              strokeWidth={2}
            />
          )}
          {/* Subscribed to something: woken when it happens, without being
              asked. What it subscribed to is in the icon's tooltip. */}
          {subscriptions?.length ? (
            <Tooltip content={subscriptions.map((s) => s.describe).join("\n")} className="whitespace-pre-line">
              <Eye
                aria-label={`subscribed to ${subscriptions.length} thing${subscriptions.length === 1 ? "" : "s"}`}
                className="size-3 shrink-0 text-faint"
                strokeWidth={2}
              />
            </Tooltip>
          ) : null}
          {a.adapter === "a2a" && (
            <span className="inline-flex flex-shrink-0 items-center rounded border border-accent/30 bg-accent-soft/40 px-1 text-[9px] font-medium leading-tight text-accent">
              a2a
            </span>
          )}
        </span>
        {/* Whose it is (when not the group's), then what it's doing, both
            starting where every row's do. */}
        {(oddOwner || meta) && (
          <span className={META_COLUMN}>{[oddOwner && `@${oddOwner}`, meta].filter(Boolean).join(" · ")}</span>
        )}
      </div>
    </AgentCardHover>
  );
}

