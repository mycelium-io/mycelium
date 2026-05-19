// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchRoomAgents, type AgentSummary } from "@/lib/api";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from "@/components/ui/dialog";

interface Props {
  roomName: string;
}

/** Two-letter monogram from a handle: "backend-lead" → BL, "oc-test2" → OT,
 *  "main" → MA. Splits on non-alphanumerics, else first two chars. */
function initials(handle: string): string {
  const parts = handle.split(/[^a-z0-9]+/i).filter(Boolean);
  const s =
    parts.length >= 2
      ? parts[0][0] + parts[1][0]
      : (parts[0] ?? handle).slice(0, 2);
  return s.toUpperCase();
}

/** Adapter → ring/initials color (shared app palette). */
function adapterColor(adapter: string): string {
  return adapter === "openclaw" ? "var(--green)" : "var(--accent)";
}

/**
 * Read-only roster of the addressable agents registered in a room (the
 * `agents/<handle>` manifests). Pairs with the room chat box (@-mention to
 * invoke) and the event stream (agent replies are badged) to make the whole
 * register → list → invoke → reply loop visible in the UI.
 *
 * Registration / teardown are intentionally NOT here: both have spoke-local
 * side effects (cc-daemon manifest mirror, OpenClaw gateway config + restart)
 * that the hub cannot perform. Use `mycelium agent add` / `create` / `rm`.
 */
export function AgentsPanel({ roomName }: Props) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loaded, setLoaded] = useState(false);

  const refresh = useCallback(() => {
    fetchRoomAgents(roomName)
      .then((a) => {
        setAgents(a);
        setLoaded(true);
      })
      .catch(() => setLoaded(true));
  }, [roomName]);

  useEffect(() => {
    refresh();
    const t = setInterval(refresh, 30_000);
    return () => clearInterval(t);
  }, [refresh]);

  return (
    <div className="flex h-full flex-col overflow-hidden">
      <div className="flex items-center gap-3 border-b border-border bg-paper px-4 py-3 caps-mono-sm text-muted">
        <span className="text-text font-semibold tabular">{agents.length}</span>
        <span>agents</span>
        <Dialog>
          <DialogTrigger
            render={<Button variant="default" size="sm" className="ml-auto" />}
          >
            + add
          </DialogTrigger>
          <DialogContent className="sm:max-w-lg">
            <DialogHeader>
              <DialogTitle className="font-mono text-ui text-text">
                Add an agent
              </DialogTitle>
              <DialogDescription className="text-label text-muted leading-relaxed">
                Agents are registered from the CLI — registration has
                machine-local side effects (manifest mirror, OpenClaw gateway
                config) the web UI can&apos;t perform. This panel is read-only.
              </DialogDescription>
            </DialogHeader>
            <div className="space-y-6 mt-2">
              <section>
                <div className="caps-mono-sm text-muted mb-1.5">
                  Adopt agents you already have
                </div>
                <pre className="font-mono text-micro text-text2 bg-surface border border-border px-2.5 py-2 overflow-x-auto whitespace-pre-wrap break-words">
                  {"mycelium agent add"}
                </pre>
                <p className="text-micro text-muted mt-1 leading-snug">
                  Interactive picker — discovers your OpenClaw agents and wires
                  the chosen ones into a room.
                </p>
              </section>
              <section>
                <div className="caps-mono-sm text-muted mb-1.5">
                  Create a new agent
                </div>
                <pre className="font-mono text-micro text-text2 bg-surface border border-border px-2.5 py-2 overflow-x-auto whitespace-pre-wrap break-words">
                  {"mycelium agent create <handle> --cwd ~/proj      # Claude Code\nmycelium agent create <handle> --adapter openclaw  # OpenClaw"}
                </pre>
              </section>
              <section>
                <div className="caps-mono-sm text-muted mb-1.5">
                  Claude Code agents also need the daemon
                </div>
                <pre className="font-mono text-micro text-text2 bg-surface border border-border px-2.5 py-2 overflow-x-auto whitespace-pre-wrap break-words">
                  {"mycelium adapter add claude-code --step=daemon\nmycelium daemon subscribe <room>"}
                </pre>
              </section>
            </div>
          </DialogContent>
        </Dialog>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loaded && agents.length === 0 && (
          <div className="text-center caps-mono-sm text-muted italic py-10">
            no agents registered
            <div className="font-mono text-label text-text2 mt-3 normal-case tracking-normal not-italic">
              add one with{" "}
              <code className="bg-surface px-1.5 py-0.5 text-accent border border-border">
                mycelium agent add
              </code>
            </div>
          </div>
        )}

        {agents.map((a) => {
          const color = adapterColor(a.adapter);
          return (
            <div
              key={a.handle}
              className="flex items-center gap-2.5 px-3 py-2.5 border-b border-border last:border-b-0"
            >
              <div
                className="flex h-8 w-8 flex-shrink-0 items-center justify-center rounded-full bg-surface font-mono text-micro font-bold"
                style={{ border: `1.5px solid ${color}`, color }}
                aria-hidden
              >
                {initials(a.handle)}
              </div>
              <div className="min-w-0 flex-1 leading-tight">
                <div className="font-mono text-label text-text font-semibold truncate leading-tight">
                  {a.handle}
                </div>
                <div className="text-micro text-muted truncate leading-tight">
                  <span style={{ color }}>{a.adapter}</span>
                  {a.description ? ` · ${a.description}` : ""}
                </div>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
