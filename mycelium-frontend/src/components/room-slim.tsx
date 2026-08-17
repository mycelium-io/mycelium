// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import {
  fetchCoordination,
  logFetchError,
  type CoordinationRoom,
  type CoordinationStatus,
} from "@/lib/api";
import { Skeleton } from "@/components/ui/skeleton";

/** This room's SLIM channel status — the node it rides, who is present (SLIM
 *  members plus server-held `await` participants), episode state, and
 *  durable-inbox counters. Scoped to the current room (the fabric-wide fleet view
 *  is the CLI's `mycelium network`). Read-only, polled, fail-soft.
 *
 *  `layout="rail"` renders a compact single-strip diagnostics bar — the top of
 *  the unified Network pane, above the L9 feed. `layout="full"` (default) is the
 *  stacked card view. */
export function RoomSlimView({
  roomName,
  layout = "full",
}: {
  roomName: string;
  layout?: "full" | "rail";
}) {
  const [coord, setCoord] = useState<CoordinationStatus | null>(null);
  const [loaded, setLoaded] = useState(false);

  useEffect(() => {
    let cancelled = false;
    const load = () =>
      fetchCoordination()
        .then((c) => {
          if (cancelled) return;
          setCoord(c);
          setLoaded(true);
        })
        .catch((err) => {
          logFetchError("fetchCoordination")(err);
          if (!cancelled) setLoaded(true);
        });
    load();
    const t = setInterval(load, 20_000);
    return () => {
      cancelled = true;
      clearInterval(t);
    };
  }, []);

  const room: CoordinationRoom | null = coord?.rooms.find((r) => r.room === roomName) ?? null;
  const enabled = coord?.slim_enabled ?? false;

  if (layout === "rail") {
    if (loaded && !coord) {
      return (
        <div className="flex items-center gap-1.5 px-4 py-2 text-micro text-muted-foreground">
          <span style={{ color: "var(--red)" }}>●</span> SLIM · backend unreachable
        </div>
      );
    }
    return (
      <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-4 py-2 text-micro">
        <RailStat
          dot={coord ? (enabled ? "var(--green)" : "var(--red)") : "var(--yellow)"}
          label="SLIM"
        >
          <span className="font-mono text-text">{coord?.endpoint ?? "…"}</span>
        </RailStat>
        <RailStat label="channels">{coord?.channels_live ?? "—"}</RailStat>
        <RailStat label="provisions">
          {coord ? `${coord.provisions_ok}✓ / ${coord.provisions_failed}✗` : "—"}
        </RailStat>
        <span className="h-3 w-px bg-border" aria-hidden />
        <RailStat
          dot={room?.provisioned ? "var(--green)" : "var(--yellow)"}
          label={`channel · ${roomName}`}
        >
          {room ? (room.provisioned ? "live" : "pending") : loaded ? "none" : "…"}
        </RailStat>
        <RailStat label="members">{room?.members.length ?? 0}</RailStat>
        <RailStat label="episode">
          <span style={{ color: room?.episode_active ? "var(--accent)" : undefined }}>
            {room?.episode_active ? "active" : "idle"}
          </span>
        </RailStat>
        <RailStat label="invites">
          <span style={{ color: (room?.pending_invites ?? 0) > 0 ? "var(--yellow)" : undefined }}>
            {room?.pending_invites ?? 0}
          </span>
        </RailStat>
        {(room?.receive_errors ?? 0) > 0 && (
          <RailStat label="recv-err">
            <span style={{ color: "var(--red)" }}>{room?.receive_errors}</span>
          </RailStat>
        )}
      </div>
    );
  }

  if (loaded && !coord) {
    return <div className="p-6 text-label text-muted-foreground">Backend unreachable.</div>;
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
      {/* SLIM node — the fabric this room's channel rides. */}
      <section className="overflow-hidden rounded-xl border border-border bg-surface/40">
        <SectionHeader
          title="SLIM node"
          dot={enabled ? "var(--green)" : "var(--red)"}
          dotLabel={coord ? (enabled ? "connected" : "disabled") : "offline"}
        />
        <div className="divide-y divide-border">
          <Stat label="Endpoint">
            <span className="font-mono text-text">{coord?.endpoint ?? "—"}</span>
          </Stat>
          <Stat label="Channels live">
            <span className="tabular text-text">{coord?.channels_live ?? "—"}</span>
          </Stat>
          <Stat label="Provisions">
            <span className="tabular text-text">
              {coord ? `${coord.provisions_ok} ok / ${coord.provisions_failed} failed` : "—"}
            </span>
          </Stat>
        </div>
      </section>

      {/* This room's channel. */}
      <section className="overflow-hidden rounded-xl border border-border bg-surface/40">
        <SectionHeader
          title={`Channel · ${roomName}`}
          dot={room?.provisioned ? "var(--green)" : "var(--yellow)"}
          dotLabel={room?.provisioned ? "provisioned" : "not provisioned"}
        />
        {!room ? (
          loaded ? (
            <div className="px-4 py-3 text-label text-muted-foreground">
              No live channel for this room yet.
            </div>
          ) : (
            <div className="flex flex-col gap-2.5 px-4 py-3.5">
              <Skeleton className="h-3 w-3/5" />
              <Skeleton className="h-3 w-2/5" />
            </div>
          )
        ) : (
          <div className="divide-y divide-border">
            <Stat label="Members present">
              {room.members.length > 0 ? (
                <div className="flex flex-wrap justify-end gap-1">
                  {room.members.map((m) => (
                    <span
                      key={m}
                      className="rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-micro text-text"
                    >
                      {m}
                    </span>
                  ))}
                </div>
              ) : (
                <span className="text-muted-foreground">none</span>
              )}
            </Stat>
            <Stat label="Episode">
              <span style={{ color: room.episode_active ? "var(--accent)" : undefined }} className="text-text">
                {room.episode_active ? "active" : "idle"}
              </span>
            </Stat>
            <Stat label="Pending invites">
              <span
                className="tabular"
                style={{ color: room.pending_invites > 0 ? "var(--yellow)" : "var(--text)" }}
              >
                {room.pending_invites}
              </span>
            </Stat>
            <Stat label="Durable inbox">
              <span className="tabular text-text">
                {room.reserves} re-served
                {room.receive_errors > 0 && (
                  <span style={{ color: "var(--red)" }}> · {room.receive_errors} recv-err</span>
                )}
              </span>
            </Stat>
          </div>
        )}
      </section>
    </div>
  );
}

function SectionHeader({ title, dot, dotLabel }: { title: string; dot: string; dotLabel: string }) {
  return (
    <div className="flex items-center gap-2 border-b border-border bg-paper px-4 py-2.5">
      <span className="text-label font-semibold text-text">{title}</span>
      <span className="ml-auto flex items-center gap-1.5 text-micro text-muted-foreground">
        <span style={{ color: dot }}>●</span>
        {dotLabel}
      </span>
    </div>
  );
}

function RailStat({
  label,
  dot,
  children,
}: {
  label: string;
  dot?: string;
  children: React.ReactNode;
}) {
  return (
    <span className="flex items-center gap-1.5">
      {dot && (
        <span style={{ color: dot }} aria-hidden>
          ●
        </span>
      )}
      <span className="text-muted-foreground">{label}</span>
      <span className="tabular text-text">{children}</span>
    </span>
  );
}

function Stat({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <div className="flex items-center justify-between gap-4 px-4 py-2.5">
      <span className="text-label text-muted-foreground">{label}</span>
      <div className="text-label">{children}</div>
    </div>
  );
}
