// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Fragment, useEffect, useLayoutEffect, useRef, useState, type RefObject } from "react";
import { createPortal } from "react-dom";
import { useRouter } from "next/navigation";
import { Volume2, X } from "lucide-react";
import { Tooltip } from "@/components/ui/tooltip";
import type { ReadAloud } from "@/components/notifications-provider";
import type { ReaderState } from "@/lib/read-aloud";
import type { Block } from "@/lib/speakable";

/** Focus in a text field keeps Esc for the field: the composer, a dialog's input. */
function typing(el: Element | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  return el.isContentEditable || el.tagName === "INPUT" || el.tagName === "TEXTAREA" || el.tagName === "SELECT";
}

function title(state: ReaderState): string {
  const item = state.item;
  if (!item) return "";
  if (item.sender) return item.sender;
  return item.id.startsWith("more:") ? "Mentions" : "Read aloud";
}

function status(state: ReaderState): string | null {
  if (state.status === "held") return "Waiting for the mic to turn off";
  if (state.status === "failed") return state.error;
  return null;
}

/** The message's blocks, with the sentence being said lit. */
function Words({ blocks, state }: { blocks: Block[]; state: ReaderState }) {
  // Each block's first sentence, as an index into the whole message.
  const starts = blocks.map((_, b) => blocks.slice(0, b).reduce((n, x) => n + x.sentences.length, 0));
  return (
    <div className="space-y-1.5">
      {blocks.map((block, b) => {
        const start = starts[b];
        const lit = (i: number) => state.at === i;
        const unread = (i: number) => i >= state.end;
        if (block.kind === "code" || block.kind === "table") {
          return (
            <pre
              key={b}
              data-lit={lit(start) || undefined}
              className={`max-h-24 overflow-hidden whitespace-pre-wrap rounded-md border px-2 py-1 font-mono text-[11px] leading-snug ${
                lit(start) ? "border-accent/50 bg-accent-soft text-text" : "border-border text-muted-foreground"
              } ${unread(start) ? "opacity-60" : ""}`}
            >
              {block.raw}
            </pre>
          );
        }
        return (
          <p
            key={b}
            className={`text-label leading-relaxed ${block.kind === "heading" ? "font-semibold" : ""} ${
              block.kind === "item" ? "pl-3 before:-ml-3 before:inline-block before:w-3 before:content-['•']" : ""
            }`}
          >
            {block.sentences.map((s, k) => {
              const i = start + k;
              return (
                <Fragment key={k}>
                  <span
                    data-lit={lit(i) || undefined}
                    className={`rounded-sm transition-colors ${
                      lit(i) ? "bg-accent-soft text-text" : unread(i) ? "text-faint" : "text-muted-foreground"
                    }`}
                  >
                    {s.show}
                  </span>
                  {k < block.sentences.length - 1 ? " " : ""}
                </Fragment>
              );
            })}
          </p>
        );
      })}
    </div>
  );
}

/**
 * What's being read aloud, under the bell: who, where, and the message with
 * the sentence being said lit. It opens on its own while reading and closes
 * when it's done, and never takes focus, so typing in the composer carries
 * on. Clicking the words opens the message; ✕ stops it, and so does Esc when
 * focus isn't in a text field.
 */
export function ReadAloudPopover({
  readAloud,
  anchor,
  hidden,
  onOpen,
}: {
  readAloud: ReadAloud;
  anchor: RefObject<HTMLElement | null>;
  /** The bell's own list is open over it. */
  hidden: boolean;
  onOpen: (id: string) => void;
}) {
  const { state, stop, readAll, keepOpen } = readAloud;
  const router = useRouter();
  const words = useRef<HTMLDivElement>(null);
  const [place, setPlace] = useState<{ top: number; right: number } | null>(null);
  const open = Boolean(state.item);

  useLayoutEffect(() => {
    if (!open) return;
    const measure = () => {
      const rect = anchor.current?.getBoundingClientRect();
      if (rect) setPlace({ top: rect.bottom + 8, right: Math.max(8, window.innerWidth - rect.right) });
    };
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [open, anchor]);

  // Keep the lit sentence in view in a long message.
  useEffect(() => {
    const lit = words.current?.querySelector("[data-lit]");
    if (lit instanceof HTMLElement && typeof lit.scrollIntoView === "function") {
      lit.scrollIntoView({ block: "nearest" });
    }
  }, [state.at]);

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key !== "Escape" || typing(document.activeElement) || e.defaultPrevented) return;
      stop();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, stop]);

  if (!open || !state.item || !place || typeof document === "undefined") return null;
  const item = state.item;
  const note = status(state);
  const go = () => {
    if (!item.href) return;
    onOpen(item.id);
    stop();
    router.push(item.href);
  };

  return createPortal(
    <div
      role="status"
      aria-live="polite"
      aria-label={`Reading aloud: ${title(state)}`}
      onMouseEnter={() => keepOpen(true)}
      onMouseLeave={() => keepOpen(false)}
      style={{ top: place.top, right: place.right }}
      className={`fixed z-50 flex w-80 flex-col rounded-xl border border-border bg-popover text-popover-foreground shadow-lg duration-100 animate-in fade-in-0 zoom-in-95 ${
        hidden ? "hidden" : ""
      }`}
    >
      <div className="flex items-center gap-2 border-b border-border px-3 py-2">
        <Volume2
          aria-hidden
          className={`size-3.5 flex-shrink-0 ${state.status === "speaking" ? "animate-pulse text-accent" : "text-muted-foreground"}`}
        />
        <span className="flex-shrink-0 text-micro font-semibold text-text">{title(state)}</span>
        {item.where && <span className="truncate text-micro text-muted-foreground">{item.where}</span>}
        <Tooltip content="Stop reading (Esc)">
          <button
            type="button"
            onClick={stop}
            aria-label="Stop reading"
            className="ml-auto flex size-5 flex-shrink-0 items-center justify-center rounded text-faint hover:bg-hairline hover:text-text"
          >
            <X className="size-3" />
          </button>
        </Tooltip>
      </div>
      <div
        ref={words}
        onClick={item.href ? go : undefined}
        className={`max-h-64 overflow-y-auto px-3 py-2.5 ${item.href ? "cursor-pointer" : ""}`}
        title={item.href ? "Open the message" : undefined}
      >
        <Words blocks={item.blocks} state={state} />
      </div>
      {(note || state.end < state.total || state.waiting + state.more > 0) && (
        <div className="flex items-center gap-2 border-t border-border px-3 py-1.5 text-micro">
          {note && (
            <span className={state.status === "failed" ? "text-red" : "text-muted-foreground"}>{note}</span>
          )}
          {state.waiting + state.more > 0 && (
            <span className="tabular text-faint">{state.waiting + state.more} more after this</span>
          )}
          {state.end < state.total && (
            <button type="button" onClick={readAll} className="ml-auto text-accent hover:underline">
              Read all
            </button>
          )}
        </div>
      )}
    </div>,
    document.body,
  );
}
