// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useState } from "react";
import { Users } from "lucide-react";
import {
  fetchMessages,
  fetchRoomAgents,
  fetchRoomMembers,
  logFetchError,
  type AgentSummary,
  type PresenceMember,
} from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
import { Monogram } from "@/components/ui/monogram";
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

/** Subtext for a present member: live socket vs. a polling lease + last-seen age.
 *  Returns null when the handle isn't currently present (caller falls back). */
function presenceLabel(member?: PresenceMember): string | null {
  if (!member) return null;
  if (member.kind === "slim") return "connected";
  const age = member.last_seen ? relativeTime(member.last_seen) : null;
  return age ? `awaiting · seen ${age}` : "awaiting";
}

/**
 * Roster of who's in a room: the **people** (agent owners + anyone who's posted,
 * plus the handle you're acting as) and the **agents** (`agents/<handle>`
 * manifests). Pairs with the chat box (@-mention to invoke) and the event stream
 * (replies are badged) to make the whole register → list → invoke → reply loop
 * visible. Humans and agents share the monogram avatar, told apart by tint
 * (muted for people, accent for agents).
 *
 * Agent registration / teardown are intentionally NOT here: both have
 * spoke-local side effects (daemon manifest mirror, workspace assets) the hub
 * can't perform. Use `mycelium agent create` / `rm` and `mycelium engine
 * create` / `rm`.
 */
export function AgentsPanel({ roomName, refreshKey = 0 }: Props) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [posters, setPosters] = useState<string[]>([]);
  const [liveMembers, setLiveMembers] = useState<PresenceMember[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [mineOnly, setMineOnly] = useState(false);
  const [addTab, setAddTab] = useState<"agents" | "engines">("agents");
  const { principal } = useCurrentUser();

  const refresh = useCallback(() => {
    fetchRoomAgents(roomName)
      .then((a) => {
        setAgents(a);
        setLoaded(true);
      })
      .catch((err) => {
        logFetchError("fetchRoomAgents")(err);
        setLoaded(true);
      });
    // Human posters come from the transcript: a room chat post is a broadcast
    // from a handle that isn't a registered agent.
    fetchMessages(roomName, 200)
      .then((data) => {
        const msgs = Array.isArray(data) ? data : (data?.messages ?? []);
        setPosters(
          msgs
            .filter((m: { message_type?: string }) => m.message_type === "broadcast")
            .map((m: { sender_handle?: string }) => m.sender_handle ?? "")
            .filter(Boolean),
        );
      })
      .catch(logFetchError("fetchMessages"));
    // Live presence: SLIM-connected + server-held lease members. Catches handles
    // that joined via `mycelium await` without registering an agent manifest.
    fetchRoomMembers(roomName)
      .then(setLiveMembers)
      .catch(logFetchError("fetchRoomMembers"));
  }, [roomName]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30_000);
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
        <Dialog>
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
                Members are registered from the CLI, because registration has
                machine-local side effects (daemon manifest mirror, workspace
                assets) the web UI can&apos;t perform. This panel is read-only.
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
                    {"mycelium agent create <handle> --cwd ~/proj                 # claude_code\nmycelium agent create <handle> --adapter cursor --cwd ~/proj  # cursor"}
                  </pre>
                  <p className="text-micro text-muted-foreground mt-1 leading-snug">
                    Cold-spawned by the daemon on @-mention. claude_code is
                    proven; cursor is supported but less travelled. Add{" "}
                    <code className="font-mono">--owner &lt;you&gt; --team &lt;slug&gt;</code>{" "}
                    so the agent is attributed to you from creation.
                  </p>
                </section>
                <section>
                  <div className="text-label font-semibold text-text mb-1.5">
                    Cold-spawn agents also need the daemon
                  </div>
                  <pre className="font-mono text-micro text-muted-foreground bg-surface border border-border px-2.5 py-2 overflow-x-auto whitespace-pre-wrap break-words">
                    {"mycelium adapter add claude-code --step=daemon\nmycelium daemon subscribe <room>"}
                  </pre>
                  <p className="text-micro text-muted-foreground mt-1 leading-snug">
                    One daemon per host serves both claude_code and cursor
                    agents.
                  </p>
                </section>
              </div>
            ) : (
              <div className="space-y-6 mt-2">
                <section>
                  <div className="text-label font-semibold text-text mb-1.5">
                    Register and summon an engine
                  </div>
                  <pre className="font-mono text-micro text-muted-foreground bg-surface border border-border px-2.5 py-2 overflow-x-auto whitespace-pre-wrap break-words">
                    {'mycelium engine create aligner --kind aligner -r <room>\nmycelium engine invoke aligner "converge on <topic>"'}
                  </pre>
                  <p className="text-micro text-muted-foreground mt-1 leading-snug">
                    An engine is a first-party citizen of the room, run by the
                    backend when @-mentioned — not cold-spawned by the daemon,
                    a different runtime family from claude_code/cursor. The{" "}
                    <span className="text-text">aligner</span> mediates
                    negotiation to consensus; the{" "}
                    <span className="text-text">synthesizer</span> distills the
                    room to memory.
                  </p>
                </section>
              </div>
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
                <div
                  key={`person-${p.handle}`}
                  className="flex items-center gap-2.5 px-3 py-2.5 border-b border-border last:border-b-0"
                >
                  <Monogram handle={p.handle} color="var(--muted-foreground)" presence={presence?.kind} />
                  <div className="min-w-0 flex-1 leading-tight">
                    <div className="flex items-center gap-1.5">
                      <span className="font-mono text-label text-text font-semibold truncate leading-tight">
                        @{p.handle}
                      </span>
                      {p.you && (
                        <span className="text-micro text-accent font-medium">you</span>
                      )}
                    </div>
                    <div className="text-micro text-muted-foreground truncate leading-tight">
                      {presenceLabel(presence) ?? (p.owns ? "owner" : "posted here")}
                      {p.teams.length > 0 ? ` · ${p.teams.join(", ")}` : ""}
                    </div>
                  </div>
                </div>
              );
            })}
          </>
        )}

        {agents.length > 0 && <SectionLabel>Agents</SectionLabel>}
        {visibleAgents.map((a) => {
          const mine = principal !== "" && a.owner === principal;
          const presence = presenceMap.get(a.handle);
          return (
            <div
              key={`agent-${a.handle}`}
              className="flex items-center gap-2.5 px-3 py-2.5 border-b border-border last:border-b-0"
            >
              <Monogram handle={a.handle} presence={presence?.kind} />
              <div className="min-w-0 flex-1 leading-tight">
                <div className="flex items-center gap-1.5">
                  <span className="font-mono text-label text-text font-semibold truncate leading-tight">
                    {a.handle}
                  </span>
                  {a.owner && (
                    <span
                      className="font-mono text-micro truncate"
                      style={{ color: mine ? "var(--accent)" : "var(--muted-foreground)" }}
                      title={`owner: @${a.owner}`}
                    >
                      @{a.owner}
                    </span>
                  )}
                  {a.team && (
                    <span className="text-micro text-muted-foreground truncate" title={`team: ${a.team}`}>
                      · {a.team}
                    </span>
                  )}
                </div>
                <div className="text-micro text-muted-foreground truncate leading-tight">
                  {presenceLabel(presence) ??
                    (a.adapter === "engine" && a.kind ? `engine · ${a.kind}` : a.adapter)}
                  {presenceLabel(presence) ? "" : a.description ? ` · ${a.description}` : ""}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
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

