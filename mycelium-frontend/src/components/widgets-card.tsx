// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The Widgets card at the foot of the rooms sidebar: the person's own widgets,
 * from `[statusline]` in this computer's config file, as the desktop app last
 * ran them (`lib/widgets.ts`). One tile each, two to a line: its icon, label
 * and dot along the top, its value under them as inline markdown in its color,
 * and a bar when it has a meter. A long value takes a whole line. What a run
 * printed as JSON is drawn over the config's fields. One that failed or hung
 * shows that dot instead and says so; hovering any tile says the command, the
 * widget's own tooltip, when it ran, and how it failed. The header opens
 * Settings at the widgets.
 *
 * Nothing renders in a browser, or when there are no widgets: no card at all.
 */

import Link from "next/link";
import { Gauge } from "lucide-react";
import { settingHref } from "@/lib/client-settings";
import { StatusDot } from "@/components/status-items";
import { Tooltip } from "@/components/ui/tooltip";
import { InlineMarkdown } from "@/components/inline-markdown";
import { WidgetIcon } from "@/components/widget-icon";
import { relativeTime, useNow } from "@/lib/relative-time";
import { lookOf, useWidgets, widgetState, type Widget, type WidgetColor } from "@/lib/widgets";
import { cn } from "@/lib/utils";

export const WIDGETS_SETTINGS = settingHref("widgets");

/** A widget's color, as the theme's own: it colors the icon and the text. */
export const WIDGET_COLOR: Record<WidgetColor, string> = {
  accent: "text-accent",
  green: "text-green",
  yellow: "text-yellow",
  red: "text-red",
  muted: "text-muted-foreground",
};

/** A widget's tooltip: a few lines of inline markdown. */
function WidgetTooltip({ text }: { text: string }) {
  return (
    <span className="flex flex-col">
      {text.split("\n").map((line, i) => (
        <span key={i}>
          <InlineMarkdown text={line} />
        </span>
      ))}
    </span>
  );
}

/** What a widget's hover says: its command, its own tooltip, when it last ran,
 *  and how it failed. */
export function RunDetail({ widget }: { widget: Widget }) {
  const now = useNow();
  const run = widget.run;
  const { tooltip } = lookOf(widget);
  if (widget.text !== null) {
    return (
      <span className="flex max-w-80 flex-col gap-1">
        {tooltip && <WidgetTooltip text={tooltip} />}
        <span className={cn(tooltip && "text-muted-foreground")}>Fixed text, from your config file.</span>
      </span>
    );
  }
  const ran = run?.ran_at ? relativeTime(Date.parse(run.ran_at), now) : null;
  return (
    <span className="flex max-w-80 flex-col gap-1">
      <code className="font-mono text-[11px] break-all">{widget.command}</code>
      {tooltip && <WidgetTooltip text={tooltip} />}
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

/** A widget's value: its text as inline markdown, its own dot before it, and
 *  a failed or hung run's dot in place of both. */
export function WidgetValue({ widget, className }: { widget: Widget; className?: string }) {
  const state = widgetState(widget);
  const look = lookOf(widget);
  if (state.kind === "waiting") return <span className="text-faint">…</span>;
  if (state.kind === "failed" || state.kind === "hung") {
    return (
      <span className="flex flex-shrink-0 items-center gap-1.5 text-muted-foreground">
        <StatusDot tone={state.kind === "hung" ? "warn" : "bad"} />
        {state.kind === "hung" ? "Hung" : "Failed"}
      </span>
    );
  }
  return (
    <span className={cn("flex min-w-0 items-center gap-1.5", className)}>
      {look.state && <StatusDot tone={look.state} />}
      {state.value && (
        <span className={cn("truncate tabular", look.color ? WIDGET_COLOR[look.color] : "text-text")}>
          <InlineMarkdown text={state.value} />
        </span>
      )}
    </span>
  );
}

/** A value this long or longer gets the card's whole width rather than half,
 *  so a sentence wraps to a second line instead of being cut at once. */
const WIDE_AT = 10;

/** One widget, as a tile: its label above, its value below it at full size,
 *  and its bar under that. The value wraps to two lines before it's cut. The
 *  tile's one dot sits in its corner: a failed or hung run's, else its own. */
function WidgetTile({ widget }: { widget: Widget }) {
  const look = lookOf(widget);
  const state = widgetState(widget);
  const failed = state.kind === "failed" || state.kind === "hung";
  const tone = failed ? (state.kind === "hung" ? "warn" : "bad") : look.state;
  const color = look.color ? WIDGET_COLOR[look.color] : null;
  const wide = state.kind === "value" && state.value.replace(/[*`_]/g, "").length >= WIDE_AT;
  return (
    <li className={cn("min-w-0", wide && "col-span-2")}>
      <Tooltip side="right" content={<RunDetail widget={widget} />}>
        <div className="flex h-full flex-col gap-1 rounded-md border border-border bg-bg px-2 py-1.5">
          <div className="flex items-center gap-1.5 text-micro text-muted-foreground">
            <WidgetIcon name={look.icon} className={cn("size-3", color ?? "text-faint")} />
            <span className="min-w-0 flex-1 truncate">{widget.label}</span>
            {tone && <StatusDot tone={tone} />}
          </div>
          <div
            className={cn(
              "line-clamp-2 text-label break-words tabular",
              failed || state.kind === "waiting" ? "text-muted-foreground" : cn("font-medium", color ?? "text-text"),
            )}
          >
            {state.kind === "waiting" ? "…" : failed ? (state.kind === "hung" ? "Hung" : "Failed") : <InlineMarkdown text={state.value} />}
          </div>
          {look.meter !== null && !failed && <Meter value={look.meter} />}
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
    // The tiles are the boxes; the card around them is only its heading.
    <div className="flex-shrink-0 border-t border-border pt-1">
      <Link
        href={WIDGETS_SETTINGS}
        className="flex items-center gap-1.5 px-3 pt-1.5 pb-1.5 text-micro text-muted-foreground hover:text-text"
      >
        <Gauge className="size-3.5 text-faint" aria-hidden />
        Widgets
      </Link>
      <ul className="grid grid-cols-2 gap-1.5 px-2 pb-2">
        {data.widgets.map((w, i) => (
          <WidgetTile key={`${i}-${w.label}`} widget={w} />
        ))}
      </ul>
    </div>
  );
}
