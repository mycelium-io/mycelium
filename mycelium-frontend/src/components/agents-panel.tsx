// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Check, ChevronDown, ChevronRight, Users } from "lucide-react";
import { createEngine, registerA2aAgent, type EngineKind, type PresenceMember } from "@/lib/api";
import { useNetworkStatus, useRoomRoster } from "@/lib/room-data";
import { agentHandoffPrompt } from "@/lib/install";
import { Button } from "@/components/ui/button";
import { CopyAction } from "@/components/ui/copy-field";
import { Input } from "@/components/ui/input";
import { Monogram } from "@/components/ui/monogram";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";
import { useCurrentUser } from "@/components/current-user";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

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

/** How a member is hosted, in words — the honest expansion of the presence kind. */
function hostingLabel(member: PresenceMember): string {
  return member.kind === "slim" ? "SLIM socket" : "server-held await lease";
}

/** The presence half of a member card: how it's hosted and when it was last
 *  seen — the detail behind the compact row's halo. */
function presenceDetail(member?: PresenceMember): React.ReactNode {
  if (!member) return null;
  const age = member.last_seen ? relativeTime(member.last_seen) : null;
  return (
    <>
      <DetailRow label="hosting" value={hostingLabel(member)} />
      <DetailRow
        label="last seen"
        value={member.kind === "slim" ? "now (live socket)" : (age ?? "awaiting")}
      />
    </>
  );
}

/** The hover card shown for any roster row: a monogram header plus a detail list
 *  (identity rows the caller passes + the shared presence rows). Ported from the
 *  herdr roster spike (#540), adapted to the fields on main. */
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
        <Monogram handle={handle} color={color} className="size-6" presence={presence?.kind} mutePresence />
        <span className="font-mono text-label font-semibold text-text">@{handle}</span>
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
 * invitation action is a pure manifest write. Coding-agent registration stays
 * CLI-driven because it has spoke-local side effects the hub cannot perform.
 */
export function AgentsPanel({
  roomName,
  engineInvite = false,
  onEngineInviteShown,
  focusHandle = null,
  onFocusConsumed,
}: Props) {
  // People collapse to a facepile and the idle swarm folds away — both by default.
  const [collapsedGroups, setCollapsedGroups] = useState<Set<string>>(new Set(["people", "idle"]));
  const [agentOpen, setAgentOpen] = useState(false);
  const [engineOpen, setEngineOpen] = useState(false);
  const [a2aOpen, setA2aOpen] = useState(false);
  const [inviteOpen, setInviteOpen] = useState(false);
  const { principal } = useCurrentUser();
  const { network } = useNetworkStatus();
  const noSubscribe = () => () => {};
  const hubUrl = useSyncExternalStore(
    noSubscribe,
    () => window.location.origin,
    () => "<this-hub-url>",
  );

  // Who's here, shared with the composer's `@` popover: agents from the room's
  // manifests, people from agent owners ∪ posters ∪ live presence ∪ you, and a
  // presence entry for whoever holds a SLIM socket or an `await` lease.
  const { agents, people, presence, loading, refresh } = useRoomRoster(roomName);

  useEffect(() => {
    if (!engineInvite) return;
    // One-shot: the parent asks specifically for an engine, rather than opening
    // the coding-agent handoff first.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setEngineOpen(true);
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
  // A highlighted row can live in a folded group (the idle swarm), so reveal
  // every group first, then scroll once it has mounted.
  useEffect(() => {
    if (!highlight) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setCollapsedGroups(new Set());
  }, [highlight]);
  useEffect(() => {
    if (!highlight) return;
    highlightRow.current?.scrollIntoView({ block: "center" });
  }, [highlight, loading, collapsedGroups]);

  // Re-tick once a minute so the minute-granular "seen Xm ago" labels advance
  // without a refetch (matches the label resolution — no sub-minute churn).
  const [, setNow] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setNow((n) => n + 1), 60_000);
    return () => clearInterval(t);
  }, []);

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

  const toggleGroup = (id: string) =>
    setCollapsedGroups((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b border-border bg-paper px-4 py-3">
        <span className="text-label font-semibold text-text">Members</span>
        <span className="text-micro tabular text-muted-foreground">
          {people.length + agents.length}
        </span>
        <Popover open={inviteOpen} onOpenChange={setInviteOpen}>
          <PopoverTrigger render={<Button variant="secondary" size="sm" className="ml-auto" />}>
            Invite <ChevronDown className="size-3" />
          </PopoverTrigger>
          <PopoverContent className="w-64 p-1">
            <InviteOption
              label="Coding agent"
              hint="Copy room-aware setup"
              onClick={() => {
                setInviteOpen(false);
                setAgentOpen(true);
              }}
            />
            <InviteOption
              label="Engine"
              hint="Add a room capability"
              onClick={() => {
                setInviteOpen(false);
                setEngineOpen(true);
              }}
            />
            <InviteOption
              label="A2A agent"
              hint="Connect an external agent service"
              onClick={() => {
                setInviteOpen(false);
                setA2aOpen(true);
              }}
            />
          </PopoverContent>
        </Popover>
        <Dialog open={agentOpen} onOpenChange={setAgentOpen}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle className="text-ui font-semibold text-text">
                Invite a coding agent
              </DialogTitle>
              <DialogDescription className="text-label text-muted-foreground leading-relaxed">
                Paste this into the coding agent you already have open. It connects to this
                hub, registers in this room, and starts by reading the board.
              </DialogDescription>
            </DialogHeader>
            <CopyAction
              value={agentHandoffPrompt({
                hubUrl,
                roomName,
                principal,
                authRequired: network?.auth?.enabled ?? null,
              })}
              label="Copy setup"
              className="mt-4 w-fit"
            />
          </DialogContent>
        </Dialog>
        <Dialog open={engineOpen} onOpenChange={setEngineOpen}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle className="text-ui font-semibold text-text">Invite an engine</DialogTitle>
              <DialogDescription className="text-label text-muted-foreground leading-relaxed">
                Engines are backend-owned room capabilities, not local coding-agent sessions.
              </DialogDescription>
            </DialogHeader>
            <EngineInviteForm
              roomName={roomName}
              createdBy={principal}
              onCreated={() => {
                refresh();
                setEngineOpen(false);
              }}
            />
          </DialogContent>
        </Dialog>
        <Dialog open={a2aOpen} onOpenChange={setA2aOpen}>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle className="text-ui font-semibold text-text">Connect an A2A agent</DialogTitle>
              <DialogDescription className="text-label text-muted-foreground leading-relaxed">
                Connect an external Agent2Agent service to this room.
              </DialogDescription>
            </DialogHeader>
            <A2aAgentForm
              roomName={roomName}
              onCreated={() => {
                refresh();
                setA2aOpen(false);
              }}
            />
          </DialogContent>
        </Dialog>
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
            description="Agents are registered from the CLI; people appear once they own an agent or post."
            action={
              <code className="font-mono text-micro bg-surface px-1.5 py-0.5 text-accent border border-border rounded whitespace-nowrap">
                mycelium agent create
              </code>
            }
          />
        )}

        {people.length > 0 && (() => {
          const collapsed = collapsedGroups.has("people");
          return (
            <>
              <SectionLabel
                collapsible
                collapsed={collapsed}
                onToggle={() => toggleGroup("people")}
                count={people.length}
              >
                People
              </SectionLabel>
              {collapsed ? (
                <Facepile people={people} presence={presence} />
              ) : (
                people.map((p) => {
                  const marked = highlight === p.handle;
                  return (
                    <PersonRow
                      key={`person-${p.handle}`}
                      person={p}
                      memberPresence={presence.get(p.handle)}
                      marked={marked}
                      rowRef={marked ? highlightRow : undefined}
                    />
                  );
                })
              )}
            </>
          );
        })()}

        {agentGroups.map((group) => {
          const collapsed = collapsedGroups.has(group.id);
          // The owner the whole group shares, shown once in the header instead of
          // repeated down every row. Null when the group's owners differ.
          const owners = new Set(group.agents.map((a) => a.owner).filter(Boolean));
          const groupOwner = owners.size === 1 ? [...owners][0]! : null;
          return (
            <div key={group.id}>
              <SectionLabel
                collapsible
                collapsed={collapsed}
                onToggle={() => toggleGroup(group.id)}
                count={group.agents.length}
                hint={groupOwner ? `@${groupOwner}` : undefined}
              >
                {group.label}
              </SectionLabel>
              {!collapsed &&
                group.agents.map((a) => {
                  const marked = highlight === a.handle;
                  return (
                    <AgentRow
                      key={`agent-${a.handle}`}
                      agent={a}
                      groupOwner={groupOwner}
                      memberPresence={presence.get(a.handle.toLowerCase())}
                      marked={marked}
                      rowRef={marked ? highlightRow : undefined}
                    />
                  );
                })}
            </div>
          );
        })}
      </div>
    </div>
  );
}

function InviteOption({ label, hint, onClick }: { label: string; hint: string; onClick: () => void }) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full flex-col gap-0.5 rounded-lg px-3 py-2 text-left transition-colors hover:bg-hairline"
    >
      <span className="text-label font-medium text-text">{label}</span>
      <span className="text-micro text-muted-foreground">{hint}</span>
    </button>
  );
}

/** Small uppercase divider between roster groups, with a count. When `onToggle`
 *  is given it becomes a collapse control with a chevron — how the idle swarm is
 *  folded away by default. */
function SectionLabel({
  children,
  count,
  hint,
  collapsible = false,
  collapsed = false,
  onToggle,
}: {
  children: React.ReactNode;
  count?: number;
  /** A normal-case aside after the count, e.g. the owner a whole group shares. */
  hint?: string;
  collapsible?: boolean;
  collapsed?: boolean;
  onToggle?: () => void;
}) {
  const inner = (
    <>
      {collapsible && (
        <ChevronRight
          className={`size-3 transition-transform ${collapsed ? "" : "rotate-90"}`}
        />
      )}
      <span>{children}</span>
      {count !== undefined && <span className="font-normal tabular">{count}</span>}
      {hint && (
        <span className="ml-auto min-w-0 truncate font-mono text-micro font-normal normal-case tracking-normal text-faint">
          {hint}
        </span>
      )}
    </>
  );
  const cls =
    "flex w-full items-center gap-2 px-3 pt-4 pb-1 text-micro font-semibold uppercase tracking-wide text-faint";
  return collapsible ? (
    <button type="button" onClick={onToggle} className={`${cls} text-left hover:text-muted-foreground`}>
      {inner}
    </button>
  ) : (
    <div className={cls}>{inner}</div>
  );
}

type AgentSummary = ReturnType<typeof useRoomRoster>["agents"][number];
type RosterPerson = ReturnType<typeof useRoomRoster>["people"][number];

/** People as an overlapping avatar stack: who's around, at a glance, in one row
 *  instead of a dozen. Live/awaiting rides each face as its halo; the rest is a
 *  hover tooltip. Overflow past `max` collapses to a `+N` disc. */
function Facepile({
  people,
  presence,
  max = 16,
}: {
  people: RosterPerson[];
  presence: Map<string, PresenceMember>;
  max?: number;
}) {
  const shown = people.slice(0, max);
  const extra = people.length - shown.length;
  return (
    <div className="flex flex-wrap items-center gap-y-1.5 px-3 py-2">
      {shown.map((p) => (
        <Tooltip key={p.handle} content={`@${p.handle}${p.you ? " (you)" : ""}${p.owns ? " · owner" : ""}`}>
          <div className="-ml-1.5 first:ml-0">
            <Monogram
              handle={p.handle}
              color={p.you ? "var(--accent)" : "var(--avatar-neutral)"}
              className="size-6 text-[9px] ring-2 ring-paper"
              presence={presence.get(p.handle)?.kind}
            />
          </div>
        </Tooltip>
      ))}
      {extra > 0 && (
        <div className="-ml-1.5 flex size-6 items-center justify-center rounded-full border border-border bg-surface text-[9px] font-medium text-muted-foreground ring-2 ring-paper">
          +{extra}
        </div>
      )}
    </div>
  );
}

/** One person, one line — the expanded form of the facepile, matching the agent
 *  rows' density. Owns/posted/teams live in the hover tooltip. */
function PersonRow({
  person: p,
  memberPresence,
  marked,
  rowRef,
}: {
  person: RosterPerson;
  memberPresence?: PresenceMember;
  marked: boolean;
  rowRef?: React.Ref<HTMLDivElement>;
}) {
  const meta = memberPresence?.kind === "slim" ? "live" : memberPresence?.kind === "lease" ? "awaiting" : null;
  return (
    <Tooltip
      side="left"
      className="w-72 max-w-72 p-3"
      content={
        <MemberTooltipCard handle={p.handle} color="var(--avatar-neutral)" presence={memberPresence}>
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
        <Monogram handle={p.handle} color="var(--avatar-neutral)" className="size-5 text-[9px]" presence={memberPresence?.kind} mutePresence />
        <span className="truncate font-mono text-label text-text">@{p.handle}</span>
        {p.you && <span className="flex-shrink-0 text-micro font-medium text-accent">you</span>}
        {meta && <span className="ml-auto flex-shrink-0 text-micro text-faint">{meta}</span>}
      </div>
    </Tooltip>
  );
}

/** The one terse thing to show at the end of a compact row: what an engine is,
 *  or how present a worker is. The avatar halo already carries live/awaiting, so
 *  this stays short — the full story is in the row's hover tooltip. */
function rowMeta(a: AgentSummary, presence?: PresenceMember): string | null {
  if (a.adapter === "engine") return a.kind ?? "engine";
  if (a.adapter === "a2a") return null; // the a2a badge already labels it
  if (presence?.kind === "slim") return "live";
  if (presence?.kind === "lease") return "awaiting";
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
  marked,
  rowRef,
}: {
  agent: AgentSummary;
  /** The owner shared by the row's group, if any — omitted from the row itself. */
  groupOwner: string | null;
  memberPresence?: PresenceMember;
  marked: boolean;
  rowRef?: React.Ref<HTMLDivElement>;
}) {
  const meta = rowMeta(a, memberPresence);
  const oddOwner = a.owner && a.owner !== groupOwner ? a.owner : null;
  const adapter = a.adapter === "engine" && a.kind ? `engine · ${a.kind}` : a.adapter;
  return (
    <Tooltip
      side="left"
      className="w-72 max-w-72 p-3"
      content={
        <MemberTooltipCard handle={a.handle} presence={memberPresence}>
          <DetailRow label="owner" value={a.owner ? `@${a.owner}` : undefined} />
          <DetailRow label="team" value={a.team ?? undefined} />
          <DetailRow label="adapter" value={adapter} />
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
        <Monogram handle={a.handle} className="size-5 text-[9px]" presence={memberPresence?.kind} mutePresence />
        <span className="truncate font-mono text-label text-text">{a.handle}</span>
        {a.adapter === "a2a" && (
          <span className="inline-flex flex-shrink-0 items-center rounded border border-accent/30 bg-accent-soft/40 px-1 text-[9px] font-medium leading-tight text-accent">
            a2a
          </span>
        )}
        {oddOwner && (
          <span className="truncate font-mono text-micro text-faint">@{oddOwner}</span>
        )}
        {meta && <span className="ml-auto flex-shrink-0 text-micro text-faint">{meta}</span>}
      </div>
    </Tooltip>
  );
}

const ENGINE_KINDS: { kind: EngineKind; blurb: string }[] = [
  { kind: "aligner", blurb: "Mediates negotiation to consensus." },
  { kind: "synthesizer", blurb: "Distills the room to memory." },
  { kind: "hello", blurb: "Answers once, writes nothing, and proves the path." },
];

/** Invite a first-party cognition engine into the room — a native manifest
 *  write over the backend (no CLI, no machine-local side effects). */
function EngineInviteForm({
  roomName,
  createdBy,
  onCreated,
}: {
  roomName: string;
  createdBy: string | null;
  onCreated: () => void;
}) {
  const [kind, setKind] = useState<EngineKind>("aligner");
  // The handle defaults to the kind name (the common case: one aligner named
  // "aligner"). It tracks the kind until the user edits it, then it's theirs.
  const [handle, setHandle] = useState<EngineKind | string>("aligner");
  const [handleTouched, setHandleTouched] = useState(false);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmed = handle.trim().replace(/^@/, "");
  const canSubmit = trimmed.length > 0 && !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await createEngine(roomName, {
        handle: trimmed,
        kind,
        description: "",
        created_by: createdBy || "web-ui",
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to register engine");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="mt-2 space-y-4">
      <div className="space-y-1.5" role="radiogroup" aria-label="Engine kind">
        {ENGINE_KINDS.map(({ kind: k, blurb }) => (
          <button
            key={k}
            type="button"
            role="radio"
            aria-checked={kind === k}
            onClick={() => {
              setKind(k);
              if (!handleTouched) setHandle(k);
            }}
            className={`flex w-full items-center gap-3 rounded-lg border px-3 py-2.5 text-left transition-colors ${
              kind === k ? "border-accent bg-accent/10" : "border-border hover:bg-hairline"
            }`}
          >
            <span className="min-w-0 flex-1">
              <span className={`block text-label font-medium ${kind === k ? "text-text" : "text-muted-foreground"}`}>
                {k}
              </span>
              <span className="block text-micro leading-snug text-muted-foreground">{blurb}</span>
            </span>
            {kind === k && <Check className="size-4 flex-shrink-0 text-accent" />}
          </button>
        ))}
      </div>

      <div className="space-y-1.5">
        <label className="text-label font-medium text-text">Handle</label>
        <Input
          value={handle}
          onChange={(e) => {
            setHandle(e.target.value);
            setHandleTouched(true);
          }}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder={kind}
          autoCapitalize="none"
          spellCheck={false}
          aria-invalid={!!error}
        />
        <p className="text-micro text-muted-foreground leading-snug">
          Summon it in the channel with{" "}
          <code className="font-mono text-accent">@{trimmed || kind}</code>. Lowercase slug.
        </p>
      </div>

      {error && <p className="text-micro text-[#f87171] leading-snug">{error}</p>}

      <div className="flex items-center gap-2">
        <Button variant="default" size="sm" onClick={submit} disabled={!canSubmit}>
          {submitting ? "Inviting…" : `Invite ${kind}`}
        </Button>
      </div>
    </div>
  );
}

/** Register an external A2A agent by its agent-card base URL — the backend
 *  resolves the card to discover the endpoint + skills, so a bad/unreachable
 *  card comes back as a 502 whose detail we surface verbatim. */
function A2aAgentForm({
  roomName,
  onCreated,
}: {
  roomName: string;
  onCreated: () => void;
}) {
  const [handle, setHandle] = useState("");
  const [card, setCard] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmedHandle = handle.trim().replace(/^@/, "");
  const trimmedCard = card.trim();
  const canSubmit = trimmedHandle.length > 0 && trimmedCard.length > 0 && !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await registerA2aAgent(roomName, {
        handle: trimmedHandle,
        card: trimmedCard,
        description: description.trim(),
      });
      onCreated();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Failed to register A2A agent");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <div className="space-y-4 mt-2">
      <div className="space-y-1.5">
        <label className="text-label font-medium text-text">Handle</label>
        <Input
          value={handle}
          onChange={(e) => setHandle(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder="researcher"
          autoCapitalize="none"
          spellCheck={false}
          aria-invalid={!!error}
        />
        <p className="text-micro text-muted-foreground leading-snug">
          Address it in the channel with{" "}
          <code className="font-mono text-accent">@{trimmedHandle || "handle"}</code>.
          Lowercase slug.
        </p>
      </div>

      <div className="space-y-1.5">
        <label className="text-label font-medium text-text">Agent card URL</label>
        <Input
          value={card}
          onChange={(e) => setCard(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") submit();
          }}
          placeholder="https://agent.example.com"
          autoCapitalize="none"
          spellCheck={false}
          aria-invalid={!!error}
        />
        <p className="text-micro text-muted-foreground leading-snug">
          The base URL of the agent&apos;s A2A agent card. The hub resolves it to
          discover the endpoint and advertised skills.
        </p>
      </div>

      <div className="space-y-1.5">
        <label className="text-label font-medium text-text">
          Description <span className="text-faint">(optional)</span>
        </label>
        <Input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What this agent does in the room"
        />
      </div>

      {error && <p className="text-micro text-[#f87171] leading-snug">{error}</p>}

      <div className="flex items-center gap-2">
        <Button variant="default" size="sm" onClick={submit} disabled={!canSubmit}>
          {submitting ? "Registering…" : "Register A2A agent"}
        </Button>
      </div>
    </div>
  );
}
