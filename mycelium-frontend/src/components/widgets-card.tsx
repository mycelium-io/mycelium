// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The Widgets card at the foot of the rooms sidebar: the person's own widgets,
 * from `[statusline]` in this computer's config file, as the desktop app last
 * ran them (`lib/widgets.ts`). One row each: its icon and label, its value,
 * and a bar under it when it's a meter. One that failed or hung shows a dot
 * and says so; hovering any row says the command, when it ran, and how it
 * failed. The header opens Settings at the widgets.
 *
 * Nothing renders in a browser, or when there are no widgets: no card at all.
 */

import Link from "next/link";
import { CircleDot, Gauge, HardDrive, MemoryStick, Type, Upload, type LucideIcon } from "lucide-react";
import { settingHref } from "@/lib/client-settings";
import { StatusDot } from "@/components/status-items";
import { Tooltip } from "@/components/ui/tooltip";
import { relativeTime, useNow } from "@/lib/relative-time";
import { percent, useWidgets, widgetState, type Widget, type WidgetIcon } from "@/lib/widgets";

export const WIDGET_ICON: Record<WidgetIcon, LucideIcon> = {
  memory: MemoryStick,
  disk: HardDrive,
  upload: Upload,
  ci: CircleDot,
  text: Type,
};

export const WIDGETS_SETTINGS = settingHref("widgets");

/** What a widget's hover says: its command, when it last ran, and how it failed. */
export function RunDetail({ widget }: { widget: Widget }) {
  const now = useNow();
  const run = widget.run;
  if (widget.text !== null) return <span>Fixed text, from your config file.</span>;
  const ran = run?.ran_at ? relativeTime(Date.parse(run.ran_at), now) : null;
  return (
    <span className="flex max-w-80 flex-col gap-1">
      <code className="font-mono text-[11px] break-all">{widget.command}</code>
      {!run && <span className="text-muted-foreground">Hasn&apos;t run yet. Runs every {widget.every}.</span>}
      {run?.ok && (
        <span className="text-muted-foreground">
          Ran {ran}. Runs every {widget.every}.
        </span>
      )}
      {run && !run.ok && (
        <>
          <span>
            {run.timed_out
              ? `Still running after ${widget.timeout}s, so it was stopped.`
              : run.exit !== null
                ? `Exited with ${run.exit}.`
                : "Couldn't start."}
            {ran ? ` Ran ${ran}.` : ""}
          </span>
          {run.error && <span className="text-muted-foreground">{run.error}</span>}
        </>
      )}
    </span>
  );
}

function Meter({ value }: { value: number }) {
  return (
    <span aria-hidden className="h-1 w-full overflow-hidden rounded-full bg-hairline">
      <span className="block h-full rounded-full bg-accent/70" style={{ width: `${value}%` }} />
    </span>
  );
}

function WidgetRow({ widget }: { widget: Widget }) {
  const Icon = WIDGET_ICON[widget.icon] ?? Type;
  const state = widgetState(widget);
  const meter = widget.meter && state.kind === "value" ? percent(state.value) : null;
  return (
    <li>
      <Tooltip side="right" content={<RunDetail widget={widget} />}>
        <div className="flex flex-col gap-1 px-2.5 py-1">
          <div className="flex items-center gap-2 text-label">
            <Icon className="size-3.5 flex-shrink-0 text-faint" aria-hidden />
            <span className="min-w-0 flex-1 truncate text-muted-foreground">{widget.label}</span>
            {state.kind === "value" && <span className="max-w-[55%] truncate tabular text-text">{state.value}</span>}
            {state.kind === "waiting" && <span className="text-faint">…</span>}
            {(state.kind === "failed" || state.kind === "hung") && (
              <span className="flex items-center gap-1.5 text-muted-foreground">
                <StatusDot tone={state.kind === "hung" ? "warn" : "bad"} />
                {state.kind === "hung" ? "Hung" : "Failed"}
              </span>
            )}
          </div>
          {meter !== null && (
            <span className="flex pl-5.5">
              <Meter value={meter} />
            </span>
          )}
        </div>
      </Tooltip>
    </li>
  );
}

/** The card, or nothing: outside the desktop app, and with no widgets. */
export function WidgetsCard() {
  const data = useWidgets();
  if (!data || data.widgets.length === 0) return null;
  return (
    <div className="m-2 flex-shrink-0 rounded-lg border border-border bg-surface">
      <Link
        href={WIDGETS_SETTINGS}
        className="flex items-center gap-1.5 px-2.5 pt-2 pb-1 text-micro text-muted-foreground hover:text-text"
      >
        <Gauge className="size-3.5 text-faint" aria-hidden />
        Widgets
      </Link>
      <ul className="pb-1.5">
        {data.widgets.map((w, i) => (
          <WidgetRow key={`${i}-${w.label}`} widget={w} />
        ))}
      </ul>
    </div>
  );
}
