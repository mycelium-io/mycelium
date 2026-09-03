// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { type AuthStatus, type CoordinationRoom, type IdentityStatus } from "@/lib/api";
import { useNetworkStatus } from "@/lib/room-data";
import { Skeleton } from "@/components/ui/skeleton";
import { Tooltip } from "@/components/ui/tooltip";

/** This room's SLIM channel status — the node it rides, who is present (SLIM
 *  members plus server-held `await` participants), episode state, and
 *  durable-inbox counters — plus the hub's posture: which SLIM channel identity
 *  tier is in force and whether the HTTP-API JWT gate is up. Scoped to the current
 *  room (the fabric-wide fleet view is the CLI's `mycelium network`). Read-only,
 *  polled, fail-soft.
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
  const { network: net, loading } = useNetworkStatus();
  const loaded = !loading;

  const coord = net?.coordination ?? null;
  const identity = net?.identity ?? null;
  const auth = net?.auth ?? null;
  const room: CoordinationRoom | null = coord?.rooms.find((r) => r.room === roomName) ?? null;
  const enabled = coord?.slim_enabled ?? false;

  if (layout === "rail") {
    if (loaded && !net) {
      return (
        <div className="flex items-center gap-1.5 px-4 py-2 text-micro text-muted-foreground">
          <StateDot color="var(--red)" /> SLIM · backend unreachable
        </div>
      );
    }
    const notes = railNotes(identity, auth);
    // Three groups, each on its own line behind a fixed label column: the node
    // this room rides, the hub's posture, and this room's own channel. The
    // stats used to run together as one wrapping strip, which put the label
    // column nowhere and let a group break across lines mid-thought.
    return (
      <div className="grid grid-cols-[4.5rem_minmax(0,1fr)] items-baseline gap-x-3 gap-y-1.5 px-4 py-2.5 text-micro">
        <RailGroup label="Node">
          <RailStat
            dot={coord ? (enabled ? "var(--green)" : "var(--red)") : "var(--yellow)"}
            value={coord?.endpoint ?? "…"}
            mono
          />
          <RailStat label="channels" value={coord?.channels_live ?? "—"} />
          <RailStat
            label="provisions"
            value={coord ? `${coord.provisions_ok}✓ / ${coord.provisions_failed}✗` : "—"}
          />
        </RailGroup>

        <RailGroup label="Posture">
          <Tooltip content={identity?.message} side="bottom">
            <span aria-description={identity?.message}>
              <RailStat
                dot={identity ? identityDot(identity) : undefined}
                label="identity"
                value={identity?.mode ?? "—"}
              />
            </span>
          </Tooltip>
          <Tooltip content={authDetail(auth)} side="bottom">
            <span aria-description={authDetail(auth)}>
              <RailStat
                dot={auth ? (auth.enabled ? "var(--green)" : "var(--faint)") : undefined}
                label="auth"
                value={auth ? (auth.enabled ? "on" : "off") : "—"}
              />
            </span>
          </Tooltip>
          {notes.map((n) => (
            <RailStat key={n.label} label={n.label} value={n.text} color={n.color} />
          ))}
        </RailGroup>

        <RailGroup label="Channel">
          <RailStat
            dot={room?.provisioned ? "var(--green)" : "var(--yellow)"}
            value={room ? (room.provisioned ? "live" : "pending") : loaded ? "none" : "…"}
          />
          <RailStat label="members" value={room?.members.length ?? 0} />
          <RailStat
            label="episode"
            value={room?.episode_active ? "active" : "idle"}
            color={room?.episode_active ? "var(--accent)" : undefined}
          />
          <RailStat
            label="deferred"
            value={room?.deferred_invites ?? 0}
            color={(room?.deferred_invites ?? 0) > 0 ? "var(--yellow)" : undefined}
          />
          {(room?.receive_errors ?? 0) > 0 && (
            <RailStat label="recv-err" value={room?.receive_errors ?? 0} color="var(--red)" />
          )}
        </RailGroup>
      </div>
    );
  }

  if (loaded && !net) {
    return <div className="p-6 text-label text-muted-foreground">Backend unreachable.</div>;
  }

  return (
    <div className="mx-auto flex max-w-2xl flex-col gap-6 p-6">
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

      {/* SLIM channel identity — the tier this hub's MLS members are minted
          under, and whether the tier it's set to actually stood up. */}
      <section className="overflow-hidden rounded-xl border border-border bg-surface/40">
        <SectionHeader
          title="Channel identity"
          dot={identityDot(identity)}
          dotLabel={identity?.status ?? "unknown"}
        />
        <div className="divide-y divide-border">
          <Stat label="Mode">
            <span className="font-mono text-text">{identity?.mode ?? "—"}</span>
          </Stat>
          <Stat label="State">
            <span style={{ color: identityDot(identity) }}>{identity?.message ?? "—"}</span>
          </Stat>
        </div>
      </section>

      {/* The HTTP-API JWT gate. It is off by default, so "open" is a fact about
          this hub rather than a fault. */}
      <section className="overflow-hidden rounded-xl border border-border bg-surface/40">
        <SectionHeader
          title="HTTP API auth"
          dot={auth ? (auth.enabled ? "var(--green)" : "var(--muted-foreground)") : "var(--yellow)"}
          dotLabel={auth ? (auth.enabled ? "gated" : "open") : "unknown"}
        />
        <div className="divide-y divide-border">
          <Stat label="Gate">
            <span className="text-text">{auth ? (auth.enabled ? "enabled" : "disabled") : "—"}</span>
          </Stat>
          {auth?.enabled && (
            <>
              <Stat label="Trusted issuers">
                {auth.issuers.length > 0 ? (
                  <div className="flex flex-wrap justify-end gap-1">
                    {auth.issuers.map((iss) => (
                      <span
                        key={iss}
                        className="rounded-full border border-border bg-surface px-2 py-0.5 font-mono text-micro text-text"
                      >
                        {iss}
                      </span>
                    ))}
                  </div>
                ) : (
                  <span style={{ color: "var(--red)" }}>none</span>
                )}
              </Stat>
              <Stat label="Audience">
                <span className="font-mono text-text">{auth.audience || "any"}</span>
              </Stat>
              <Stat label="Localhost bypass">
                <span className="text-text">{auth.localhost_bypass ? "on" : "off"}</span>
              </Stat>
            </>
          )}
          {(auth?.warnings?.length ?? 0) > 0 && (
            <div className="flex flex-col gap-1 px-4 py-2.5 text-label">
              {auth?.warnings?.map((w) => (
                <span key={w} style={{ color: "var(--yellow)" }}>
                  {w}
                </span>
              ))}
            </div>
          )}
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
            <Stat label="Deferred invites">
              <span
                className="tabular"
                style={{ color: room.deferred_invites > 0 ? "var(--yellow)" : "var(--text)" }}
              >
                {room.deferred_invites}
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

/** Dot color for the identity tier, mirroring `/health`'s own verdict — a
 *  `signerjwt` hub with no resolvable signing key/roster is degraded (or
 *  failing closed). The tier being selected is not the tier being in force,
 *  and the dot says which. */
function identityDot(identity: IdentityStatus | null): string {
  if (!identity) return "var(--yellow)";
  if (identity.status === "error") return "var(--red)";
  if (identity.status === "degraded") return "var(--yellow)";
  return "var(--green)";
}

/** The rail's second line: what the two posture stats can't say in one word. */
function railNotes(
  identity: IdentityStatus | null,
  auth: AuthStatus | null,
): { label: string; text: string; color?: string }[] {
  const notes: { label: string; text: string; color?: string }[] = [];
  if (identity && identity.status !== "ok") {
    notes.push({ label: "identity", text: identity.message, color: identityDot(identity) });
  }
  if (auth?.enabled) {
    notes.push({
      label: "trusts",
      text: auth.issuers.length > 0 ? auth.issuers.join(", ") : "no issuers configured",
      color: auth.issuers.length > 0 ? "var(--text)" : "var(--red)",
    });
    notes.push({ label: "audience", text: auth.audience || "any" });
  }
  for (const w of auth?.warnings ?? []) {
    notes.push({ label: "auth", text: w, color: "var(--yellow)" });
  }
  return notes;
}

/** Rail hover text for the auth gate: who it trusts and what the backend itself
 *  complains about, without widening the strip. */
function authDetail(auth: AuthStatus | null): string | undefined {
  if (!auth) return undefined;
  if (!auth.enabled) return "HTTP API auth gate disabled";
  const parts = [
    auth.issuers.length > 0 ? `issuers: ${auth.issuers.join(", ")}` : "no trusted issuers",
    `audience: ${auth.audience || "any"}`,
  ];
  if (auth.warnings?.length) parts.push(...auth.warnings);
  return parts.join(" · ");
}

function SectionHeader({ title, dot, dotLabel }: { title: string; dot: string; dotLabel: string }) {
  return (
    <div className="flex items-center gap-2 border-b border-border bg-paper px-4 py-2.5">
      <span className="text-label font-semibold text-text">{title}</span>
      <span className="ml-auto flex items-center gap-1.5 text-micro text-muted-foreground">
        <StateDot color={dot} />
        {dotLabel}
      </span>
    </div>
  );
}

/** A status dot. Drawn rather than typed: the ● glyph sat on the text baseline
 *  and picked up the font's own metrics, so it landed at a different height in
 *  every row it appeared in. */
function StateDot({ color, pulse = false }: { color: string; pulse?: boolean }) {
  return (
    <span
      aria-hidden
      className={`inline-block size-1.5 flex-shrink-0 rounded-full ${pulse ? "animate-pulse" : ""}`}
      style={{ background: color }}
    />
  );
}

/** One labeled line of the rail: a caps label in its own column, then the
 *  group's stats. The label column is fixed by the parent grid, so all three
 *  groups' stats start at the same x. */
function RailGroup({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <>
      <span className="caps-mono-sm text-faint">{label}</span>
      <span className="flex flex-wrap items-center gap-x-3 gap-y-1">{children}</span>
    </>
  );
}

/** One stat. The label is optional — the first stat in a group is the group's
 *  headline value and is already named by the group label beside it. */
function RailStat({
  label,
  value,
  dot,
  color,
  mono = false,
}: {
  label?: string;
  value: React.ReactNode;
  dot?: string;
  color?: string;
  mono?: boolean;
}) {
  return (
    <span className="flex items-center gap-1.5">
      {dot && <StateDot color={dot} />}
      {label && <span className="text-muted-foreground">{label}</span>}
      <span className={mono ? "font-mono text-text" : "tabular text-text"} style={{ color }}>
        {value}
      </span>
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
