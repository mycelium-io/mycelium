"use client";

import { useEffect, useState } from "react";
import { fetchChildRooms, fetchSessions } from "@/lib/api";

interface SessionRoom {
  name: string;
  coordination_state: string;
  created_at: string;
  parent_namespace: string;
  join_deadline: string | null;
}

interface AgentSession {
  agent_handle: string;
  intent: string | null;
  joined_at: string;
}

const stateColors: Record<string, string> = {
  idle: "bg-muted/40",
  waiting: "bg-yellow-500/20 text-yellow-400",
  negotiating: "bg-accent/20 text-accent",
  complete: "bg-emerald-500/20 text-emerald-400",
  failed: "bg-red-500/20 text-red-400",
};

function Countdown({ deadline }: { deadline: string }) {
  const [remaining, setRemaining] = useState("");

  useEffect(() => {
    const tick = () => {
      const secs = Math.max(0, Math.floor((new Date(deadline).getTime() - Date.now()) / 1000));
      setRemaining(secs > 0 ? `${secs}s` : "closing…");
    };
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, [deadline]);

  return <span className="text-[10px] text-yellow-400/70 font-mono tabular-nums">{remaining}</span>;
}

export function SessionsPanel({ roomName }: { roomName: string }) {
  const [sessions, setSessions] = useState<SessionRoom[]>([]);
  const [agents, setAgents] = useState<Record<string, AgentSession[]>>({});
  const [expanded, setExpanded] = useState<string | null>(null);

  useEffect(() => {
    const load = async () => {
      const rooms = await fetchChildRooms(roomName);
      setSessions(rooms);
      // Refresh agents for expanded session
      if (expanded) {
        const data = await fetchSessions(expanded);
        setAgents((prev) => ({ ...prev, [expanded]: data.sessions || [] }));
      }
    };
    load();
    const interval = setInterval(load, 3000);
    return () => clearInterval(interval);
  }, [roomName, expanded]);

  const toggleSession = async (sessionName: string) => {
    if (expanded === sessionName) {
      setExpanded(null);
      return;
    }
    setExpanded(sessionName);
    const data = await fetchSessions(sessionName);
    setAgents((prev) => ({ ...prev, [sessionName]: data.sessions || [] }));
  };

  if (sessions.length === 0) {
    return (
      <div className="px-4 py-3 text-xs text-muted">
        No sessions — spawn one with <code className="text-accent/70">mycelium session create</code>
      </div>
    );
  }

  return (
    <div className="px-4 py-2 space-y-1.5">
      {sessions.map((s) => {
        const shortId = s.name.split(":session:")[1] || s.name;
        const isExpanded = expanded === s.name;
        const agentList = agents[s.name] || [];

        return (
          <div key={s.name}>
            <button
              onClick={() => toggleSession(s.name)}
              className="w-full flex items-center gap-2 px-2.5 py-1.5 rounded-md hover:bg-white/5 transition-colors text-left"
            >
              <svg
                width="10" height="10" viewBox="0 0 10 10" fill="currentColor"
                className={`text-muted transition-transform ${isExpanded ? "rotate-90" : ""}`}
              >
                <path d="M3 1L8 5L3 9Z" />
              </svg>
              <code className="text-xs text-white/80 font-mono">{shortId}</code>
              <span className={`text-[10px] px-1.5 py-0.5 rounded-full font-mono ${stateColors[s.coordination_state] || "bg-muted/40"}`}>
                {s.coordination_state}
              </span>
              {s.coordination_state === "waiting" && s.join_deadline && (
                <Countdown deadline={s.join_deadline} />
              )}
            </button>

            {isExpanded && (
              <div className="ml-6 mt-1 space-y-1">
                {agentList.length === 0 ? (
                  <div className="text-[11px] text-muted">No agents joined</div>
                ) : (
                  agentList.map((a) => (
                    <div key={a.agent_handle} className="flex items-center gap-2 text-[11px]">
                      <span className="w-1.5 h-1.5 rounded-full bg-accent/60 shrink-0" />
                      <span className="font-mono text-white/70">{a.agent_handle}</span>
                      {a.intent && (
                        <span className="text-muted truncate">{a.intent}</span>
                      )}
                    </div>
                  ))
                )}
              </div>
            )}
          </div>
        );
      })}
    </div>
  );
}
