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
  CircleDashed,
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
                onSelect={() => setSelected((s) => (s === it.id ? null : it.id))}
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

const KIND_META: Record<string, { icon: typeof AlertTriangle; tone: string; label: string }> = {
  decision: { icon: AlertTriangle, tone: "var(--yellow)", label: "decision" },
  blocked: { icon: Ban, tone: "var(--red)", label: "blocked" },
  review: { icon: Eye, tone: "var(--accent)", label: "review" },
  action: { icon: CircleDashed, tone: "var(--muted-foreground)", label: "action" },
  concern: { icon: AlertTriangle, tone: "var(--accent)", label: "concern" },
};

function BoardRow({
  item,
  selected,
  onSelect,
  onVerb,
}: {
  item: BoardItem;
  selected: boolean;
  onSelect: () => void;
  onVerb: (name: BoardVerb, id: string, body?: { owner?: string; waiting_on?: string; issue?: number }) => void;
}) {
  const resolved = item.state === "resolved";
  // A blocked row reads as blocked regardless of its underlying kind.
  const metaKey = item.state === "blocked" ? "blocked" : item.kind;
  const meta = resolved
    ? { icon: CheckCircle2, tone: "var(--green)", label: "resolved" }
    : KIND_META[metaKey] ?? KIND_META.action;
  const Icon = meta.icon;
  const verbs = VERBS_BY_SOURCE[item.source];

  return (
    <li
      onClick={onSelect}
      className={`group flex cursor-pointer gap-3 px-6 py-3 transition-colors hover:bg-hairline ${
        selected ? "bg-hairline ring-1 ring-inset ring-accent/40" : ""
      } ${resolved ? "opacity-60" : ""}`}
    >
      <Icon className="mt-0.5 size-4 shrink-0" style={{ color: meta.tone }} />

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span className="font-mono text-micro text-faint tabular">{short(item.id)}</span>
          <span
            className="rounded px-1.5 py-px text-micro font-medium"
            style={{ color: meta.tone, background: `color-mix(in srgb, ${meta.tone} 14%, transparent)` }}
          >
            {meta.label}
          </span>
          <span className={`text-body ${resolved ? "text-muted-foreground line-through" : "text-text"}`}>
            {item.title}
          </span>
        </div>

        {item.detail && <div className="mt-0.5 text-label text-muted-foreground">{item.detail}</div>}

        {/* Meta line: owner · work links · deps · provenance · age */}
        <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-micro text-muted-foreground">
          {item.owner && <OwnerBadge owner={item.owner} />}
          <WorkLinks work={item.work} />
          {item.blocks && (
            <span className="inline-flex items-center gap-1">
              <CornerDownRight className="size-3" /> blocks &ldquo;{item.blocks}&rdquo;
            </span>
          )}
          {item.waiting_on && <span>waiting on {item.waiting_on}</span>}
          {item.github?.issue && (
            <span className="inline-flex items-center gap-1 text-faint">
              <ArrowUpRight className="size-3" />#{item.github.issue}
              {item.github.state ? ` ${item.github.state}` : ""}
            </span>
          )}
          {item.provenance && <span className="text-faint">{item.provenance}</span>}
          {item.age && <span className="text-faint tabular">{item.age}</span>}
          {item.note && resolved && <span className="text-green">{item.note}</span>}
        </div>

        {/* Decision choices */}
        {item.choices && !resolved && (
          <div className="mt-2 flex flex-wrap items-center gap-1.5">
            {item.choices.map((c) => (
              <button
                key={c}
                onClick={(e) => {
                  e.stopPropagation();
                  onVerb("resolve", item.id);
                }}
                className="rounded-md border border-border bg-surface px-2.5 py-1 text-label font-medium text-text transition-colors hover:bg-elevated"
              >
                {c}
              </button>
            ))}
            <button
              onClick={(e) => e.stopPropagation()}
              className="rounded-md px-2 py-1 text-label text-muted-foreground transition-colors hover:text-text"
            >
              reply ↗
            </button>
          </div>
        )}
      </div>

      {/* One-gesture triage — appears on hover/selection, per-source */}
      {!resolved && verbs.length > 0 && (
        <div
          className={`flex shrink-0 items-start gap-1 transition-opacity ${
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
