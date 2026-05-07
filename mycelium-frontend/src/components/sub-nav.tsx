// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

"use client";

import Link from "next/link";
import type { ReactNode } from "react";
import { IDChip } from "./id-chip";

export interface Crumb {
  label: string;
  href?: string;
  /** Use IDChip rendering for room/session ids. Maps "rm:" → room, "ss:" → session. */
  sigil?: "rm:" | "ss:";
}

interface SubNavProps {
  crumbs: Crumb[];
  actions?: ReactNode;
}

export function SubNav({ crumbs, actions }: SubNavProps) {
  return (
    <div className="flex h-[40px] flex-shrink-0 items-center gap-3 border-b border-border bg-paper px-5 min-w-0">
      <div className="flex items-center gap-2 min-w-0 flex-1">
        {crumbs.map((c, i) => {
          const kind = c.sigil === "rm:" ? "room" : c.sigil === "ss:" ? "session" : null;
          const inner = kind
            ? <IDChip kind={kind} name={c.label} active={!c.href} />
            : <span className="font-mono text-label truncate" style={{ color: c.href ? "var(--text2)" : "var(--text)", fontWeight: 600 }}>{c.label}</span>;
          return (
            <span key={i} className="flex items-center gap-2 min-w-0">
              {i > 0 && <span className="text-dim caps-mono-sm flex-shrink-0">/</span>}
              {c.href
                ? <Link href={c.href} className="hover:opacity-80 transition-opacity min-w-0">{inner}</Link>
                : inner}
            </span>
          );
        })}
      </div>
      {actions && <div className="flex items-center gap-2 flex-shrink-0">{actions}</div>}
    </div>
  );
}
