// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * MOCK: the person's own widgets, from the `[statusline]` section of their
 * config file, in one of four places to compare (`?statusline=`):
 *
 * - `rail`: cells in the bottom status rail, the first round.
 * - `title`: short readouts in the title bar, the label on hover.
 * - `gauge`: one button in the title bar that opens them all in a panel.
 * - `sidebar`: a card at the foot of the rooms sidebar.
 *
 * The title bar already says "This computer" for the hub, so the panel and the
 * card are called "Widgets".
 *
 * A widget that failed or hung shows a dot in place of its value and says why
 * on hover. Clicking through opens Settings at the status line.
 */

import { useSyncExternalStore } from "react";
import Link from "next/link";
import { CircleDot, Gauge, HardDrive, MemoryStick, Type, Upload, type LucideIcon } from "lucide-react";
import { settingHref } from "@/lib/client-settings";
import { CONFIG_PATH, RUNS, WIDGETS, type StatusIcon, type StatusWidget, type WidgetRun } from "@/mocks/statusline";
import { StatusDot, StatusLink } from "@/components/status-items";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

export const WIDGET_ICON: Record<StatusIcon, LucideIcon> = {
  memory: MemoryStick,
  disk: HardDrive,
  upload: Upload,
  ci: CircleDot,
  text: Type,
};

type Placement = "rail" | "title" | "gauge" | "sidebar";

const subscribeNever = () => () => {};

function usePlacement(): Placement {
  return useSyncExternalStore(
    subscribeNever,
    () => (new URLSearchParams(window.location.search).get("statusline") as Placement | null) ?? "gauge",
    () => "gauge",
  );
}

const SETTINGS = settingHref("general", "statusline");

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

function Meter({ value }: { value: string }) {
  const pct = Math.max(0, Math.min(100, parseFloat(value)));
  return (
    <span aria-hidden className="h-1 w-full overflow-hidden rounded-full bg-hairline">
      <span className="block h-full rounded-full bg-accent/70" style={{ width: `${pct}%` }} />
    </span>
  );
}

const items = WIDGETS.map((w, i) => ({ w, run: RUNS[i], Icon: WIDGET_ICON[w.icon ?? "text"] }));
const failing = items.filter(({ run }) => !run.ok);

/** The bottom rail's cells: the first round. */
export function StatusWidgets() {
  if (usePlacement() !== "rail" || !items.length) return null;
  return (
    <>
      {items.map(({ w, run, Icon }) => (
        <StatusLink key={w.label} href={SETTINGS} tooltip={<RunDetail widget={w} run={run} />}>
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
      ))}
      <span aria-hidden className="hidden h-3 w-px flex-shrink-0 bg-border sm:block" />
    </>
  );
}

/** The title bar's share: short readouts, or one button that opens the panel. */
export function TitleWidgets() {
  const placement = usePlacement();
  if (!items.length) return null;
  if (placement === "title") {
    return (
      <div className="mr-2 flex items-center gap-0.5 border-r border-border pr-2">
        {items.map(({ w, run, Icon }) => (
          <Tooltip
            key={w.label}
            side="bottom"
            content={
              <span className="flex flex-col gap-1">
                <span className="font-medium">{w.label}</span>
                <RunDetail widget={w} run={run} />
              </span>
            }
          >
            <Link
              href={SETTINGS}
              className="flex h-7 items-center gap-1.5 rounded-md px-1.5 text-micro text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
            >
              <Icon className="size-3.5 text-faint" aria-hidden />
              {run.ok ? (
                <span className="flex flex-col items-stretch gap-0.5">
                  <span className="tabular">{w.text ?? run.value}</span>
                  {w.meter && run.value && <Meter value={run.value} />}
                </span>
              ) : (
                <StatusDot tone={run.timedOut ? "warn" : "bad"} />
              )}
            </Link>
          </Tooltip>
        ))}
      </div>
    );
  }
  if (placement === "gauge") {
    return (
      <Popover>
        <PopoverTrigger
          aria-label="Widgets"
          className="relative flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
        >
          <Gauge className="size-4" aria-hidden />
          {failing.length > 0 && (
            <span aria-hidden className="absolute top-1 right-1 size-1.5 rounded-full bg-red ring-2 ring-surface" />
          )}
        </PopoverTrigger>
        <PopoverContent className="w-80 p-0">
          <div className="flex items-center gap-2 border-b border-border px-3 py-2">
            <span className="text-label font-medium text-text">Widgets</span>
            <Link href={SETTINGS} className="ml-auto text-micro text-muted-foreground hover:text-text hover:underline">
              Edit widgets
            </Link>
          </div>
          <WidgetRows />
          <div className="border-t border-border px-3 py-2 font-mono text-[11px] text-faint">{CONFIG_PATH}</div>
        </PopoverContent>
      </Popover>
    );
  }
  return null;
}

/** The rooms sidebar's foot: a card of the widgets. */
export function SidebarWidgets() {
  if (usePlacement() !== "sidebar" || !items.length) return null;
  return (
    <div className="m-2 rounded-lg border border-border bg-surface">
      <Link
        href={SETTINGS}
        className="flex items-center gap-1.5 px-2.5 pt-2 pb-1 text-micro text-muted-foreground hover:text-text"
      >
        <Gauge className="size-3.5 text-faint" aria-hidden />
        Widgets
      </Link>
      <WidgetRows dense />
    </div>
  );
}

/** One row per widget: its icon and label, its value, a meter under it when
 *  it asks for one, and why it failed when it did. */
function WidgetRows({ dense = false }: { dense?: boolean }) {
  return (
    <ul className={dense ? "pb-1.5" : "py-1"}>
      {items.map(({ w, run, Icon }) => (
        <li key={w.label}>
          <Tooltip side="right" content={<RunDetail widget={w} run={run} />}>
            <div className={cn("flex flex-col gap-1", dense ? "px-2.5 py-1" : "px-3 py-1.5")}>
              <div className="flex items-center gap-2 text-label">
                <Icon className="size-3.5 flex-shrink-0 text-faint" aria-hidden />
                <span className="min-w-0 flex-1 truncate text-muted-foreground">{w.label}</span>
                {run.ok ? (
                  <span className="tabular text-text">{w.text ?? run.value}</span>
                ) : (
                  <span className="flex items-center gap-1.5 text-muted-foreground">
                    <StatusDot tone={run.timedOut ? "warn" : "bad"} />
                    {run.timedOut ? "Hung" : "Failed"}
                  </span>
                )}
              </div>
              {run.ok && w.meter && run.value && (
                <span className="flex pl-5.5">
                  <Meter value={run.value} />
                </span>
              )}
              {!run.ok && !dense && run.error && (
                <span className="truncate pl-5.5 text-micro text-faint">{run.error}</span>
              )}
            </div>
          </Tooltip>
        </li>
      ))}
    </ul>
  );
}
