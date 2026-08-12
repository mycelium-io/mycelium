// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

interface Props {
  kind: "room" | "session";
  name: string;
  /** Optional dim/active state (active = chalk-white text) */
  active?: boolean;
  className?: string;
}

/**
 * Visual treatment for room and session identifiers.
 *
 * Just the name in mono; context (page, crumb position, sidebar header)
 * already tells the reader whether it's a room or a session. The `kind`
 * prop drives the title attribute for accessibility but no visual marker.
 */
export function IDChip({ kind, name, active, className }: Props) {
  return (
    <span
      className={`font-mono text-label truncate ${className ?? ""}`}
      title={kind}
      style={{ color: active === false ? "var(--text2)" : "var(--text)", fontWeight: 600 }}
    >
      {name}
    </span>
  );
}
