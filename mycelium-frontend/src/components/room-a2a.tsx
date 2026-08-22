// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { ArrowDownLeft, ArrowUpRight, ChevronRight } from "lucide-react";
import { useA2aBridge } from "@/lib/room-data";
import type { A2aBridgedAgent, A2aExchange } from "@/lib/api";

/** The A2A bridge strip in the Network pane — the room's off-channel traffic.
 *
 *  Everything else in this pane rides SLIM. A bridged agent doesn't: the hub
 *  calls it over HTTP and posts the reply back as that handle, so its turns
 *  would otherwise appear in the room with nothing here to explain them. This
 *  strip is that explanation — who is bridged, whether the room's own Agent Card
 *  is being read, and the last exchanges either way.
 *
 *  It renders nothing at all for a room with no bridge, so the pane keeps its
 *  shape for the common case. Collapsed it's one summary line; expanded it lists
 *  the agents, the exposure, and the recent exchanges.
 *
 *  The boundary cue is deliberate and load-bearing: a bridged agent is proxied,
 *  never a member of the room's MLS group, and the pane says so rather than
 *  letting proximity to the SLIM rail imply otherwise. */
export function RoomA2aView({ roomName }: { roomName: string }) {
  const { bridge } = useA2aBridge(roomName);
  const [open, setOpen] = useState(false);

  if (!bridge) return null;
  const { agents, exchanges, exposure } = bridge;
  const inboundSeen = exposure.card_fetches > 0 || exposure.messages > 0;
  if (agents.length === 0 && exchanges.length === 0 && !inboundSeen) return null;

  return (
    <div className="border-b border-border bg-surface/40" data-testid="room-a2a">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex w-full flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 text-left text-micro hover:bg-hairline"
      >
        <span className="flex items-center gap-1.5">
          <ChevronRight
            aria-hidden
            className={`size-3 text-muted-foreground transition-transform ${open ? "rotate-90" : ""}`}
          />
          <span className="text-muted-foreground">A2A bridge</span>
        </span>
        <Stat label="bridged">{agents.length}</Stat>
        <Stat label="calls">
          {bridge.outbound_ok}✓
          {bridge.outbound_failed > 0 && (
            <span style={{ color: "var(--red)" }}> / {bridge.outbound_failed}✗</span>
          )}
        </Stat>
        <Stat label="card">
          {exposure.card_fetches} read{exposure.card_fetches === 1 ? "" : "s"} ·{" "}
          {exposure.messages} in
        </Stat>
        <ProxiedBadge className="ml-auto" />
      </button>

      {open && (
        <div className="flex flex-col gap-3 border-t border-border px-4 py-3">
          {agents.length > 0 && (
            <div className="flex flex-col gap-2">
              {agents.map((agent) => (
                <BridgedAgentRow key={agent.handle} agent={agent} />
              ))}
            </div>
          )}

          <div className="text-micro text-muted-foreground">
            <span className="text-text">Exposed as an A2A agent.</span> Card served at{" "}
            <span className="break-all font-mono text-text">{exposure.card_url}</span>
            {exposure.skills.length > 0 && <> · skills: {exposure.skills.join(", ")}</>}
          </div>

          {exchanges.length > 0 && (
            <div className="flex flex-col gap-1">
              {exchanges
                .slice(-RECENT_EXCHANGES)
                .reverse()
                .map((exchange) => (
                  <ExchangeRow key={exchange.id} exchange={exchange} />
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}

/** Exchanges shown when expanded — a tail for context, not a log. */
const RECENT_EXCHANGES = 6;

function BridgedAgentRow({ agent }: { agent: A2aBridgedAgent }) {
  return (
    <div className="flex flex-wrap items-baseline gap-x-2 gap-y-0.5 text-micro">
      <span className="font-mono text-label font-semibold text-text">@{agent.handle}</span>
      <span className="break-all font-mono text-muted-foreground">
        {agent.endpoint ?? agent.card ?? "—"}
      </span>
      {agent.skills.length > 0 && (
        <span className="flex flex-wrap gap-1">
          {agent.skills.map((skill) => (
            <span
              key={skill}
              className="rounded-full border border-border bg-surface px-1.5 py-0 text-micro text-text"
            >
              {skill}
            </span>
          ))}
        </span>
      )}
      <span className="ml-auto tabular text-muted-foreground">
        {agent.calls_ok}✓
        {agent.calls_failed > 0 && (
          <span style={{ color: "var(--red)" }}> / {agent.calls_failed}✗</span>
        )}
      </span>
    </div>
  );
}

function ExchangeRow({ exchange }: { exchange: A2aExchange }) {
  const ok = exchange.status === "ok";
  const outbound = exchange.direction === "outbound";
  const Icon = outbound ? ArrowUpRight : ArrowDownLeft;
  // An answered call shows what came back; a failed one shows why, so silence in
  // the room reads here as a failed call rather than as nothing having happened.
  const text = ok ? exchange.reply || exchange.prompt : (exchange.detail ?? "no answer");
  return (
    <div className="flex items-baseline gap-2 text-micro">
      <Icon
        aria-hidden
        className="size-3 shrink-0 self-center"
        style={{ color: ok ? "var(--muted-foreground)" : "var(--red)" }}
      />
      <span className="font-mono text-text">@{exchange.handle}</span>
      {exchange.peer && <span className="text-muted-foreground">← @{exchange.peer}</span>}
      {exchange.duration_ms !== null && (
        <span className="tabular text-muted-foreground">{exchange.duration_ms}ms</span>
      )}
      <span className="truncate" style={{ color: ok ? "var(--text)" : "var(--red)" }}>
        {text}
      </span>
      <span className="ml-auto shrink-0 tabular text-muted-foreground">
        {exchange.at.slice(11, 19)}
      </span>
    </div>
  );
}

/** The honest cue: bridged agents are proxied by the hub over HTTP — they hold
 *  no group key, so they are not members of the room's encrypted group. */
function ProxiedBadge({ className = "" }: { className?: string }) {
  return (
    <span
      className={`rounded-md border border-border bg-surface px-1.5 py-0 text-micro text-muted-foreground ${className}`}
      title="Bridged over HTTP by the hub: proxied, not a member of the room's MLS group — the hub sees this traffic in plaintext."
    >
      proxied · not in the MLS group
    </span>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <span className="flex items-center gap-1.5">
      <span className="text-muted-foreground">{label}</span>
      <span className="tabular text-text">{children}</span>
    </span>
  );
}
