// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useEffect, useState } from "react";
import Link from "next/link";
import { fetchRooms, logFetchError } from "@/lib/api";
import { CreateRoomDialog } from "@/components/create-room-dialog";
import { MainTopBar } from "@/components/main-top-bar";
import { IDChip } from "@/components/id-chip";

interface Room {
  name: string;
  created_at: string;
  is_persistent: boolean;
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

  const load = () =>
    fetchRooms()
      .then((data: Room[]) => setRooms(data))
      .catch(logFetchError("fetchRooms"));

  useEffect(() => {
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-bg text-text">
      <MainTopBar
        activeTab="rooms"
        actions={
          <button
            onClick={() => setShowCreate(true)}
            className="flex items-center gap-2 border border-accent/40 bg-accent/[0.06] px-3 py-1.5 text-accent caps-mono-sm transition-colors hover:bg-accent/[0.12] hover:border-accent/60"
          >
            + NEW ROOM
          </button>
        }
      />

      <main className="flex flex-1 flex-col overflow-hidden">
        <TableHeader />
        <div className="flex-1 overflow-y-auto">
          {rooms.length === 0 ? (
            <div className="px-6 py-16 text-center italic text-muted">
              no rooms yet — create one to get started
            </div>
          ) : (
            rooms.map((room, i) => <RoomRow key={room.name} room={room} index={i} />)
          )}
        </div>
        <FooterCount visible={rooms} />
      </main>

      <CreateRoomDialog open={showCreate} onClose={() => setShowCreate(false)} onCreated={load} />
    </div>
  );
}

// ─── Table ────────────────────────────────────────────────────────────────────

const COL_TEMPLATE = "32px minmax(0, 1fr) 110px";

function TableHeader() {
  return (
    <div
      className="grid items-center gap-3 border-b border-border2 bg-paper px-6 py-2.5"
      style={{ gridTemplateColumns: COL_TEMPLATE }}
    >
      <span className="caps-mono-sm text-muted">#</span>
      <span className="caps-mono-sm text-muted">ROOM</span>
      <span className="caps-mono-sm text-muted">CREATED</span>
    </div>
  );
}

function RoomRow({ room, index }: { room: Room; index: number }) {
  return (
    <Link
      href={`/room/${encodeURIComponent(room.name)}`}
      className="grid cursor-pointer items-center gap-3 border-b border-border px-6 py-3 transition-colors hover:bg-white/[0.025]"
      style={{ gridTemplateColumns: COL_TEMPLATE }}
    >
      <span className="text-micro text-dim tabular">{String(index + 1).padStart(2, "0")}</span>

      <div className="flex min-w-0 items-center">
        <IDChip kind="room" name={room.name} />
      </div>

      <span className="text-label text-muted">{relativeTime(room.created_at)}</span>
    </Link>
  );
}

// ─── Footer count ─────────────────────────────────────────────────────────────

function FooterCount({ visible }: { visible: Room[] }) {
  return (
    <div className="flex flex-shrink-0 items-center gap-6 border-t border-border2 bg-paper px-6 py-2.5">
      <span className="caps-mono-sm text-muted">
        <span className="text-text font-semibold tabular">{visible.length}</span> rooms
      </span>
    </div>
  );
}
