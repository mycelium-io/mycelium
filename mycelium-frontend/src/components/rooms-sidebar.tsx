// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import Image from "next/image";
import { BarChart3, Boxes, Plus, Search, SearchX } from "lucide-react";
import { fetchRooms, logFetchError } from "@/lib/api";
import { CreateRoomDialog } from "@/components/create-room-dialog";
import { ThemeToggle } from "@/components/theme-toggle";
import { EmptyState } from "@/components/empty-state";

interface Room {
  name: string;
  created_at: string;
  is_persistent: boolean;
}

/** Two-letter monogram from a room name (mirrors the agent avatars). */
function monogram(name: string): string {
  const parts = name.split(/[^a-z0-9]+/i).filter(Boolean);
  const s = parts.length >= 2 ? parts[0][0] + parts[1][0] : (parts[0] ?? name).slice(0, 2);
  return s.toUpperCase();
}

interface Props {
  /** The room currently open, so its row is highlighted. Null on the home view. */
  activeRoom?: string | null;
}

export function RoomsSidebar({ activeRoom = null }: Props) {
  const [rooms, setRooms] = useState<Room[]>([]);
  const [query, setQuery] = useState("");
  const [showCreate, setShowCreate] = useState(false);

  const load = () =>
    fetchRooms().then((data: Room[]) => setRooms(data)).catch(logFetchError("fetchRooms"));

  useEffect(() => {
    load();
    const t = setInterval(load, 10_000);
    return () => clearInterval(t);
  }, []);

  const filtered = useMemo(() => {
    const q = query.trim().toLowerCase();
    return q ? rooms.filter(r => r.name.toLowerCase().includes(q)) : rooms;
  }, [rooms, query]);

  return (
    <aside className="flex w-[236px] flex-shrink-0 flex-col border-r border-border bg-surface/50">
      {/* Brand */}
      <Link
        href="/"
        className="flex h-[52px] flex-shrink-0 items-center gap-2.5 border-b border-border px-4 transition-colors hover:bg-hairline"
      >
        <Image src="/logo.png" alt="Mycelium" width={20} height={20} className="opacity-90" />
        <span
          className="text-display leading-none text-text"
          style={{ fontFamily: "'Cormorant Garamond', Georgia, serif", fontStyle: "italic", fontWeight: 600 }}
        >
          mycelium
        </span>
      </Link>

      {/* Rooms header + search */}
      <div className="flex items-center gap-2 px-3 pt-3 pb-2">
        <span className="text-micro font-semibold uppercase tracking-wide text-muted-foreground">Rooms</span>
        <span className="text-micro tabular text-faint">{rooms.length}</span>
        <button
          onClick={() => setShowCreate(true)}
          aria-label="New room"
          title="New room"
          className="ml-auto flex size-6 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-surface hover:text-text"
        >
          <Plus className="size-4" />
        </button>
      </div>
      <div className="px-3 pb-2">
        <div className="flex items-center gap-2 rounded-lg border border-border bg-bg px-2.5 py-1.5 focus-within:border-accent">
          <Search className="size-3.5 flex-shrink-0 text-faint" />
          <input
            value={query}
            onChange={e => setQuery(e.target.value)}
            placeholder="Filter rooms…"
            className="w-full bg-transparent text-label text-text placeholder:text-muted-foreground focus:outline-none"
          />
        </div>
      </div>

      {/* Rooms list */}
      <nav className="flex-1 overflow-y-auto px-2 pb-2">
        {filtered.length === 0 ? (
          rooms.length === 0 ? (
            <EmptyState size="sm" icon={Boxes} title="No rooms yet" description="Create one with the + above." />
          ) : (
            <EmptyState size="sm" icon={SearchX} title="No matches" />
          )
        ) : (
          filtered.map(room => {
            const active = room.name === activeRoom;
            return (
              <Link
                key={room.name}
                href={`/room/${encodeURIComponent(room.name)}`}
                className={`group flex items-center gap-2.5 rounded-lg px-2 py-1.5 transition-colors ${
                  active ? "bg-elevated ring-1 ring-border" : "hover:bg-hairline"
                }`}
              >
                <span
                  className={`flex size-7 flex-shrink-0 items-center justify-center rounded-md font-mono text-micro font-semibold ${
                    active ? "bg-accent text-accent-fg" : "bg-surface text-muted-foreground group-hover:text-text"
                  }`}
                  aria-hidden
                >
                  {monogram(room.name)}
                </span>
                <span className={`truncate text-label ${active ? "font-medium text-text" : "text-muted-foreground group-hover:text-text"}`}>
                  {room.name}
                </span>
              </Link>
            );
          })
        )}
      </nav>

      {/* Footer */}
      <div className="flex items-center gap-1 border-t border-border px-3 py-2">
        <Link
          href="/metrics"
          className="flex items-center gap-2 rounded-md px-2 py-1.5 text-label font-medium text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
        >
          <BarChart3 className="size-4" />
          Metrics
        </Link>
        <div className="ml-auto">
          <ThemeToggle />
        </div>
      </div>

      <CreateRoomDialog open={showCreate} onClose={() => setShowCreate(false)} onCreated={load} />
    </aside>
  );
}
