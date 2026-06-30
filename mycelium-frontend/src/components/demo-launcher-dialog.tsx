// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import { useRouter } from "next/navigation";
import {
  fetchDemoJob,
  fetchDemoScenarios,
  startDemo,
  type DemoScenario,
} from "@/lib/api";

interface Props {
  open: boolean;
  onClose: () => void;
}

/**
 * One-click "run a sample coordination" for non-technical users. Picks a
 * scenario, asks the backend to start it on the host runner, polls the
 * provisioning job, and routes into the live room when it's ready.
 *
 * This dialog is only rendered when the host runner is configured (the parent
 * gates on `fetchDemoScenarios() !== null`), so it assumes the feature is on.
 */
export function DemoLauncherDialog({ open, onClose }: Props) {
  const router = useRouter();
  const [scenarios, setScenarios] = useState<DemoScenario[]>([]);
  const [selected, setSelected] = useState<string>("");
  const [phase, setPhase] = useState<"pick" | "provisioning" | "failed">("pick");
  const [room, setRoom] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (!open) return;
    fetchDemoScenarios().then((list) => {
      if (!list) return;
      setScenarios(list);
      setSelected((cur) => cur || list.find((s) => s.default)?.id || list[0]?.id || "");
    });
  }, [open]);

  if (!open) return null;

  const reset = () => {
    setPhase("pick");
    setRoom(null);
    setError(null);
  };

  const handleClose = () => {
    reset();
    onClose();
  };

  const handleRun = async () => {
    setPhase("provisioning");
    setError(null);
    try {
      const { job_id, room: roomName } = await startDemo({ scenario: selected });
      setRoom(roomName);
      // Poll until the agents are live, then route into the room. Provisioning
      // an openclaw demo includes a gateway restart, so this can take ~30s.
      const poll = async () => {
        const job = await fetchDemoJob(job_id);
        if (!job) {
          setTimeout(poll, 1500);
          return;
        }
        if (job.status === "ready") {
          router.push(`/room/${encodeURIComponent(roomName)}`);
          return;
        }
        if (job.status === "failed") {
          setError(job.error || "provisioning failed");
          setPhase("failed");
          return;
        }
        setTimeout(poll, 1500);
      };
      poll();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to start demo");
      setPhase("failed");
    }
  };

  return (
    <div
      className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={handleClose}
    >
      <div
        className="w-[460px] rounded-xl border border-border bg-surface p-6 shadow-2xl"
        onClick={(e) => e.stopPropagation()}
      >
        <h2 className="mb-1 text-lg font-bold">Run a sample coordination</h2>
        <p className="mb-4 text-sm text-muted">
          Spins up real agents on the hub and lets them negotiate to consensus — no setup.
        </p>

        {phase === "pick" && (
          <>
            <label className="mb-1 block text-sm text-muted">Scenario</label>
            <select
              className="mb-4 w-full rounded-lg border border-border bg-bg px-3 py-2 text-sm font-mono focus:border-accent/50 focus:outline-none"
              value={selected}
              onChange={(e) => setSelected(e.target.value)}
            >
              {scenarios.map((s) => (
                <option key={s.id} value={s.id}>
                  {s.topic}
                  {s.default ? "  (recommended)" : ""}
                </option>
              ))}
            </select>
          </>
        )}

        {phase === "provisioning" && (
          <div className="mb-4 text-sm text-muted">
            <p className="text-accent">Provisioning{room ? ` ${room}` : ""}…</p>
            <p className="mt-1 text-micro text-dim">
              Creating the room and agents, then waking them to negotiate. This can take up to a
              minute.
            </p>
          </div>
        )}

        {phase === "failed" && error && (
          <p role="alert" className="mb-4 break-words text-sm text-red-400">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-3">
          <button
            onClick={handleClose}
            className="px-4 py-2 text-sm text-muted transition-colors hover:text-white"
          >
            {phase === "provisioning" ? "Close" : "Cancel"}
          </button>
          {phase !== "provisioning" && (
            <button
              onClick={phase === "failed" ? reset : handleRun}
              disabled={!selected}
              className="rounded-lg border border-accent/30 bg-accent/20 px-4 py-2 text-sm font-bold text-accent transition-all hover:bg-accent/30 disabled:opacity-50"
            >
              {phase === "failed" ? "Try again" : "Run"}
            </button>
          )}
          {phase === "provisioning" && room && (
            <button
              onClick={() => router.push(`/room/${encodeURIComponent(room)}`)}
              className="rounded-lg border border-accent/30 bg-accent/20 px-4 py-2 text-sm font-bold text-accent transition-all hover:bg-accent/30"
            >
              Watch now
            </button>
          )}
        </div>
      </div>
    </div>
  );
}
