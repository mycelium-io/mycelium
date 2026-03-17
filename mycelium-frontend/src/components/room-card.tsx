"use client";

import Link from "next/link";

const modeColors: Record<string, string> = {
  sync: "bg-accent/10 text-accent border-accent/25",
  async: "bg-emerald-500/10 text-emerald-400 border-emerald-500/25",
  hybrid: "bg-purple-500/10 text-purple-400 border-purple-500/25",
};

const stateIndicator: Record<string, string> = {
  idle: "bg-muted",
  waiting: "bg-yellow-400 animate-pulse",
  negotiating: "bg-accent animate-pulse",
  complete: "bg-emerald-400",
  synthesizing: "bg-purple-400 animate-pulse",
};

interface RoomCardProps {
  room: {
    name: string;
    mode: string;
    coordination_state: string;
    created_at: string;
    is_persistent: boolean;
  };
}

export function RoomCard({ room }: RoomCardProps) {
  return (
    <Link href={`/room/${room.name}`}>
      <div className="group p-5 rounded-xl bg-surface border border-border hover:border-accent/30 transition-all cursor-pointer">
        <div className="flex items-start justify-between mb-3">
          <h3 className="font-bold text-lg font-mono group-hover:text-accent transition-colors">
            {room.name}
          </h3>
          <span className={`text-[10px] font-bold uppercase tracking-wider px-2 py-0.5 rounded-full border ${modeColors[room.mode] || modeColors.sync}`}>
            {room.mode}
          </span>
        </div>
        <div className="flex items-center gap-2 text-sm text-muted">
          <span className={`w-2 h-2 rounded-full ${stateIndicator[room.coordination_state] || stateIndicator.idle}`} />
          <span>{room.coordination_state}</span>
          {room.is_persistent && <span className="text-xs opacity-50">persistent</span>}
        </div>
        <div className="mt-2 text-xs text-muted/60">
          {room.created_at?.slice(0, 10)}
        </div>
      </div>
    </Link>
  );
}
