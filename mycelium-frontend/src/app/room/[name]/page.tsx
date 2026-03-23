"use client";

import { useParams, useRouter } from "next/navigation";
import { useEffect, useState, useCallback } from "react";
import Image from "next/image";
import { fetchRoom } from "@/lib/api";
import { EventStream } from "@/components/event-stream";
import { MemoryPanel } from "@/components/memory-panel";
import { SessionsPanel } from "@/components/sessions-panel";

export default function RoomPage() {
  const params = useParams();
  const router = useRouter();
  const roomName = params.name as string;
  const [room, setRoom] = useState<any>(null);
  const [memoryRefresh, setMemoryRefresh] = useState(0);

  useEffect(() => {
    fetchRoom(roomName).then(setRoom).catch(() => {});
  }, [roomName]);

  const handleMemoryChanged = useCallback(() => {
    setMemoryRefresh(n => n + 1);
  }, []);

  return (
    <div className="h-screen flex flex-col">
      {/* Header */}
      <div className="flex items-center gap-3 px-6 py-3 border-b border-border bg-surface/50 backdrop-blur-sm">
        <button onClick={() => router.push("/")} className="text-muted hover:text-white transition-colors">
          <svg width="20" height="20" viewBox="0 0 20 20" fill="none"><path d="M12 4L6 10L12 16" stroke="currentColor" strokeWidth="2" strokeLinecap="round"/></svg>
        </button>
        <Image src="/logo.png" alt="" width={24} height={24} className="opacity-70" />
        <h1 className="font-bold font-mono text-lg">{roomName}</h1>
        {room && (
          <span className="text-xs text-muted font-mono ml-2">
            {room.coordination_state}
          </span>
        )}
      </div>

      {/* Split layout */}
      <div className="flex-1 flex overflow-hidden">
        {/* Left: Event stream */}
        <div className="w-[60%] border-r border-border flex flex-col">
          <div className="px-4 py-2 border-b border-border">
            <span className="text-[10px] font-bold uppercase tracking-wider text-muted">Live Events</span>
          </div>
          <div className="flex-1 overflow-hidden">
            <EventStream roomName={roomName} onMemoryChanged={handleMemoryChanged} />
          </div>
        </div>

        {/* Right: Sessions + Memory */}
        <div className="w-[40%] flex flex-col">
          <div className="border-b border-border">
            <div className="px-4 py-2 border-b border-border">
              <span className="text-[10px] font-bold uppercase tracking-wider text-muted">Sessions</span>
            </div>
            <SessionsPanel roomName={roomName} />
          </div>
          <div className="flex-1 overflow-hidden flex flex-col">
            <MemoryPanel roomName={roomName} refreshTrigger={memoryRefresh} />
          </div>
        </div>
      </div>
    </div>
  );
}
