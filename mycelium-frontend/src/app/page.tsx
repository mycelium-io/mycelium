// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useEffect, useMemo, useState } from "react";
import Image from "next/image";
import Link from "next/link";
import { fetchRooms } from "@/lib/api";
import { CreateRoomDialog } from "@/components/create-room-dialog";

interface Room {
  name: string;
  coordination_state: string;
  created_at: string;
  parent_namespace: string | null;
  is_namespace: boolean;
  is_persistent: boolean;
}

const NAV_TABS = [
  { id: "rooms", label: "ROOMS", href: "/" },
  { id: "memory", label: "MEMORY" },
  { id: "agents", label: "AGENTS" },
  { id: "logs", label: "LOGS" },
];

const ACTIVITY_FILTERS: { id: string; label: string; predicate: (r: Room) => boolean }[] = [
  { id: "all", label: "all", predicate: () => true },
  { id: "negotiating", label: "negotiating", predicate: r => r.coordination_state === "negotiating" },
  { id: "waiting", label: "waiting", predicate: r => r.coordination_state === "waiting" },
  { id: "synthesizing", label: "synthesizing", predicate: r => r.coordination_state === "synthesizing" },
  { id: "complete", label: "complete", predicate: r => r.coordination_state === "complete" },
  { id: "idle", label: "idle", predicate: r => r.coordination_state === "idle" || !r.coordination_state },
];

const STATE_TONE: Record<string, "accent" | "muted" | "warn" | "ok"> = {
  negotiating: "accent",
  waiting: "warn",
  synthesizing: "accent",
  complete: "ok",
  idle: "muted",
  failed: "warn",
};

function namespaceOf(room: Room): string {
  if (room.parent_namespace) return room.parent_namespace;
  // Derive a namespace from the leftmost segment of the name.
  const slash = room.name.indexOf("/");
  if (slash > 0) return room.name.slice(0, slash);
  const colon = room.name.indexOf(":");
  if (colon > 0) return room.name.slice(0, colon);
  return room.name;
}

function relativeTime(iso: string): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const diff = Date.now() - t;
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "now";
  if (min < 60) return `${min}m ago`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h ago`;
  const d = Math.floor(hr / 24);
  if (d === 1) return "yesterday";
  if (d < 7) return `${d}d ago`;
  return new Date(iso).toISOString().slice(0, 10);
}

export default function Dashboard() {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [showCreate, setShowCreate] = useState(false);
  const [activity, setActivity] = useState("all");
  const [ns, setNs] = useState("all");

  const load = () =>
    fetchRooms()
      .then((data: Room[]) => setRooms(data.filter(r => r.is_namespace !== false)))
      .catch(() => {});

  useEffect(() => {
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  const namespaces = useMemo(() => {
    const counts = new Map<string, number>();
    for (const r of rooms) {
      const k = namespaceOf(r);
      counts.set(k, (counts.get(k) ?? 0) + 1);
    }
    return Array.from(counts.entries()).sort((a, b) => a[0].localeCompare(b[0]));
  }, [rooms]);

  const activityCounts = useMemo(() => {
    return ACTIVITY_FILTERS.map(f => [f.id, rooms.filter(f.predicate).length] as const);
  }, [rooms]);

  const visible = useMemo(() => {
    let out = rooms;
    const filter = ACTIVITY_FILTERS.find(f => f.id === activity);
    if (filter && activity !== "all") out = out.filter(filter.predicate);
    if (ns !== "all") out = out.filter(r => namespaceOf(r) === ns);
    return out;
  }, [rooms, activity, ns]);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg text-text">
      <TopBar onCreate={() => setShowCreate(true)} />

      <div className="flex flex-1 overflow-hidden">
        {/* ── Filter rail ──────────────────────────────────────────── */}
        <aside className="w-[220px] flex-shrink-0 overflow-y-auto border-r border-border bg-surface/60 py-4">
          <div className="px-4 pb-2">
            <span className="caps-mono-sm text-muted">ACTIVITY</span>
          </div>
          {ACTIVITY_FILTERS.map(({ id, label }) => {
            const count = activityCounts.find(([k]) => k === id)?.[1] ?? 0;
            const isActive = activity === id;
            return (
              <button
                key={id}
                onClick={() => setActivity(id)}
                className={`flex w-full items-center gap-2 px-3.5 py-1.5 text-left transition-colors ${
                  isActive ? "bg-white/[0.04] text-text" : "text-text2 hover:text-text"
                }`}
                style={{
                  borderLeft: `2px solid ${isActive ? "var(--accent)" : "transparent"}`,
                }}
              >
                <span
                  className={`square-dot ${isActive ? "filled" : ""}`}
                  style={{ width: 6, height: 6, color: isActive ? "var(--accent)" : "var(--muted)" }}
                />
                <span className="caps-mono-sm">{label.replace(/-/g, " ")}</span>
                <span className="ml-auto text-[10px] text-muted tabular">{count}</span>
              </button>
            );
          })}

          <div className="mt-4 border-t border-border px-4 pt-4 pb-2">
            <span className="caps-mono-sm text-muted">NAMESPACE</span>
          </div>
          <NamespaceButton id="all" label="all" count={rooms.length} active={ns === "all"} onClick={() => setNs("all")} />
          {namespaces.map(([n, c]) => (
            <NamespaceButton key={n} id={n} label={`${n}/`} count={c} active={ns === n} onClick={() => setNs(n)} />
          ))}
        </aside>

        {/* ── Body table ──────────────────────────────────────────── */}
        <main className="flex flex-1 flex-col overflow-hidden">
          <TableHeader />
          <div className="flex-1 overflow-y-auto">
            {visible.length === 0 ? (
              <div className="px-6 py-16 text-center italic text-muted">
                {rooms.length === 0 ? "no rooms yet — create one to get started" : "no rooms match this filter"}
              </div>
            ) : (
              visible.map((room, i) => <RoomRow key={room.name} room={room} index={i} />)
            )}
          </div>
          <FooterCount visible={visible} />
        </main>
      </div>

      <CreateRoomDialog open={showCreate} onClose={() => setShowCreate(false)} onCreated={load} />
    </div>
  );
}

// ─── Top bar (instrument-panel cells) ─────────────────────────────────────────

function TopBar({ onCreate }: { onCreate: () => void }) {
  return (
    <header className="flex h-[52px] flex-shrink-0 items-stretch border-b border-border2 bg-surface/80 backdrop-blur">
      <div className="flex items-center gap-3 border-r border-border px-5">
        <Image src="/logo.png" alt="Mycelium" width={22} height={22} className="opacity-90" />
        <span
          className="text-[20px] leading-none text-text"
          style={{ fontFamily: "'Cormorant Garamond', Georgia, serif", fontStyle: "italic", fontWeight: 600 }}
        >
          mycelium
        </span>
      </div>
      <nav className="flex items-stretch border-r border-border px-3">
        {NAV_TABS.map(t => {
          const active = t.id === "rooms";
          const className = `flex items-center px-3 caps-mono-sm transition-colors ${
            active ? "text-accent" : "text-text2/70 hover:text-text"
          }`;
          return t.href ? (
            <Link key={t.id} href={t.href} className={className}>
              {t.label}
            </Link>
          ) : (
            <span key={t.id} className={`${className} cursor-default`}>{t.label}</span>
          );
        })}
      </nav>
      <div className="flex flex-1 items-center justify-end gap-3 px-5">
        <button
          onClick={onCreate}
          className="flex items-center gap-2 border border-accent/40 bg-accent/[0.06] px-3 py-1.5 text-accent caps-mono-sm transition-colors hover:bg-accent/[0.12] hover:border-accent/60"
        >
          <span className="square-dot filled" style={{ width: 6, height: 6, color: "var(--accent)" }} />
          NEW ROOM
        </button>
      </div>
    </header>
  );
}

// ─── Filter rail item ─────────────────────────────────────────────────────────

function NamespaceButton({
  label, count, active, onClick,
}: { id: string; label: string; count: number; active: boolean; onClick: () => void }) {
  return (
    <button
      onClick={onClick}
      className={`flex w-full items-center gap-2 px-3.5 py-1.5 text-left transition-colors ${
        active ? "bg-white/[0.04] text-text" : "text-text2 hover:text-text"
      }`}
      style={{ borderLeft: `2px solid ${active ? "var(--accent)" : "transparent"}` }}
    >
      <span
        className="font-mono text-[11px] tabular"
        style={{ color: active ? "var(--text)" : "var(--text2)" }}
      >
        {label}
      </span>
      <span className="ml-auto text-[10px] text-muted tabular">{count}</span>
    </button>
  );
}

// ─── Table ────────────────────────────────────────────────────────────────────

const COL_TEMPLATE = "32px minmax(0, 1.6fr) 130px minmax(0, 1fr) 110px";

function TableHeader() {
  return (
    <div
      className="grid items-center gap-3 border-b border-border2 bg-surface/40 px-6 py-2.5"
      style={{ gridTemplateColumns: COL_TEMPLATE }}
    >
      <span className="caps-mono-sm text-muted">#</span>
      <span className="caps-mono-sm text-muted">ROOM</span>
      <span className="caps-mono-sm text-muted">STATE</span>
      <span className="caps-mono-sm text-muted">NAMESPACE</span>
      <span className="caps-mono-sm text-muted">CREATED</span>
    </div>
  );
}

function RoomRow({ room, index }: { room: Room; index: number }) {
  const tone = STATE_TONE[room.coordination_state] ?? "muted";
  const toneColor =
    tone === "accent" ? "var(--accent)" :
    tone === "ok"     ? "var(--green)" :
    tone === "warn"   ? "var(--yellow)" :
                        "var(--muted)";
  const pulse = tone === "accent" || tone === "warn";

  return (
    <Link
      href={`/room/${encodeURIComponent(room.name)}`}
      className="grid cursor-pointer items-center gap-3 border-b border-border px-6 py-3 transition-colors hover:bg-white/[0.025]"
      style={{ gridTemplateColumns: COL_TEMPLATE }}
    >
      <span className="text-[10px] text-dim tabular">{String(index + 1).padStart(2, "0")}</span>

      <div className="flex min-w-0 items-center gap-2.5">
        <span
          className="square-dot"
          style={{ color: "var(--muted)" }}
          aria-hidden
        />
        <span className="text-[10px] uppercase tracking-[0.08em] text-muted">rm:</span>
        <span className="truncate font-mono text-[12.5px] font-semibold text-text">
          {room.name}
        </span>
      </div>

      <div className="flex items-center gap-2">
        <span
          className={`square-dot filled ${pulse ? "pulse" : ""}`}
          style={{ width: 6, height: 6, color: toneColor }}
        />
        <span className="caps-mono-sm" style={{ color: toneColor }}>
          {room.coordination_state || "idle"}
        </span>
      </div>

      <span className="truncate text-[12px] text-text2 tabular">
        {namespaceOf(room)}/
      </span>

      <span className="text-[10.5px] text-muted">{relativeTime(room.created_at)}</span>
    </Link>
  );
}

// ─── Footer count ─────────────────────────────────────────────────────────────

function FooterCount({ visible }: { visible: Room[] }) {
  const namespaces = new Set(visible.map(namespaceOf)).size;
  return (
    <div className="flex flex-shrink-0 items-center gap-6 border-t border-border2 bg-surface/40 px-6 py-2.5">
      <span className="caps-mono-sm text-muted">
        <span className="text-text font-semibold tabular">{visible.length}</span> rooms
        <span className="mx-1.5 text-dim">·</span>
        <span className="text-text font-semibold tabular">{namespaces}</span> namespaces
      </span>
    </div>
  );
}
