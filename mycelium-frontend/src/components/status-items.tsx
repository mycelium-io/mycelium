// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3 } from "lucide-react";
import type { ReactNode } from "react";
import { useGlobalStatus } from "@/lib/use-status";

/** A status-bar cell that navigates somewhere on click (editor footer style). */
export function StatusLink({ href, title, children }: { href: string; title?: string; children: ReactNode }) {
  return (
    <Link
      href={href}
      title={title}
      className="flex items-center gap-1.5 rounded px-1.5 py-0.5 -my-0.5 transition-colors hover:bg-hairline hover:text-text"
    >
      {children}
    </Link>
  );
}

/** A status-bar cell that fires an action on click. */
export function StatusButton({ onClick, title, children }: { onClick: () => void; title?: string; children: ReactNode }) {
  return (
    <button
      type="button"
      onClick={onClick}
      title={title}
      className="flex items-center gap-1.5 rounded px-1.5 py-0.5 -my-0.5 transition-colors hover:bg-hairline hover:text-text"
    >
      {children}
    </button>
  );
}

/** Global items shared by every screen's status bar: model, spend, health. */
export function GlobalStatusItems() {
  const { model, spend, healthy } = useGlobalStatus();
  const shortModel = model ? model.split("/").pop() : null;

  return (
    <>
      {shortModel && (
        <StatusLink href="/metrics" title={model ?? undefined}>
          <span className="font-mono">{shortModel}</span>
        </StatusLink>
      )}
      {spend !== null && (
        <StatusLink href="/metrics" title="Spend (session)">
          <span className="tabular">${spend.toFixed(2)}</span>
        </StatusLink>
      )}
      {/* Health only shows when unhealthy. */}
      {healthy === false && (
        <StatusLink href="/metrics" title="Backend unreachable">
          <span className="flex items-center gap-1.5 text-red">
            <span className="inline-block size-1.5 rounded-full bg-red" />
            backend
          </span>
        </StatusLink>
      )}
    </>
  );
}

/** Metrics lives in the status bar, beside the model/spend cells that already
 *  deep-link into it — telemetry reads as a footer concern (editor-style), not
 *  a peer of the rooms in the navigation rail. */
export function MetricsStatusLink() {
  const pathname = usePathname();
  const active = pathname === "/metrics";
  return (
    <Link
      href="/metrics"
      title="Metrics"
      aria-current={active ? "page" : undefined}
      className={`flex items-center gap-1.5 rounded px-1.5 py-0.5 -my-0.5 transition-colors hover:bg-hairline hover:text-text ${
        active ? "text-text" : ""
      }`}
    >
      <BarChart3 className="size-3.5" />
      metrics
    </Link>
  );
}
