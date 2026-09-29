// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useRef } from "react";
import { cn } from "@/lib/utils";
import {
  ROW_ACTIONS,
  fieldAsList,
  fieldAsString,
  kindOf,
  attentionFilterOf,
  statusOf,
  type LiveItem,
  type RowAction,
} from "@/lib/board/item";
import { waitingOn, type ItemGroup } from "@/lib/board/view";
import { EPISODE_FIELD } from "@/lib/board/projection";
import {
  AgeTag,
  BlocksNote,
  KindIcon,
  LiveDot,
  AssignmentChip,
  openableThread,
  ThreadChip,
  UpstreamChip,
  WorkLinks,
} from "./board-cells";
import { BoardRowMenu } from "./board-row-menu";

interface Props {
  groups: ItemGroup[];
  now: number;
  selectedId: string | null;
  onSelect: (id: string) => void;
  onVerb: (item: LiveItem, action: RowAction) => void;
  onAnswer: (item: LiveItem, choice: string) => void;
  /** Open a row's thread. Absent, the thread chip reads as a label. */
  onOpenThread?: (episode: string) => void;
}

/**
 * The steer filter, rendered. Rows are grouped by whatever the view groups by, and
 * every row carries its own row actions — triage is one gesture from wherever the eye
 * already is, never a detour through a detail page.
 */
export function BoardTriage({ groups, now, selectedId, onSelect, onVerb, onAnswer, onOpenThread }: Props) {
  return (
    <div className="flex flex-col gap-3 px-3 py-2 sm:px-4">
      {groups.map(group => (
        <section key={group.key}>
          {/* A quiet label over its rows, the way every list here groups. */}
          <header className="flex h-7 items-end gap-1.5 px-2 pb-1">
            <h3 className="text-micro font-medium text-faint">{group.label}</h3>
            <span className="tabular text-micro text-faint">{group.items.length}</span>
          </header>
          <div className="flex flex-col">
            {group.items.map(item => (
              <TriageRow
                key={item.id}
                item={item}
                now={now}
                selected={item.id === selectedId}
                onSelect={() => onSelect(item.id)}
                onVerb={action => onVerb(item, action)}
                onAnswer={choice => onAnswer(item, choice)}
                onOpenThread={onOpenThread}
              />
            ))}
          </div>
        </section>
      ))}
    </div>
  );
}

function TriageRow({
  item,
  now,
  selected,
  onSelect,
  onVerb,
  onAnswer,
  onOpenThread,
}: {
  item: LiveItem;
  now: number;
  selected: boolean;
  onSelect: () => void;
  onVerb: (action: RowAction) => void;
  onAnswer: (choice: string) => void;
  onOpenThread?: (episode: string) => void;
}) {
  const ref = useRef<HTMLDivElement>(null);
  // Keyboard navigation moves the selection, so the selection has to bring the
  // row with it — otherwise j/k walks off the bottom of the viewport.
  useEffect(() => {
    if (selected) ref.current?.scrollIntoView({ block: "nearest" });
  }, [selected]);

  const choices = fieldAsList(item, "choices");
  const waiting = waitingOn(item);
  const resolved = attentionFilterOf(item, now) === "resolved";
  // Priority is only worth a word when it's above normal.
  const priority = fieldAsString(item, "priority");
  const raised = !resolved && (priority === "urgent" || priority === "high") ? priority : null;

  return (
    <BoardRowMenu item={item}>
    <div
      ref={ref}
      role="button"
      tabIndex={-1}
      // The row is the task, and the task is its thread, so a click opens it —
      // the verbs and answer chips below stop the click, so they still act in
      // place. Selecting keeps the keyboard's place on the row it opened.
      onClick={() => {
        onSelect();
        const episode = openableThread(item);
        if (episode) onOpenThread?.(episode);
      }}
      data-board-row={item.id}
      className={cn(
        "group relative flex cursor-pointer items-start gap-2.5 rounded px-2 py-1.5 transition-colors",
        selected ? "bg-hairline" : "hover:bg-hairline",
        resolved && "opacity-60",
      )}
    >
      {/* The selected row wears an accent edge; the eye keeps its place through an action. */}
      {selected && <span className="absolute inset-y-1.5 left-0 w-[2px] rounded-full bg-accent" />}

      <KindIcon item={item} className="mt-[2px]" />

      <div className="min-w-0 flex-1">
        <div className="flex items-baseline gap-2">
          <span
            title={item.source.label}
            className={cn(
              "min-w-0 flex-1 truncate text-label",
              resolved ? "text-muted-foreground line-through decoration-border2" : "text-text",
            )}
          >
            {item.title}
          </span>
          {raised && (
            <span className={cn("shrink-0 text-micro", raised === "urgent" ? "text-red" : "text-yellow")}>
              {raised}
            </span>
          )}
          <AgeTag item={item} now={now} drain />
        </div>

        {/* Only what's worth a glance: who has it, where the work is, what it waits on.
            The row's key is the title's tooltip; an empty line draws nothing. */}
        <div className="mt-0.5 flex flex-wrap items-center gap-x-2.5 gap-y-0.5 text-micro empty:hidden">
          <AssignmentChip item={item} now={now} />
          <ThreadChip item={item} onOpen={onOpenThread} />
          <WorkLinks item={item} />
          <UpstreamChip item={item} />
          <BlocksNote item={item} />
          {waiting && <span className="text-micro text-red">{waiting}</span>}
          <LiveDot item={item} />
        </div>

        {/* A decision the room can settle from the row: the answer is the gesture. */}
        {choices.length > 0 && statusOf(item) === "open" && (
          <div className="mt-1 flex flex-wrap items-center gap-1">
            {choices.map(choice => (
              <button
                key={choice}
                onClick={e => {
                  e.stopPropagation();
                  onAnswer(choice);
                }}
                className="h-6 rounded border border-accent/30 px-1.5 text-micro text-accent transition-colors hover:bg-accent-soft"
              >
                {choice}
              </button>
            ))}
            {/* Answering settles it in one gesture; replying opens its thread —
                the row's own, because a decision is a task with a thread like any
                other. A real way in, not a promise the row can't keep. */}
            {(() => {
              const episode = fieldAsString(item, EPISODE_FIELD);
              return episode && onOpenThread ? (
                <button
                  onClick={e => {
                    e.stopPropagation();
                    onOpenThread(episode);
                  }}
                  className="text-micro text-muted-foreground underline-offset-2 transition-colors hover:text-text hover:underline"
                >
                  or reply in thread
                </button>
              ) : (
                <span className="text-micro text-faint">or reply in thread</span>
              );
            })()}
          </div>
        )}
      </div>


      {/* Row actions stay hidden until the row is under the cursor or the caret, so a
          long list reads as text rather than as a wall of buttons. */}
      <div
        className={cn(
          "absolute right-1.5 top-1 flex items-center gap-0.5 rounded bg-surface p-0.5 transition-opacity",
          selected ? "opacity-100" : "pointer-events-none opacity-0 group-hover:pointer-events-auto group-hover:opacity-100",
        )}
      >
        {ROW_ACTIONS.filter(v => !(resolved && (v.id === "resolve" || v.id === "dismiss"))).map(action => (
          <button
            key={action.id}
            onClick={e => {
              e.stopPropagation();
              onVerb(action.id);
            }}
            title={`${action.label}  (${action.key})`}
            className="rounded px-1.5 py-0.5 text-micro text-muted-foreground transition-colors hover:bg-surface hover:text-text"
          >
            {action.label.split(" ")[0]}
            <span className="ml-1 font-mono text-faint">{action.key}</span>
          </button>
        ))}
      </div>
    </div>
    </BoardRowMenu>
  );
}

/** The one-line summary the header wears, phrased the way the CLI prints it. */
export function summarize(items: LiveItem[], now: number = Date.now()): string {
  const needs = items.filter(i => attentionFilterOf(i, now) === "needs_you").length;
  const flight = items.filter(i => attentionFilterOf(i, now) === "in_flight").length;
  const resolved = items.filter(i => attentionFilterOf(i, now) === "resolved").length;
  const decisions = items.filter(
    i => kindOf(i) === "decision" && attentionFilterOf(i, now) === "needs_you",
  ).length;
  const parts = [`${needs} need you`, `${flight} in flight`, `${resolved} resolved today`];
  if (decisions) parts.unshift(`${decisions} open decision${decisions === 1 ? "" : "s"}`);
  return parts.join(" · ");
}
