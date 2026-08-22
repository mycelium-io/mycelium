// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { BarChart3 } from "lucide-react";
import type { ReactNode } from "react";
import { useGlobalStatus } from "@/lib/use-status";
import { Tooltip } from "@/components/ui/tooltip";

/** A status-bar cell that navigates somewhere on click (editor footer style).
 *  The bar sits at the bottom of the viewport, so its tooltips open upward. */
export function StatusLink({ href, tooltip, children }: { href: string; tooltip?: string; children: ReactNode }) {
  return (
    <Tooltip content={tooltip} side="top">
      <Link
        href={href}
        className="flex items-center gap-1.5 rounded px-1.5 py-0.5 -my-0.5 transition-colors hover:bg-hairline hover:text-text"
      >
        {children}
      </Link>
    </Tooltip>
  );
}

/** A status-bar cell that fires an action on click. */
export function StatusButton({ onClick, tooltip, children }: { onClick: () => void; tooltip?: string; children: ReactNode }) {
  return (
    <Tooltip content={tooltip} side="top">
      <button
        type="button"
        onClick={onClick}
        className="flex items-center gap-1.5 rounded px-1.5 py-0.5 -my-0.5 transition-colors hover:bg-hairline hover:text-text"
      >
        {children}
      </button>
    </Tooltip>
  );
}

/** Global items shared by every screen's status bar: model, spend, health. */
export function GlobalStatusItems() {
  const { model, spend, healthy } = useGlobalStatus();
  const shortModel = model ? model.split("/").pop() : null;

  return (
    <>
      {shortModel && (
        <StatusLink href="/metrics" tooltip={model ?? undefined}>
          <span className="font-mono">{shortModel}</span>
        </StatusLink>
      )}
      {spend !== null && (
        <StatusLink href="/metrics" tooltip="Spend (session)">
          <span className="tabular">${spend.toFixed(2)}</span>
        </StatusLink>
      )}
      {/* Health only shows when unhealthy. */}
      {healthy === false && (
        <StatusLink href="/metrics" tooltip="Backend unreachable">
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
    <Tooltip content="Metrics" side="top">
      <Link
        href="/metrics"
        aria-current={active ? "page" : undefined}
        className={`flex items-center gap-1.5 rounded px-1.5 py-0.5 -my-0.5 transition-colors hover:bg-hairline hover:text-text ${
          active ? "text-text" : ""
        }`}
      >
        <BarChart3 className="size-3.5" />
        metrics
      </Link>
    </Tooltip>
  );
}
