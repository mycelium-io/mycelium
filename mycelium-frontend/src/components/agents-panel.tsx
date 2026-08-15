// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Users } from "lucide-react";
import {
  createEngine,
  fetchMessages,
  fetchRoomAgents,
  fetchRoomMembers,
  type AgentSummary,
  type EngineKind,
  type PresenceMember,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Input } from "@/components/ui/input";
import { Monogram } from "@/components/ui/monogram";
import { HerdrRam } from "@/components/ui/herdr-ram";
import {
  Tooltip,
  TooltipContent,
  TooltipProvider,
  TooltipTrigger,
} from "@/components/ui/tooltip";
import { EmptyState } from "@/components/empty-state";
import { Skeleton } from "@/components/ui/skeleton";
import { useCurrentUser } from "@/components/current-user";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

interface Props {
  roomName: string;
  /** Bumped by the room page on pushed presence/memory events to refetch now. */
  refreshKey?: number;
}

interface Person {
  handle: string;
  /** Team slugs, unioned from the agents this person owns. */
  teams: string[];
  /** True when this is the handle the browser is acting as. */
  you: boolean;
  /** True when they own ≥1 agent here (vs. only having posted). */
  owns: boolean;
}

/** Minute-granular relative age; null under a minute (an actively-polling lease
 *  reads plainly as "awaiting" rather than churning a seconds counter). */
function relativeTime(iso: string): string | null {
  const mins = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (mins < 1) return null;
  if (mins < 60) return `${mins}m ago`;
  return `${Math.floor(mins / 60)}h ago`;
}

/** Per-herdr-state accent for the roster's activity line, so the palette isn't
 *  uniformly cold: working reads warm, blocked hot, done green, idle muted. */
const HERDR_STATE_COLOR: Record<string, string> = {
  working: "var(--warning, #d19a45)",
  blocked: "var(--destructive, #d1495b)",
  done: "var(--success, #4c9a6a)",
  idle: "var(--muted-foreground)",
};

/** Subtext for a present member. For a herdr-hosted agent this is the ram mark +
 *  its **current task** (herdr's terminal title) — replacing the old
 *  "herdr · working · not joined" jargon. A bare SLIM/lease member keeps the
 *  plain connection line. Returns null when not present (caller falls back). */
function presenceLine(member?: PresenceMember): React.ReactNode {
  if (!member) return null;
  const isHerdr =
    member.kind === "herdr" || (!!member.status && member.status in HERDR_STATE_COLOR);
  const queued = member.wake_pending ? (
    <span style={{ color: "var(--accent)" }}> · queued</span>
  ) : null;

  if (isHerdr) {
    const task = member.title?.trim();
    const state = member.status ?? "alive";
    const stateColor = HERDR_STATE_COLOR[member.status ?? ""] ?? "var(--muted-foreground)";
    return (
      <span className="inline-flex min-w-0 max-w-full items-center gap-1">
        <HerdrRam className="size-3 shrink-0" style={{ color: "var(--accent)" }} />
        <span className="truncate" style={{ color: task ? "var(--text)" : stateColor }}>
          {task || state}
        </span>
        {queued}
      </span>
    );
  }

  const age = member.last_seen ? relativeTime(member.last_seen) : null;
  const base = member.kind === "slim" ? "connected" : age ? `awaiting · seen ${age}` : "awaiting";
  return (
    <>
      {base}
      {queued}
    </>
  );
}

/** One label/value line in a member tooltip. Rendered only when it has a value. */
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
      <span className="w-14 shrink-0 text-faint">{label}</span>
      <span className="min-w-0 flex-1 break-words" style={color ? { color } : undefined}>
        {value}
      </span>
    </div>
  );
}

/** How a member is hosted, in words — the honest expansion of the presence kind. */
function hostingLabel(member: PresenceMember): string {
  if (member.kind === "herdr") return "herdr pane (not joined)";
  if (member.kind === "slim") return "SLIM socket";
  return "server-held await lease";
}

/** The presence half of a member tooltip: hosting, live state, current task,
 *  queued wake, last-seen — the "full details" behind the compact row. */
function presenceDetail(member?: PresenceMember): React.ReactNode {
  if (!member) return null;
  const stateColor = HERDR_STATE_COLOR[member.status ?? ""];
  const age = member.last_seen ? relativeTime(member.last_seen) : null;
  return (
    <>
      <DetailRow label="hosting" value={hostingLabel(member)} />
      <DetailRow label="state" value={member.status} color={stateColor} />
      <DetailRow label="task" value={member.title?.trim()} />
      <DetailRow
        label="wake"
        value={member.wake_pending ? "queued — held until idle" : undefined}
        color="var(--accent)"
      />
      <DetailRow label="last seen" value={member.kind === "slim" ? "now (live socket)" : age} />
    </>
  );
}

/** The hover card shown for any roster row: a monogram header + the full detail
 *  list (identity rows the caller passes + the shared presence rows). */
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
        />
        <span className="font-mono text-label font-semibold text-text">@{handle}</span>
        {presence?.kind === "herdr" && (
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
 * Engines (aligner / synthesizer) can be invited from the Add dialog — they're
 * backend-owned, so registration is a pure manifest write. Agent registration /
 * teardown stay CLI-only: those have spoke-local side effects (resident session,
 * workspace assets) the hub can't perform. Use `mycelium agent create` / `rm`.
 */
export function AgentsPanel({ roomName, refreshKey = 0 }: Props) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [posters, setPosters] = useState<string[]>([]);
  const [liveMembers, setLiveMembers] = useState<PresenceMember[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [mineOnly, setMineOnly] = useState(false);
  const [addTab, setAddTab] = useState<"agents" | "engines">("agents");
  const [addOpen, setAddOpen] = useState(false);
  const { principal } = useCurrentUser();

  const refresh = useCallback(() => {
    // fetchRoomAgents degrades to [] on failure, so no .catch is needed —
    // `loaded` still flips so the skeleton clears either way.
    fetchRoomAgents(roomName).then((a) => {
      setAgents(a);
      setLoaded(true);
    });
    // Human posters come from the transcript: a room chat post is a broadcast
    // from a handle that isn't a registered agent. fetchMessages degrades to
    // { messages: [] } on failure, so no .catch is needed.
    fetchMessages(roomName, 200).then(({ messages }) => {
      setPosters(
        messages
          .filter((m) => m.message_type === "broadcast")
          .map((m) => m.sender_handle ?? "")
          .filter(Boolean),
      );
    });
    // Live presence: SLIM-connected + server-held lease members. Catches handles
    // that joined via `mycelium await` without registering an agent manifest.
    // fetchRoomMembers degrades to [] on failure, so no .catch is needed.
    fetchRoomMembers(roomName).then(setLiveMembers);
  }, [roomName]);

  useEffect(() => {
    refresh();
    // Poll at the herdr sync bridge's cadence (~5s) so liveness badges + queued-
    // wake dots track the roster near-live instead of lagging up to 30s behind.
    const t = setInterval(refresh, 5_000);
    return () => clearInterval(t);
  }, [refresh, refreshKey]);

  const agentHandles = useMemo(() => new Set(agents.map((a) => a.handle)), [agents]);

  // presence map: handle → full presence member (kind + last_seen) for each live one.
  const presenceMap = useMemo(
    () => new Map(liveMembers.map((m) => [m.handle, m])),
    [liveMembers],
  );

  // Re-tick once a minute so the minute-granular "seen Xm ago" labels advance
  // without a refetch (matches the label resolution — no sub-minute churn).
  const [, setNow] = useState(0);
  useEffect(() => {
    const t = setInterval(() => setNow((n) => n + 1), 60_000);
    return () => clearInterval(t);
  }, []);

  // People = owners of the room's agents ∪ human posters ∪ live presence members
  // ∪ the acting-as handle. Teams roll up from each person's owned agents.
  const people = useMemo(() => {
    const byHandle = new Map<string, Person>();
    const add = (handle: string, owns: boolean) => {
      const h = handle.replace(/^@/, "").toLowerCase();
      if (!h) return;
      const existing = byHandle.get(h);
      if (existing) {
        existing.owns = existing.owns || owns;
        return;
      }
      byHandle.set(h, { handle: h, teams: [], you: h === principal, owns });
    };
    for (const a of agents) if (a.owner) add(a.owner, true);
    for (const p of posters) if (!agentHandles.has(p)) add(p, false);
    // Include handles present via SLIM or lease that aren't registered agents.
    for (const m of liveMembers) if (!agentHandles.has(m.handle)) add(m.handle, false);
    if (principal) add(principal, false);
    for (const person of byHandle.values()) {
      person.teams = [
        ...new Set(
          agents.filter((a) => a.owner === person.handle && a.team).map((a) => a.team as string),
        ),
      ];
    }
    return [...byHandle.values()].sort((x, y) => x.handle.localeCompare(y.handle));
  }, [agents, posters, liveMembers, agentHandles, principal]);

  // "Mine" scopes the agent list to the acting-as user: agents they own, plus
  // any agent fielded by a team their own agents claim.
  const myTeams = useMemo(
    () =>
      new Set(
        agents.filter((a) => a.owner === principal && a.team).map((a) => a.team as string),
      ),
    [agents, principal],
  );
  const visibleAgents = useMemo(
    () =>
      !mineOnly || !principal
        ? agents
        : agents.filter((a) => a.owner === principal || (a.team && myTeams.has(a.team))),
    [agents, mineOnly, principal, myTeams],
  );

  return (
    <TooltipProvider>
      <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center gap-2 border-b border-border bg-paper px-4 py-3">
        <span className="text-label font-semibold text-text">Members</span>
        <span className="text-micro tabular text-muted-foreground">
          {people.length + agents.length}
        </span>
        {principal && (
          <Chip
            variant="accent"
            active={mineOnly}
            onClick={() => setMineOnly((v) => !v)}
            className="ml-1 px-2 py-0.5 text-micro"
          >
            mine
          </Chip>
        )}
        <Dialog open={addOpen} onOpenChange={setAddOpen}>
          <DialogTrigger
            render={<Button variant="secondary" size="sm" className="ml-auto" />}
          >
            Add
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle className="text-ui font-semibold text-text">
                Add an agent or engine
              </DialogTitle>
              <DialogDescription className="text-label text-muted-foreground leading-relaxed">
                <span className="text-text">Engines</span> are backend-owned, so
                you can invite one right here. <span className="text-text">Agents</span>{" "}
                are registered from the CLI, because they have machine-local side
                effects (resident session, workspace assets) the web UI can&apos;t
                perform.
              </DialogDescription>
            </DialogHeader>
            <div className="flex items-center gap-1.5 mt-2">
              <Chip
                variant="accent"
                active={addTab === "agents"}
                onClick={() => setAddTab("agents")}
                className="px-2.5 py-0.5 text-micro"
              >
                Agents
              </Chip>
              <Chip
                variant="accent"
                active={addTab === "engines"}
                onClick={() => setAddTab("engines")}
                className="px-2.5 py-0.5 text-micro"
              >
                Engines
              </Chip>
            </div>
            {addTab === "agents" ? (
              <div className="space-y-6 mt-2">
                <section>
                  <div className="text-label font-semibold text-text mb-1.5">
                    Create a new agent
                  </div>
                  <pre className="font-mono text-micro text-muted-foreground bg-surface border border-border px-2.5 py-2 overflow-x-auto whitespace-pre-wrap break-words">
                    {"mycelium agent create <handle>                  # claude_code\nmycelium agent create <handle> --adapter cursor  # cursor"}
                  </pre>
                  <p className="text-micro text-muted-foreground mt-1 leading-snug">
                    claude_code is proven; cursor is supported but less
                    travelled. Optional:{" "}
                    <code className="font-mono">--cwd &lt;path&gt;</code> for the session&apos;s
                    working dir, and{" "}
                    <code className="font-mono">--owner &lt;you&gt; --team &lt;slug&gt;</code>{" "}
                    to attribute it from creation.
                  </p>
                </section>
                <section>
                  <div className="text-label font-semibold text-text mb-1.5">
                    Keep the session resident
                  </div>
                  <pre className="font-mono text-micro text-muted-foreground bg-surface border border-border px-2.5 py-2 overflow-x-auto whitespace-pre-wrap break-words">
                    {"mycelium await --loop --handle <handle> --exec <cmd>"}
                  </pre>
                  <p className="text-micro text-muted-foreground mt-1 leading-snug">
                    An agent is your own claude_code / cursor session, kept woken
                    by the loop: it <span className="text-text">await</span>s each
                    @-mention, reasons, and <span className="text-text">respond</span>s
                    on the same turn. The loop is the wake — no daemon, no
                    cold-spawn.
                  </p>
                </section>
              </div>
            ) : (
              <EngineInviteForm
                roomName={roomName}
                createdBy={principal}
                onCreated={() => {
                  refresh();
                  setAddOpen(false);
                }}
              />
            )}
          </DialogContent>
        </Dialog>
      </div>

      <div className="flex-1 overflow-y-auto">
        {!loaded &&
          ["w-20", "w-28", "w-16"].map((w, i) => (
            <div key={i} className="flex items-center gap-2.5 border-b border-border px-3 py-2.5 last:border-b-0">
              <Skeleton className="size-8 flex-shrink-0 rounded-full" />
              <div className="min-w-0 flex-1">
                <Skeleton className={`h-3 ${w}`} />
                <Skeleton className="mt-1.5 h-2.5 w-24" />
              </div>
            </div>
          ))}
        {loaded && agents.length === 0 && people.length === 0 && (
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

        {people.length > 0 && (
          <>
            <SectionLabel>People</SectionLabel>
            {people.map((p) => {
              const presence = presenceMap.get(p.handle);
              return (
                <Tooltip key={`person-${p.handle}`}>
                  <TooltipTrigger
                    render={
                      <div className="flex items-center gap-2.5 px-3 py-2.5 border-b border-border last:border-b-0 hover:bg-hairline" />
                    }
                  >
                    <Monogram handle={p.handle} color="var(--muted-foreground)" presence={presence?.kind} status={presence?.status} wakePending={presence?.wake_pending} />
                    <div className="min-w-0 flex-1 leading-tight text-left">
                      <div className="flex items-center gap-1.5">
                        <span className="font-mono text-label text-text font-semibold truncate leading-tight">
                          @{p.handle}
                        </span>
                        {p.you && (
                          <span className="text-micro text-accent font-medium">you</span>
                        )}
                      </div>
                      <div className="text-micro text-muted-foreground truncate leading-tight">
                        {presence ? (
                          presenceLine(presence)
                        ) : (
                          <>
                            {p.owns ? "owner" : "posted here"}
                            {p.teams.length > 0 ? ` · ${p.teams.join(", ")}` : ""}
                          </>
                        )}
                      </div>
                    </div>
                  </TooltipTrigger>
                  <TooltipContent>
                    <MemberTooltipCard handle={p.handle} color="var(--muted-foreground)" presence={presence}>
                      <DetailRow label="role" value={p.owns ? "agent owner" : "posted here"} />
                      {p.you && <DetailRow label="note" value="acting as you" color="var(--accent)" />}
                      {p.teams.length > 0 && <DetailRow label="teams" value={p.teams.join(", ")} />}
                    </MemberTooltipCard>
                  </TooltipContent>
                </Tooltip>
              );
            })}
          </>
        )}

        {agents.length > 0 && <SectionLabel>Agents</SectionLabel>}
        {visibleAgents.map((a) => {
          const mine = principal !== "" && a.owner === principal;
          const presence = presenceMap.get(a.handle);
          return (
            <Tooltip key={`agent-${a.handle}`}>
              <TooltipTrigger
                render={
                  <div className="flex items-center gap-2.5 px-3 py-2.5 border-b border-border last:border-b-0 hover:bg-hairline" />
                }
              >
                <Monogram handle={a.handle} presence={presence?.kind} status={presence?.status} wakePending={presence?.wake_pending} />
                <div className="min-w-0 flex-1 leading-tight text-left">
                  <div className="flex items-center gap-1.5">
                    <span className="font-mono text-label text-text font-semibold truncate leading-tight">
                      {a.handle}
                    </span>
                    {a.owner && (
                      <span
                        className="font-mono text-micro truncate"
                        style={{ color: mine ? "var(--accent)" : "var(--muted-foreground)" }}
                      >
                        @{a.owner}
                      </span>
                    )}
                    {a.team && (
                      <span className="text-micro text-muted-foreground truncate">
                        · {a.team}
                      </span>
                    )}
                  </div>
                  <div className="text-micro text-muted-foreground truncate leading-tight">
                    {presence ? (
                      presenceLine(presence)
                    ) : (
                      <>
                        {a.adapter === "engine" && a.kind ? `engine · ${a.kind}` : a.adapter}
                        {a.description ? ` · ${a.description}` : ""}
                      </>
                    )}
                  </div>
                </div>
              </TooltipTrigger>
              <TooltipContent>
                <MemberTooltipCard handle={a.handle} presence={presence}>
                  <DetailRow
                    label="kind"
                    value={a.adapter === "engine" && a.kind ? `engine · ${a.kind}` : a.adapter}
                  />
                  {a.owner && (
                    <DetailRow
                      label="owner"
                      value={`@${a.owner}`}
                      color={mine ? "var(--accent)" : undefined}
                    />
                  )}
                  {a.team && <DetailRow label="team" value={a.team} />}
                  {a.description && <DetailRow label="about" value={a.description} />}
                </MemberTooltipCard>
              </TooltipContent>
            </Tooltip>
          );
        })}
      </div>
      </div>
    </TooltipProvider>
  );
}

/** Small uppercase divider between the People and Agents groups. */
function SectionLabel({ children }: { children: React.ReactNode }) {
  return (
    <div className="px-3 pt-3 pb-1 text-micro font-semibold uppercase tracking-wide text-faint">
      {children}
    </div>
  );
}

const ENGINE_KINDS: { kind: EngineKind; blurb: string }[] = [
  { kind: "aligner", blurb: "Mediates negotiation to consensus." },
  { kind: "synthesizer", blurb: "Distills the room to memory." },
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
  const [description, setDescription] = useState("");
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
        description: description.trim(),
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
    <div className="space-y-4 mt-2">
      <div className="grid grid-cols-2 gap-2">
        {ENGINE_KINDS.map(({ kind: k, blurb }) => (
          <button
            key={k}
            type="button"
            onClick={() => {
              setKind(k);
              if (!handleTouched) setHandle(k);
            }}
            className={`flex flex-col gap-0.5 rounded-lg border px-3 py-2 text-left transition-colors ${
              kind === k ? "border-accent bg-accent/10" : "border-border hover:bg-hairline"
            }`}
          >
            <span className={`text-label font-medium ${kind === k ? "text-text" : "text-muted-foreground"}`}>
              {k}
            </span>
            <span className="text-micro leading-snug text-muted-foreground">{blurb}</span>
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

      <div className="space-y-1.5">
        <label className="text-label font-medium text-text">
          Description <span className="text-faint">(optional)</span>
        </label>
        <Input
          value={description}
          onChange={(e) => setDescription(e.target.value)}
          placeholder="What this engine does in the room"
        />
      </div>

      {error && <p className="text-micro text-[#f87171] leading-snug">{error}</p>}

      <div className="flex items-center gap-2">
        <Button variant="default" size="sm" onClick={submit} disabled={!canSubmit}>
          {submitting ? "Registering…" : "Invite engine"}
        </Button>
        <span className="text-micro text-muted-foreground">
          or <code className="font-mono">mycelium engine create</code> from the CLI
        </span>
      </div>
    </div>
  );
}

