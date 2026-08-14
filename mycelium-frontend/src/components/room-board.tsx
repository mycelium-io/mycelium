// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  fetchBoard,
  runBoardVerb,
  captureConcern,
  logFetchError,
  type BoardItem,
  type BoardOwner,
  type BoardVerb,
  type BoardWork,
} from "@/lib/api";
import { boardCounts, lensOf, type Lens } from "@/lib/board";
import {
  AlertTriangle,
  Ban,
  Bot,
  Check,
  CheckCircle2,
  ChevronRight,
  Circle,
  CircleDashed,
  Clock,
  CornerDownRight,
  Eye,
  GitBranch,
  GitPullRequest,
  Hand,
  ArrowUpRight,
  Plus,
  User,
  X,
} from "lucide-react";

interface Props {
  roomName: string;
  refreshTrigger: number;
}

const YOU = "you";

const LENSES: { id: Lens; label: string }[] = [
  { id: "needs", label: "Needs you" },
  { id: "flight", label: "In flight" },
  { id: "resolved", label: "Resolved" },
];

// Which verbs a row exposes, by source. Plan rows are read-mostly (resolve maps
// to a task toggle); a live episode is read-only (reply in the channel).
const VERBS_BY_SOURCE: Record<BoardItem["source"], BoardVerb[]> = {
  ledger: ["claim", "resolve", "block", "promote", "dismiss"],
  plan: ["resolve"],
  episode: [],
};

export function RoomBoard({ roomName, refreshTrigger }: Props) {
  const [items, setItems] = useState<BoardItem[]>([]);
  const [lens, setLens] = useState<Lens | "all">("needs");
  const [selected, setSelected] = useState<string | null>(null);
  const [expanded, setExpanded] = useState<Set<string>>(new Set());
  const [flash, setFlash] = useState<string | null>(null);
  const [capture, setCapture] = useState("");
  const captureRef = useRef<HTMLInputElement>(null);

  const load = useCallback(async () => {
    try {
      const board = await fetchBoard(roomName);
      setItems(board.items);
    } catch (err) {
      logFetchError("fetchBoard")(err);
    }
  }, [roomName]);

  useEffect(() => {
    load();
    const t = setInterval(load, 8000);
    return () => clearInterval(t);
  }, [load, refreshTrigger]);

  const counts = useMemo(() => boardCounts(items), [items]);

  // Drive a triage verb: optimistic local update for snap, then the real call
  // and a reload so the server projection is the source of truth.
  const verb = useCallback(
    async (name: BoardVerb, id: string, body?: { owner?: string; waiting_on?: string; issue?: number }) => {
      setItems((prev) =>
        prev.map((it) => {
          if (it.id !== id) return it;
          if (name === "resolve" || name === "promote") return { ...it, state: "resolved", needs_you: false };
          if (name === "block") return { ...it, state: "blocked", needs_you: true };
          if (name === "claim") return { ...it, state: "claimed", owner: { handle: body?.owner ?? YOU, kind: "human", present: true } };
          return it;
        }),
      );
      if (name === "dismiss") setItems((prev) => prev.filter((it) => it.id !== id));
      setFlash(
        name === "promote" ? `promoted ${short(id)} → filed a GitHub issue, dropped from the board` : `${name}ed ${short(id)}`,
      );
      const ok = await runBoardVerb(roomName, id, name, body);
      if (!ok) setFlash(`couldn't ${name} ${short(id)} — reloading`);
      await load();
    },
    [roomName, load],
  );

  const onCapture = useCallback(async () => {
    const text = capture.trim();
    if (!text) return;
    setCapture("");
    setFlash(`captured "${text}" → structured concern`);
    await captureConcern(roomName, text, YOU);
    await load();
  }, [capture, roomName, load]);

  // Keyboard-first triage: ⌘K / "/" focuses capture; single letters drive the
  // selected row's verbs (Linear-style). Ignored while typing in the capture bar.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const typing = document.activeElement === captureRef.current;
      if ((e.key === "k" && (e.metaKey || e.ctrlKey)) || (e.key === "/" && !typing)) {
        e.preventDefault();
        captureRef.current?.focus();
        return;
      }
      if (typing || !selected) return;
      const map: Record<string, BoardVerb> = { c: "claim", r: "resolve", b: "block", p: "promote", x: "dismiss" };
      const name = map[e.key.toLowerCase()];
      const item = items.find((it) => it.id === selected);
      if (name && item && VERBS_BY_SOURCE[item.source].includes(name)) {
        e.preventDefault();
        verb(name, selected);
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [selected, items, verb]);

  const shown = useMemo(
    () => (lens === "all" ? items : items.filter((it) => lensOf(it) === lens)),
    [items, lens],
  );

  return (
    <div className="flex h-full flex-col">
      {/* Header: summary line, lens tabs, capture bar */}
      <div className="shrink-0 border-b border-border bg-paper/60 px-6 pt-5 pb-3">
        <div className="flex items-baseline gap-2">
          <span
            className="text-text"
            style={{
              fontFamily: "var(--font-serif, 'Cormorant Garamond', Georgia, serif)",
              fontStyle: "italic",
              fontWeight: 600,
              fontSize: "1.9rem",
            }}
          >
            {roomName}
          </span>
          <span className="text-label text-muted-foreground">
            {counts.needs} need you · {counts.flight} in flight · {counts.resolved} resolved
          </span>
        </div>

        <div className="mt-3 flex flex-wrap items-center gap-2">
          <div className="flex items-center gap-0.5 rounded-lg border border-border bg-surface p-0.5">
            {LENSES.map((l) => {
              const active = lens === l.id;
              return (
                <button
                  key={l.id}
                  onClick={() => setLens(l.id)}
                  className={`flex items-center gap-1.5 rounded-md px-3 py-1 text-label font-medium transition-colors ${
                    active ? "bg-elevated text-text shadow-sm ring-1 ring-border" : "text-muted-foreground hover:bg-hairline hover:text-text"
                  }`}
                >
                  {l.label}
                  <span className={`text-micro tabular ${active ? "text-accent" : "text-muted-foreground"}`}>
                    {counts[l.id]}
                  </span>
                </button>
              );
            })}
            <button
              onClick={() => setLens("all")}
              className={`rounded-md px-3 py-1 text-label font-medium transition-colors ${
                lens === "all" ? "bg-elevated text-text shadow-sm ring-1 ring-border" : "text-muted-foreground hover:bg-hairline hover:text-text"
              }`}
            >
              All
            </button>
          </div>

          <div className="ml-auto flex min-w-[220px] flex-1 items-center gap-2 rounded-md border border-border bg-surface px-2.5 py-1.5 focus-within:ring-2 focus-within:ring-accent/40 sm:flex-none">
            <Plus className="size-3.5 text-muted-foreground" />
            <input
              ref={captureRef}
              value={capture}
              onChange={(e) => setCapture(e.target.value)}
              onKeyDown={(e) => e.key === "Enter" && onCapture()}
              placeholder="capture a concern…"
              className="w-full bg-transparent text-label text-text outline-none placeholder:text-muted-foreground"
            />
            <kbd className="rounded border border-border px-1 text-micro text-faint tabular">⌘K</kbd>
          </div>
        </div>

        {flash && (
          <div className="mt-2 flex items-center gap-2 text-micro text-muted-foreground">
            <span className="inline-block size-1.5 rounded-full bg-accent" />
            {flash}
          </div>
        )}
      </div>

      {/* Rows */}
      <div className="min-h-0 flex-1 overflow-y-auto">
        {shown.length === 0 ? (
          <div className="px-6 py-16 text-center text-label text-muted-foreground">
            Nothing here. The board self-heals — items land as events do, and resolve out on their own.
          </div>
        ) : (
          <ul className="divide-y divide-border/50">
            {shown.map((it) => (
              <BoardRow
                key={it.id}
                item={it}
                selected={selected === it.id}
                expanded={expanded.has(it.id)}
                onOpen={() => {
                  setSelected(it.id);
                  setExpanded((prev) => {
                    const next = new Set(prev);
                    if (next.has(it.id)) next.delete(it.id);
                    else next.add(it.id);
                    return next;
                  });
                }}
                onVerb={verb}
              />
            ))}
          </ul>
        )}
      </div>

      {/* Verb legend (mirrors the CLI footer) */}
      <div className="shrink-0 border-t border-border bg-paper/60 px-6 py-2 text-micro text-muted-foreground">
        <Legend k="c" label="claim" /> <Legend k="r" label="resolve" /> <Legend k="b" label="block" />{" "}
        <Legend k="p" label="promote→gh" /> <Legend k="x" label="dismiss" /> <Legend k="/" label="capture" />
        <span className="ml-2 text-faint">select a row, then press a key</span>
      </div>
    </div>
  );
}

function short(id: string): string {
  // Ledger ids are UUIDs; plan/episode ids are already short and prefixed.
  return id.includes(":") ? id : id.slice(0, 3);
}

function Legend({ k, label }: { k: string; label: string }) {
  return (
    <span className="mr-1 inline-flex items-center gap-1">
      <kbd className="rounded border border-border px-1 text-faint">{k}</kbd>
      <span>{label}</span>
    </span>
  );
}

// ── Row ──────────────────────────────────────────────────────────────────────

// The leading anchor + kind pill. State wins the anchor (a resolved decision
// reads as resolved, a blocked concern as blocked); kind drives the pill label.
const KIND_META: Record<string, { tone: string; label: string }> = {
  escalation: { tone: "var(--red)", label: "escalation" },
  decision: { tone: "var(--yellow)", label: "decision" },
  blocked: { tone: "var(--red)", label: "blocked" },
  review: { tone: "var(--accent)", label: "review" },
  action: { tone: "var(--muted-foreground)", label: "action" },
  concern: { tone: "var(--accent)", label: "concern" },
};

function anchorFor(item: BoardItem): { icon: typeof Circle; tone: string } {
  if (item.state === "resolved") return { icon: CheckCircle2, tone: "var(--green)" };
  // An agent-raised escalation is the loudest thing on the board.
  if (item.kind === "escalation") return { icon: Hand, tone: "var(--red)" };
  if (item.state === "blocked") return { icon: Ban, tone: "var(--red)" };
  if (item.state === "in_review" || item.kind === "review") return { icon: Eye, tone: "var(--accent)" };
  if (item.kind === "decision") return { icon: AlertTriangle, tone: "var(--yellow)" };
  if (item.state === "in_progress" || item.state === "claimed") return { icon: CircleDashed, tone: "var(--accent)" };
  return { icon: Circle, tone: "var(--accent)" };
}

function BoardRow({
  item,
  selected,
  expanded,
  onOpen,
  onVerb,
}: {
  item: BoardItem;
  selected: boolean;
  expanded: boolean;
  onOpen: () => void;
  onVerb: (name: BoardVerb, id: string, body?: { owner?: string; waiting_on?: string; issue?: number }) => void;
}) {
  const resolved = item.state === "resolved";
  const pillKey = item.state === "blocked" ? "blocked" : item.kind;
  const pill = KIND_META[pillKey] ?? KIND_META.action;
  const anchor = anchorFor(item);
  const Anchor = anchor.icon;
  const verbs = VERBS_BY_SOURCE[item.source];

  return (
    <>
      <li
        onClick={onOpen}
        className={`group flex cursor-pointer items-center gap-2.5 px-4 py-2.5 transition-colors hover:bg-hairline ${
          selected ? "bg-hairline" : ""
        } ${resolved ? "opacity-55" : ""}`}
        style={selected ? { boxShadow: "inset 2px 0 0 var(--accent)" } : undefined}
      >
        {/* Chevron — the expand affordance */}
        <ChevronRight
          className="size-3.5 shrink-0 text-faint transition-transform"
          style={expanded ? { transform: "rotate(90deg)", color: "var(--muted-foreground)" } : undefined}
        />

        {/* State anchor */}
        <Anchor className="size-4 shrink-0" style={{ color: anchor.tone }} />

        {/* Kind pill */}
        <span
          className="shrink-0 rounded px-1.5 py-px text-micro font-semibold uppercase tracking-wide"
          style={{ color: pill.tone, background: `color-mix(in srgb, ${pill.tone} 14%, transparent)` }}
        >
          {pill.label}
        </span>

        {/* Title — the object's name, dominant */}
        <span className={`truncate text-ui ${resolved ? "text-muted-foreground line-through" : "text-text"}`}>
          {item.title}
        </span>

        {/* Compact inline meta — quiet, right-aligned */}
        <div className="ml-auto flex shrink-0 items-center gap-2.5 text-micro text-muted-foreground">
          {/* An escalation leads with the agent that raised it and its ask. */}
          {item.escalated_by && (
            <span className="inline-flex items-center gap-1" style={{ color: "var(--red)" }}>
              <Bot className="size-3" />
              <span className="font-medium">{item.escalated_by}</span>
              {item.ask && <span className="text-muted-foreground">needs {item.ask}</span>}
            </span>
          )}
          {item.owner && <OwnerBadge owner={item.owner} />}
          {item.work?.ci && <CiDot ci={item.work.ci} />}
          {item.work?.pr && <span className="font-mono text-accent">PR#{item.work.pr.number}</span>}
          {item.waiting_on && <span className="text-yellow">⛔ {item.waiting_on}</span>}
          {item.ephemeral && item.expires_in && (
            <span className="inline-flex items-center gap-1 text-faint" title="transient — self-expires, no durable record here">
              <Clock className="size-3" />
              {item.expires_in}
            </span>
          )}
          {item.age && <span className="tabular text-faint">{item.age}</span>}
        </div>

        {/* Inline decision choices — act without opening */}
        {item.choices && !resolved && (
          <div className="flex shrink-0 items-center gap-1" onClick={(e) => e.stopPropagation()}>
            {item.choices.map((c) => (
              <button
                key={c}
                onClick={() => onVerb("resolve", item.id)}
                className="rounded-md border border-border bg-surface px-2 py-0.5 text-label font-medium text-text transition-colors hover:bg-elevated"
              >
                {c}
              </button>
            ))}
          </div>
        )}

        {/* One-gesture triage — on hover/selection, per-source */}
        {!resolved && verbs.length > 0 && (
          <div
            className={`flex shrink-0 items-center gap-0.5 transition-opacity ${
              selected ? "opacity-100" : "opacity-0 group-hover:opacity-100"
            }`}
            onClick={(e) => e.stopPropagation()}
          >
            {verbs.includes("claim") && <RowAction icon={Hand} title="claim" onClick={() => onVerb("claim", item.id, { owner: YOU })} />}
            {verbs.includes("resolve") && <RowAction icon={Check} title="resolve" onClick={() => onVerb("resolve", item.id)} />}
            {verbs.includes("block") && <RowAction icon={Ban} title="block" onClick={() => onVerb("block", item.id)} />}
            {verbs.includes("promote") && <RowAction icon={ArrowUpRight} title="promote → GitHub issue" onClick={() => onVerb("promote", item.id)} />}
            {verbs.includes("dismiss") && <RowAction icon={X} title="dismiss" onClick={() => onVerb("dismiss", item.id)} />}
          </div>
        )}
      </li>

      {expanded && <ExpandedDetail item={item} />}
    </>
  );
}

/** Detail-on-demand: provenance, dependencies, work, activity — the context the
 *  row hides until you ask for it. Progressive disclosure, not navigation. */
function ExpandedDetail({ item }: { item: BoardItem }) {
  const created = item.created_at ? new Date(item.created_at) : null;
  return (
    <li className="border-l-2 border-accent/40 bg-bg/40 px-6 py-3 pl-11">
      {item.detail && <p className="mb-2 text-body text-text">{item.detail}</p>}

      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1 text-label">
        <Field label="id" value={<span className="font-mono text-micro text-muted-foreground">{item.id}</span>} />
        <Field label="source" value={item.source} />
        <Field label="state" value={item.state.replace("_", " ")} />
        {item.escalated_by && (
          <Field
            label="escalated by"
            value={
              <span className="inline-flex items-center gap-1" style={{ color: "var(--red)" }}>
                <Bot className="size-3" />
                {item.escalated_by}
                {item.ask && <span className="text-muted-foreground">· needs {item.ask}</span>}
              </span>
            }
          />
        )}
        {item.ephemeral && (
          <Field
            label="lifespan"
            value={
              <span className="text-faint">
                transient{item.expires_in ? ` · expires in ${item.expires_in}` : ""} — no durable record, promote to keep
              </span>
            }
          />
        )}
        {item.owner && (
          <Field
            label="owner"
            value={
              <span className="inline-flex items-center gap-1">
                {item.owner.handle}
                <span className="text-faint">({item.owner.kind}{item.owner.present ? ", live" : ""})</span>
              </span>
            }
          />
        )}
        {item.provenance && <Field label="from" value={item.provenance} />}
        {created && (
          <Field
            label="opened"
            value={
              <span className="inline-flex items-center gap-1">
                <Clock className="size-3 text-faint" />
                {created.toLocaleString()} {item.age ? <span className="text-faint">· {item.age} ago</span> : null}
              </span>
            }
          />
        )}
        {item.waiting_on && <Field label="waiting on" value={<span className="text-yellow">{item.waiting_on}</span>} />}
        {item.blocks && (
          <Field
            label="blocks"
            value={
              <span className="inline-flex items-center gap-1">
                <CornerDownRight className="size-3" /> {item.blocks}
              </span>
            }
          />
        )}
        {item.work && (item.work.branch || item.work.pr || item.work.ci) && (
          <Field label="work" value={<span className="flex flex-wrap items-center gap-x-3 gap-y-1"><WorkLinks work={item.work} /></span>} />
        )}
        {item.github?.issue && (
          <Field
            label="github"
            value={
              <span className="inline-flex items-center gap-1 text-faint">
                <ArrowUpRight className="size-3" />#{item.github.issue}
                {item.github.state ? ` ${item.github.state}` : ""}
              </span>
            }
          />
        )}
        {item.note && <Field label="note" value={<span className="text-green">{item.note}</span>} />}
      </dl>

      {/* Affordances into the underlying work — display-only for now */}
      <div className="mt-2.5 flex flex-wrap items-center gap-2 text-label">
        {(item.kind === "decision" || item.kind === "review") && (
          <span className="inline-flex cursor-default items-center gap-1 text-accent">reply in channel ↗</span>
        )}
        {item.work?.pr && <span className="inline-flex cursor-default items-center gap-1 text-accent">open PR #{item.work.pr.number} ↗</span>}
        {item.source === "plan" && <span className="text-faint">from {item.provenance}</span>}
      </div>
    </li>
  );
}

function Field({ label, value }: { label: string; value: React.ReactNode }) {
  return (
    <>
      <dt className="text-micro uppercase tracking-wide text-faint">{label}</dt>
      <dd className="text-muted-foreground">{value}</dd>
    </>
  );
}

function CiDot({ ci }: { ci: NonNullable<BoardWork["ci"]> }) {
  const color = ci === "green" ? "var(--green)" : ci === "running" ? "var(--yellow)" : "var(--red)";
  return (
    <span className="inline-flex items-center gap-1 font-mono">
      <span className={`inline-block size-1.5 rounded-full ${ci === "running" ? "animate-pulse" : ""}`} style={{ background: color }} />
      <span className="text-faint">CI</span>
    </span>
  );
}

function RowAction({ icon: Icon, title, onClick }: { icon: typeof Hand; title: string; onClick: () => void }) {
  return (
    <button
      title={title}
      onClick={onClick}
      className="flex size-6 items-center justify-center rounded-md border border-transparent text-muted-foreground transition-colors hover:border-border hover:bg-elevated hover:text-text"
    >
      <Icon className="size-3.5" />
    </button>
  );
}

function OwnerBadge({ owner }: { owner: BoardOwner }) {
  const Icon = owner.kind === "agent" ? Bot : User;
  const color = owner.kind === "agent" ? "var(--accent)" : "var(--muted-foreground)";
  return (
    <span className="inline-flex items-center gap-1" style={{ color }}>
      <Icon className="size-3" />
      <span className="font-medium">{owner.handle}</span>
      {owner.present && (
        <span className="inline-block size-1.5 rounded-full bg-green" title="live in the room" aria-label="live" />
      )}
    </span>
  );
}

function WorkLinks({ work }: { work?: BoardWork | null }) {
  if (!work) return null;
  const ci = work.ci;
  const ciColor = ci === "green" ? "var(--green)" : ci === "running" ? "var(--yellow)" : "var(--red)";
  return (
    <>
      {work.branch && (
        <span className="inline-flex items-center gap-1 font-mono text-faint">
          <GitBranch className="size-3" />
          {work.branch}
        </span>
      )}
      {ci && (
        <span className="inline-flex items-center gap-1 font-mono">
          <span className={`inline-block size-1.5 rounded-full ${ci === "running" ? "animate-pulse" : ""}`} style={{ background: ciColor }} />
          <span className="text-faint">CI {ci}</span>
        </span>
      )}
      {work.pr && (
        <span className="inline-flex items-center gap-1 font-mono">
          <GitPullRequest className="size-3 text-accent" />
          <span className="text-accent">PR #{work.pr.number}</span>
          <span className="text-faint">{work.pr.state}</span>
        </span>
      )}
    </>
  );
}
