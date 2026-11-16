// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * MOCK: the person's own widgets in the status rail, from the `[statusline]`
 * section of their config file.
 *
 * Each reads like every other cell in the rail: a quiet icon, then the value
 * and its label in one muted color. A widget that failed or hung shows a dot
 * in place of its value, and its tooltip says what went wrong. Clicking one
 * opens Settings at the status line, where the file and every widget's last
 * run are shown.
 */

import { CircleDot, HardDrive, MemoryStick, Type, Upload, type LucideIcon } from "lucide-react";
import { settingHref } from "@/lib/client-settings";
import { RUNS, WIDGETS, type StatusIcon, type StatusWidget, type WidgetRun } from "@/mocks/statusline";
import { StatusDot, StatusLink } from "@/components/status-items";

export const WIDGET_ICON: Record<StatusIcon, LucideIcon> = {
  memory: MemoryStick,
  disk: HardDrive,
  upload: Upload,
  ci: CircleDot,
  text: Type,
};

/** What a widget's tooltip says about its last run. */
export function RunDetail({ widget, run }: { widget: StatusWidget; run: WidgetRun }) {
  return (
    <span className="flex max-w-80 flex-col gap-1">
      {widget.command && <code className="font-mono text-[11px] break-all">{widget.command}</code>}
      {run.ok ? (
        <span className="text-muted-foreground">
          Ran {run.ran}. Runs every {widget.every}.
        </span>
      ) : (
        <>
          <span>{run.timedOut ? `Still running after ${widget.timeout}s.` : `Exited with ${run.exit}.`}</span>
          {run.error && <span className="text-muted-foreground">{run.error}</span>}
        </>
      )}
    </span>
  );
}

export function StatusWidgets() {
  if (!WIDGETS.length) return null;
  return (
    <>
      {WIDGETS.map((w, i) => {
        const run = RUNS[i];
        const Icon = WIDGET_ICON[w.icon ?? "text"];
        return (
          <StatusLink
            key={w.label}
            href={settingHref("general", "statusline")}
            tooltip={<RunDetail widget={w} run={run} />}
          >
            <Icon />
            {run.ok ? (
              <span className="tabular">
                {w.text ?? run.value} {w.label}
              </span>
            ) : (
              <>
                <StatusDot tone={run.timedOut ? "warn" : "bad"} />
                <span>{w.label}</span>
              </>
            )}
          </StatusLink>
        );
      })}
      <span aria-hidden className="hidden h-3 w-px flex-shrink-0 bg-border sm:block" />
    </>
  );
}
