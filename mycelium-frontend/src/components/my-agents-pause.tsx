// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useMemo, useState } from "react";
import { Pause } from "lucide-react";
import { useSWRConfig } from "swr";
import { controlMyAgents } from "@/lib/api";
import type { PaletteCommand } from "@/lib/commands";
import { useMyPaused } from "@/lib/room-data";
import { usePrincipal } from "@/components/current-user";
import { useCommands } from "@/components/keymap-provider";
import { StatusButton } from "@/components/status-items";

/**
 * Pause or resume every agent you own, in every room, in one step: what you do
 * before bed and in the morning. Only your own agents, as the hub only lets an
 * agent's owner pause it.
 */
export function useMyAgentsPause() {
  const me = usePrincipal();
  const { paused, refresh } = useMyPaused();
  const { mutate } = useSWRConfig();
  const [busy, setBusy] = useState(false);

  const run = useCallback(
    async (verb: "pause" | "resume") => {
      if (!me || busy) return;
      setBusy(true);
      try {
        await controlMyAgents(verb, me);
      } finally {
        setBusy(false);
        refresh();
        // Every room's members read says who is paused; re-read the open ones.
        void mutate((key) => Array.isArray(key) && key[0] === "room" && key[2] === "members");
      }
    },
    [me, busy, refresh, mutate],
  );

  return {
    me,
    paused,
    busy,
    pause: useCallback(() => void run("pause"), [run]),
    resume: useCallback(() => void run("resume"), [run]),
  };
}

/**
 * The status rail's word while your agents are paused, and the way back: a
 * click resumes them all. Also puts "Pause my agents" and "Resume my agents"
 * in ⌘K, so stopping for the night is one step from anywhere.
 */
export function MyAgentsPause() {
  const { me, paused, busy, pause, resume } = useMyAgentsPause();

  const commands = useMemo<PaletteCommand[]>(
    () =>
      me
        ? [
            {
              id: "agents.pause-mine",
              title: "Pause my agents",
              group: "Agents",
              keywords: ["stop", "bed", "night", "hold"],
              run: pause,
            },
            {
              id: "agents.resume-mine",
              title: "Resume my agents",
              group: "Agents",
              keywords: ["start", "morning", "continue", "unpause"],
              run: resume,
            },
          ]
        : [],
    [me, pause, resume],
  );
  useCommands(commands);

  if (paused.length === 0) return null;
  const n = paused.length;
  return (
    <StatusButton
      onClick={resume}
      tooltip={`${n} of your agents ${n === 1 ? "is" : "are"} paused. Click to resume ${n === 1 ? "it" : "them"}.`}
      className="flex-shrink-0 text-yellow"
    >
      <Pause />
      {busy ? "Resuming…" : `${n} paused`}
    </StatusButton>
  );
}
