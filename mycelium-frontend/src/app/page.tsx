"use client";

import { useEffect, useState } from "react";
import Image from "next/image";
import { fetchRooms } from "@/lib/api";
import { RoomCard } from "@/components/room-card";
import { CreateRoomDialog } from "@/components/create-room-dialog";

export default function Dashboard() {
  const [rooms, setRooms] = useState<any[]>([]);
  const [showCreate, setShowCreate] = useState(false);

  const load = () => fetchRooms().then(setRooms).catch(() => {});

  useEffect(() => {
    load();
    const interval = setInterval(load, 10000);
    return () => clearInterval(interval);
  }, []);

  return (
    <div className="min-h-screen p-8 max-w-6xl mx-auto">
      {/* Header */}
      <div className="flex items-center gap-4 mb-12">
        <Image src="/logo.png" alt="Mycelium" width={48} height={48} className="opacity-90" />
        <div>
          <h1 className="text-2xl font-bold">Mycelium</h1>
          <p className="text-sm text-muted">Multi-agent coordination + persistent memory</p>
        </div>
        <button
          onClick={() => setShowCreate(true)}
          className="ml-auto px-4 py-2 bg-accent/10 text-accent border border-accent/25 rounded-lg text-sm font-bold hover:bg-accent/20 hover:border-accent/40 transition-all"
        >
          + Create Room
        </button>
      </div>

      {/* Room grid */}
      {rooms.length === 0 ? (
        <div className="text-center text-muted/50 py-20">
          <p className="text-lg mb-2">No rooms yet</p>
          <p className="text-sm">Create a room to get started</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
          {rooms.map(room => (
            <RoomCard key={room.name} room={room} />
          ))}
        </div>
      )}

      <CreateRoomDialog open={showCreate} onClose={() => setShowCreate(false)} onCreated={load} />
    </div>
  );
}
