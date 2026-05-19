// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import { useCallback, useEffect, useState } from "react";
import { fetchRoomAgents, fetchAgentManifest, type AgentSummary } from "@/lib/api";

interface Props {
  roomName: string;
}

/**
 * Read-only roster of the addressable agents registered in a room (the
 * `agents/<handle>` manifests). Pairs with the room chat box (@-mention to
 * invoke) and the event stream (agent replies are badged) to make the whole
 * register → list → invoke → reply loop visible in the UI.
 *
 * Registration / teardown are intentionally NOT here: both have spoke-local
 * side effects (cc-daemon manifest mirror, OpenClaw gateway config + restart)
 * that the hub cannot perform. That is the daemon-mediated provisioning
 * protocol, tracked separately — for now use `mycelium agent add` / `rm`.
 */
export function AgentsPanel({ roomName }: Props) {
  const [agents, setAgents] = useState<AgentSummary[]>([]);
  const [loaded, setLoaded] = useState(false);
  const [open, setOpen] = useState<string | null>(null);
  const [manifest, setManifest] = useState<Record<string, string | null>>({});

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

  const toggle = useCallback(
    (handle: string) => {
      setOpen((cur) => (cur === handle ? null : handle));
      if (manifest[handle] === undefined) {
        fetchAgentManifest(roomName, handle)
          .then((m) => setManifest((prev) => ({ ...prev, [handle]: m })))
          .catch(() => setManifest((prev) => ({ ...prev, [handle]: null })));
      }
    },
    [manifest, roomName],
  );

  return (
    <div className="flex h-full flex-col">
      <div className="flex flex-shrink-0 items-center gap-2 border-b border-border bg-paper px-4 py-2.5">
        <span className="caps-mono-sm text-muted">AGENTS</span>
        <span className="caps-mono-sm text-muted ml-auto tabular">
          {agents.length}
        </span>
      </div>

      <div className="flex-1 overflow-y-auto">
        {loaded && agents.length === 0 && (
          <div className="px-4 py-10 text-center text-micro text-muted italic leading-relaxed">
            no agents registered
            <br />
            <span className="text-dim">
              register one with{" "}
              <code className="text-mono-sm text-muted">mycelium agent add</code>
            </span>
          </div>
        )}

        {agents.map((a) => {
          const isOpen = open === a.handle;
          const body = manifest[a.handle];
          return (
            <div key={a.handle} className="border-b border-border last:border-b-0">
              <button
                type="button"
                onClick={() => toggle(a.handle)}
                className="w-full px-4 py-2.5 text-left transition-colors hover:bg-white/[0.025]"
              >
                <div className="flex items-baseline gap-2">
                  <span className="text-mono text-accent font-semibold truncate">
                    @{a.handle}
                  </span>
                  <span
                    className="caps-mono-sm flex-shrink-0"
                    style={{
                      color:
                        a.adapter === "openclaw"
                          ? "var(--green)"
                          : "var(--muted)",
                    }}
                  >
                    {a.adapter}
                  </span>
                  <span
                    aria-hidden
                    className="ml-auto text-micro text-muted font-mono"
                  >
                    {isOpen ? "−" : "+"}
                  </span>
                </div>
                {a.description && (
                  <div className="mt-1 text-micro text-muted leading-snug line-clamp-2">
                    {a.description}
                  </div>
                )}
              </button>

              {isOpen && (
                <div className="px-4 pb-3">
                  {body === undefined ? (
                    <div className="text-micro text-muted italic py-2">
                      loading manifest…
                    </div>
                  ) : body === null ? (
                    <div className="text-micro text-muted italic py-2">
                      manifest unavailable
                    </div>
                  ) : (
                    <pre className="text-mono-sm text-text2 bg-bg border border-border rounded p-2 overflow-x-auto whitespace-pre-wrap break-words">
                      {body}
                    </pre>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </div>

      <div className="flex-shrink-0 border-t border-border bg-paper px-4 py-2">
        <span className="text-micro text-dim leading-snug">
          @-mention an agent in the chat box to invoke it; replies are badged
          in the stream. Register/teardown is CLI-only for now.
        </span>
      </div>
    </div>
  );
}
