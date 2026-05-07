// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useEffect, useMemo, useState } from "react";
import Link from "next/link";
import { fetchChildRooms } from "@/lib/api";

function sessionIdOf(sessionRoomName: string): string {
  return sessionRoomName.split(":").pop() ?? sessionRoomName;
}

interface Session {
  name: string;
  coordination_state: string;
  created_at: string;
  parent_namespace?: string | null;
}

const STATE_TONE: Record<string, "accent" | "muted" | "warn" | "ok"> = {
  negotiating: "accent",
  waiting: "warn",
  synthesizing: "accent",
  complete: "ok",
  idle: "muted",
  failed: "warn",
};

function relativeTime(iso: string): string {
  if (!iso) return "—";
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return "—";
  const diff = Date.now() - t;
  const min = Math.floor(diff / 60_000);
  if (min < 1) return "now";
  if (min < 60) return `${min}m`;
  const hr = Math.floor(min / 60);
  if (hr < 24) return `${hr}h`;
  const d = Math.floor(hr / 24);
  return `${d}d`;
}

function shortSessionName(name: string): string {
  // session names look like "<room>:session:<uuid>" — show the trailing chunk
  const colon = name.lastIndexOf(":");
  const tail = colon >= 0 ? name.slice(colon + 1) : name;
  return tail.length > 12 ? `${tail.slice(0, 8)}…${tail.slice(-3)}` : tail;
}

function toneVar(t: "accent" | "muted" | "warn" | "ok"): string {
  return t === "accent" ? "var(--accent)"
       : t === "ok"     ? "var(--green)"
       : t === "warn"   ? "var(--yellow)"
                        : "var(--muted)";
}

interface SessionsRailProps {
  roomName: string;
  activeSessionName?: string | null;
}

export function SessionsRail({ roomName, activeSessionName }: SessionsRailProps) {
  const [sessions, setSessions] = useState<Session[]>([]);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchChildRooms(roomName)
        .then((data: Session[]) => { if (!cancelled) { setSessions(data); setLoaded(true); } })
        .catch(() => { if (!cancelled) setLoaded(true); });
    load();
    const t = setInterval(load, 5000);
    return () => { cancelled = true; clearInterval(t); };
  }, [roomName]);

  const counts = useMemo(() => {
    const live = sessions.filter(s => s.coordination_state === "negotiating" || s.coordination_state === "waiting").length;
    const done = sessions.filter(s => s.coordination_state === "complete").length;
    return { total: sessions.length, live, done };
  }, [sessions]);

  return (
    <div className="flex h-full flex-col overflow-hidden bg-surface/40">
      {/* Pane header */}
      <div className="flex items-center gap-2 border-b border-border bg-paper px-4 py-2.5">
        <span className="caps-mono-sm text-muted">SESSIONS</span>
        <span className="ml-auto text-micro text-muted tabular">
          {counts.total}
          {counts.live > 0 && (
            <span className="text-accent"> · {counts.live} live</span>
          )}
        </span>
      </div>

      {/* Session list */}
      <div className="flex-1 overflow-y-auto py-1">
        {!loaded ? (
          <div className="px-4 py-8 text-center caps-mono-sm text-muted italic">loading…</div>
        ) : sessions.length === 0 ? (
          <div className="px-4 py-8 text-center caps-mono-sm text-muted italic">
            no sessions yet
          </div>
        ) : (
          sessions.map(s => {
            const tone = STATE_TONE[s.coordination_state] ?? "muted";
            const color = toneVar(tone);
            const pulse = tone === "accent" || tone === "warn";
            const isActive = s.name === activeSessionName;
            const sessionId = sessionIdOf(s.name);
            return (
              <Link
                key={s.name}
                href={`/room/${encodeURIComponent(roomName)}/session/${encodeURIComponent(sessionId)}`}
                className={`flex w-full flex-col gap-1 px-4 py-2 text-left transition-colors ${
                  isActive ? "bg-white/[0.04]" : "hover:bg-white/[0.02]"
                }`}
                style={{ borderLeft: `2px solid ${isActive ? "var(--accent)" : "transparent"}` }}
              >
                <div className="flex items-center gap-2">
                  <span
                    className={`square-dot filled ${pulse ? "pulse" : ""}`}
                    style={{ width: 6, height: 6, color }}
                  />
                  <span className={`font-mono text-label ${isActive ? "text-text" : "text-text2"} truncate`}>
                    {shortSessionName(s.name)}
                  </span>
                  <span className="ml-auto text-micro text-muted tabular">{relativeTime(s.created_at)}</span>
                </div>
                <div className="flex items-center gap-1.5 pl-3">
                  <span className="caps-mono-sm" style={{ color, fontSize: 'var(--text-micro)' }}>
                    {s.coordination_state || "idle"}
                  </span>
                </div>
              </Link>
            );
          })
        )}
      </div>
    </div>
  );
}
