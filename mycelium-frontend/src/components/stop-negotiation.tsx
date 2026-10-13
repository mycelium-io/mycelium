// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Square } from "lucide-react";
import { stopNegotiation, type EpisodeSummary } from "@/lib/api";
import { useCurrentUser } from "@/components/current-user";
import { StatusButton } from "@/components/status-items";

/** Whether the aligner's negotiation is running now: an open episode with no
 *  flow. A conductor's run carries a flow, and isn't what Stop ends. */
export function alignerRunning(episodes: EpisodeSummary[] | null): boolean {
  return (episodes ?? []).some((ep) => (ep.subkind ?? ep.outcome) === "open" && !ep.flow);
}

/**
 * Stop, in the status rail beside "negotiating", while the aligner runs in the
 * room. The run ends before its next turn and posts one line saying who
 * stopped it; `onStopped` re-reads the room either way (a 409 means it had
 * already ended).
 */
export function StopNegotiation({
  roomName,
  episodes,
  onStopped,
}: {
  roomName: string;
  episodes: EpisodeSummary[] | null;
  onStopped: () => void;
}) {
  const { principal } = useCurrentUser();
  const [stopping, setStopping] = useState(false);
  if (!alignerRunning(episodes)) return null;

  const stop = async () => {
    if (stopping) return;
    setStopping(true);
    try {
      await stopNegotiation(roomName, principal.trim() || undefined);
    } catch {
      // Already ended: the re-read below shows it.
    } finally {
      setStopping(false);
      onStopped();
    }
  };

  return (
    <StatusButton onClick={() => void stop()} tooltip="Stop the negotiation" className="flex-shrink-0">
      <Square />
      {stopping ? "Stopping…" : "Stop"}
    </StatusButton>
  );
}
