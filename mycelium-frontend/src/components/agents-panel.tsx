// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useRef, useState, useSyncExternalStore } from "react";
import { Check, ChevronDown, Users } from "lucide-react";
import { createEngine, registerA2aAgent, type EngineKind, type PresenceMember } from "@/lib/api";
import { useNetworkStatus, useRoomRoster } from "@/lib/room-data";
import { agentHandoffPrompt } from "@/lib/install";
import { Button } from "@/components/ui/button";
import { Chip } from "@/components/ui/chip";
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

/** A presence *note* to append after the role — only the part the avatar badge
 *  can't convey. A live SLIM socket is already the solid badge, so it adds
 *  nothing here (null); a polling lease adds "awaiting" + last-seen age. */
function presenceNote(member?: PresenceMember): string | null {
  if (!member || member.kind === "slim") return null;
  const age = member.last_seen ? relativeTime(member.last_seen) : null;
  return age ? `awaiting · seen ${age}` : "awaiting";
}

function subtext(...parts: (string | null | undefined | false)[]): string {
  return parts.filter(Boolean).join(" · ");
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
  const [mineOnly, setMineOnly] = useState(false);
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

        {people.length > 0 && (
          <>
            <SectionLabel count={people.length}>People</SectionLabel>
            {people.map((p) => {
              const memberPresence = presence.get(p.handle);
              const marked = highlight === p.handle;
              return (
                <div
                  key={`person-${p.handle}`}
                  ref={marked ? highlightRow : undefined}
                  className={`flex items-center gap-2.5 px-3 py-2 transition-colors hover:bg-hairline ${
                    marked ? "bg-accent/15" : ""
                  }`}
                >
                  <Monogram handle={p.handle} color="var(--avatar-neutral)" presence={memberPresence?.kind} />
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-1.5">
                      <span className="truncate font-mono text-label font-semibold text-text">
                        @{p.handle}
                      </span>
                      {p.you && <span className="text-micro font-medium text-accent">you</span>}
                    </div>
                    <div className="mt-0.5 truncate text-micro text-muted-foreground">
                      {subtext(
                        p.owns ? "owner" : "posted here",
                        presenceNote(memberPresence),
                        p.teams.length > 0 && p.teams.join(", "),
                      )}
                    </div>
                  </div>
                </div>
              );
            })}
          </>
        )}

        {agents.length > 0 && <SectionLabel count={visibleAgents.length}>Agents</SectionLabel>}
        {visibleAgents.map((a) => {
          const mine = principal !== "" && a.owner === principal;
          const memberPresence = presence.get(a.handle.toLowerCase());
          const marked = highlight === a.handle;
          return (
            <div
              key={`agent-${a.handle}`}
              ref={marked ? highlightRow : undefined}
              className={`flex items-center gap-2.5 px-3 py-2 transition-colors hover:bg-hairline ${
                marked ? "bg-accent/15" : ""
              }`}
            >
              <Monogram handle={a.handle} presence={memberPresence?.kind} />
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <span className="truncate font-mono text-label font-semibold text-text">
                    {a.handle}
                  </span>
                  {a.owner && (
                    <Tooltip content={`owner: @${a.owner}`}>
                      <span
                        className="truncate font-mono text-micro"
                        style={{ color: mine ? "var(--accent)" : "var(--muted-foreground)" }}
                        aria-description={`owner: @${a.owner}`}
                      >
                        @{a.owner}
                      </span>
                    </Tooltip>
                  )}
                  {a.team && (
                    <Tooltip content={`team: ${a.team}`}>
                      <span
                        className="truncate text-micro text-muted-foreground"
                        aria-description={`team: ${a.team}`}
                      >
                        · {a.team}
                      </span>
                    </Tooltip>
                  )}
                  {a.adapter === "a2a" && (
                    <span
                      className="inline-flex items-center rounded-md border border-accent/30 bg-accent-soft/40 px-1.5 py-0 text-micro font-medium text-accent"
                      title={a.a2a_endpoint ?? a.a2a_card ?? "external A2A agent"}
                    >
                      a2a
                    </span>
                  )}
                </div>
                <div className="mt-0.5 truncate text-micro text-muted-foreground">
                  {subtext(
                    a.adapter === "engine" && a.kind ? `engine · ${a.kind}` : a.adapter,
                    presenceNote(memberPresence),
                    a.adapter === "a2a" && a.a2a_skills && a.a2a_skills.length > 0
                      ? a.a2a_skills.join(", ")
                      : a.description,
                  )}
                </div>
              </div>
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

/** Small uppercase divider between the People and Agents groups, with a count. */
function SectionLabel({ children, count }: { children: React.ReactNode; count?: number }) {
  return (
    <div className="flex items-center gap-2 px-3 pt-4 pb-1 text-micro font-semibold uppercase tracking-wide text-faint">
      <span>{children}</span>
      {count !== undefined && <span className="font-normal tabular">{count}</span>}
    </div>
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
