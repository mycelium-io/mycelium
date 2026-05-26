// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchSessions } from "@/lib/api";

interface Props {
  /** Session display name, e.g. ``my-room:session:abc12345`` */
  sessionRoom: string;
}

interface Participant {
  agent_handle: string;
  intent: string | null;
  joined_at?: string | null;
}

/** Two-letter monogram (mirrors AgentsPanel). */
function initials(handle: string): string {
  const parts = handle.split(/[^a-z0-9]+/i).filter(Boolean);
  const s =
    parts.length >= 2
      ? parts[0][0] + parts[1][0]
      : (parts[0] ?? handle).slice(0, 2);
  return s.toUpperCase();
}

/**
 * Read-only roster of agents participating in a coordination session — the
 * session-view counterpart to the room's AgentsPanel. Shows each
 * participant's handle plus their opening position (``intent``) so a
 * reviewer can see WHO came in with WHAT before the negotiation started.
 *
 * Participants join through ``mycelium session join`` (which the daemon also
 * issues during @-mention dispatch); registration is intentionally not in
 * the UI, mirroring AgentsPanel.
 */
export function ParticipantsPanel({ sessionRoom }: Props) {
  const [participants, setParticipants] = useState<Participant[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(() => {
    fetchSessions(sessionRoom)
      .then((data) => {
        setParticipants(data.participants ?? []);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [sessionRoom]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30_000);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center gap-3 border-b border-border bg-paper px-4 py-3 caps-mono-sm text-muted">
        <span className="text-text font-semibold tabular">{participants.length}</span>
        <span>participants</span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loaded && participants.length === 0 && (
          <div className="text-center caps-mono-sm text-muted italic py-10">
            no participants yet
            <div className="font-mono text-label text-text2 mt-3 normal-case tracking-normal not-italic">
              join with
              <div className="mt-2">
                <code className="bg-surface px-1.5 py-0.5 text-accent border border-border whitespace-nowrap">
                  mycelium session join
                </code>
              </div>
            </div>
          </div>
        )}

        {participants.map((p) => (
          <div
            key={p.agent_handle}
            className="flex items-start gap-2.5 px-3 py-2.5 border-b border-border last:border-b-0"
          >
            <div
              className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-surface font-mono text-micro font-bold mt-0.5"
              style={{ border: "1.5px solid var(--accent)", color: "var(--accent)" }}
              aria-hidden
            >
              {initials(p.agent_handle)}
            </div>
            <div className="min-w-0 flex-1 leading-tight">
              <div className="font-mono text-label text-text font-semibold truncate leading-tight">
                @{p.agent_handle}
              </div>
              {p.intent ? (
                <div className="text-micro text-muted italic mt-0.5 leading-snug line-clamp-2">
                  &ldquo;{p.intent}&rdquo;
                </div>
              ) : (
                <div className="text-micro text-muted italic mt-0.5 leading-tight">
                  no opening position
                </div>
              )}
            </div>
          </div>
        ))}
      </div>
    </div>
  );
}
