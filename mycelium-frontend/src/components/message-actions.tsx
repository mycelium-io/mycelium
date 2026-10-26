// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * The row of buttons on a channel message the pointer is on: Reply and Quote
 * (into the room's composer), Copy text and Copy link, Make a task, and More,
 * which holds the right-click menu's remaining items. It sits on the message's
 * top edge so it never moves the text, and draws nothing until its row is
 * hovered or has focus, so a long channel carries no open bars.
 */

import { useEffect, useRef, useState } from "react";
import { AtSign, Braces, Check, Copy, Link2, ListTodo, Loader2, MoreHorizontal, Reply, TextQuote } from "lucide-react";
import { createTask } from "@/lib/api";
import { absoluteUrl, copyText } from "@/lib/clipboard";
import {
  insertIntoComposer,
  messagePath,
  quoteText,
  replyText,
  taskBody,
  taskTitle,
} from "@/lib/message-actions";
import { useCurrentUser } from "@/components/current-user";
import { useKeyAction } from "@/components/keymap-provider";
import { IconButton, iconButtonClass } from "@/components/ui/icon-button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip } from "@/components/ui/tooltip";
import { RawMessageDialog } from "@/components/raw-message-dialog";

interface Props {
  roomName: string;
  /** The thread the message is drawn in, whose composer Reply and Quote fill. */
  episode?: string | null;
  messageId?: string | null;
  content: string;
  sender: string;
  wire?: Record<string, unknown>;
  /** Opens the task a message was just made into, on its thread. */
  onOpenThread?: (episode: string) => void;
  /** A clock time to show at the bar's start, for a line with no header of its own. */
  time?: string;
}

/** How long a copy button shows its check. */
const COPIED_MS = 1500;

const menuItem =
  "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-label text-text transition-colors hover:bg-hairline [&_svg]:size-3.5 [&_svg]:text-muted-foreground";

export function MessageActions(props: Props) {
  // Mounted in every row, but only an anchor until the row is hovered or
  // focused: the row is the anchor's parent, and its events are watched here
  // so hovering one message re-renders that message alone.
  const anchor = useRef<HTMLSpanElement>(null);
  const [hovered, setHovered] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  useEffect(() => {
    const row = anchor.current?.parentElement;
    if (!row) return;
    const on = () => setHovered(true);
    const off = (e: Event) => {
      // Focus moving within the row (between the bar's buttons) keeps it open.
      if (e instanceof FocusEvent && e.relatedTarget instanceof Node && row.contains(e.relatedTarget)) return;
      if (e.type === "focusout" && row.matches(":hover")) return;
      if (e.type === "mouseleave" && row.contains(document.activeElement)) return;
      setHovered(false);
    };
    row.addEventListener("mouseenter", on);
    row.addEventListener("mouseleave", off);
    row.addEventListener("focusin", on);
    row.addEventListener("focusout", off);
    return () => {
      row.removeEventListener("mouseenter", on);
      row.removeEventListener("mouseleave", off);
      row.removeEventListener("focusin", on);
      row.removeEventListener("focusout", off);
    };
  }, []);

  // Held here rather than in the bar, which goes when the pointer moves off
  // the row, as it does to reach the dialog.
  const [rawOpen, setRawOpen] = useState(false);

  return (
    <>
      <span ref={anchor} hidden />
      {(hovered || menuOpen) && (
        <Bar {...props} menuOpen={menuOpen} onMenuOpen={setMenuOpen} onViewRaw={() => setRawOpen(true)} />
      )}
      {rawOpen && props.wire && <RawMessageDialog open onClose={() => setRawOpen(false)} message={props.wire} />}
    </>
  );
}

function Bar({
  roomName,
  episode = null,
  messageId,
  content,
  sender,
  wire,
  onOpenThread,
  time,
  menuOpen,
  onMenuOpen,
  onViewRaw,
}: Props & { menuOpen: boolean; onMenuOpen: (open: boolean) => void; onViewRaw: () => void }) {
  const { principal } = useCurrentUser();
  const [copied, setCopied] = useState<"text" | "link" | null>(null);
  const [making, setMaking] = useState(false);
  const [taskError, setTaskError] = useState<string | null>(null);
  useEffect(() => {
    if (!copied) return;
    const t = setTimeout(() => setCopied(null), COPIED_MS);
    return () => clearTimeout(t);
  }, [copied]);

  const link = messageId ? absoluteUrl(messagePath(roomName, messageId)) : null;
  // The bar sits in its message's row, so it says which pane the click is from.
  const bar = useRef<HTMLDivElement>(null);
  const insert = (text: string) => insertIntoComposer({ room: roomName, episode, text, from: bar.current });
  const reply = () => insert(replyText(sender));
  const quote = () => insert(quoteText(content, sender));
  const copy = () => void copyText(content).then(() => setCopied("text"));
  // Bound only while this bar is drawn, which is while its message is hovered.
  useKeyAction("message.reply", reply);
  useKeyAction("message.quote", quote);
  useKeyAction("message.copy", copy);

  const makeTask = async () => {
    setMaking(true);
    setTaskError(null);
    try {
      const task = await createTask(roomName, {
        title: taskTitle(content),
        content: taskBody(content, sender, link),
        handle: principal.trim() || "user",
      });
      if (task.episode) onOpenThread?.(task.episode);
    } catch (e) {
      setTaskError(e instanceof Error ? e.message : "Couldn't make the task");
    } finally {
      setMaking(false);
    }
  };

  return (
    <div
      ref={bar}
      role="toolbar"
      aria-label="Message actions"
      className="absolute -top-3.5 right-4 z-10 flex items-center gap-px rounded-lg border border-border2 bg-elevated p-0.5 shadow-md"
    >
      {time && <span className="px-1.5 text-micro tabular text-faint">{time}</span>}
      <IconButton label="Reply" action="message.reply" className="size-7" onClick={reply}>
        <Reply />
      </IconButton>
      <IconButton label="Quote" action="message.quote" className="size-7" onClick={quote}>
        <TextQuote />
      </IconButton>
      <Divider />
      <IconButton
        label={copied === "text" ? "Copied" : "Copy text"}
        action="message.copy"
        className="size-7"
        onClick={copy}
      >
        {copied === "text" ? <Check /> : <Copy />}
      </IconButton>
      {link && (
        <IconButton
          label={copied === "link" ? "Copied" : "Copy link"}
          className="size-7"
          onClick={() => void copyText(link).then(() => setCopied("link"))}
        >
          {copied === "link" ? <Check /> : <Link2 />}
        </IconButton>
      )}
      <Divider />
      <IconButton
        label={taskError ? `Couldn't make the task: ${taskError}` : "Make a task"}
        className={taskError ? "size-7 text-red" : "size-7"}
        disabled={making}
        onClick={() => void makeTask()}
      >
        {making ? <Loader2 className="animate-spin" /> : <ListTodo />}
      </IconButton>
      <Divider />
      <Popover open={menuOpen} onOpenChange={onMenuOpen}>
        <Tooltip content="More">
          <PopoverTrigger aria-label="More" className={iconButtonClass("sm", "size-7")}>
            <MoreHorizontal />
          </PopoverTrigger>
        </Tooltip>
        <PopoverContent align="end" sideOffset={4} className="w-52 p-1">
          <button
            type="button"
            className={menuItem}
            onClick={() => {
              void copyText(`@${sender}`);
              onMenuOpen(false);
            }}
          >
            <AtSign />
            Copy @{sender}
          </button>
          {wire && (
            <button
              type="button"
              className={menuItem}
              onClick={() => {
                onViewRaw();
                onMenuOpen(false);
              }}
            >
              <Braces />
              View raw message
            </button>
          )}
        </PopoverContent>
      </Popover>
    </div>
  );
}

function Divider() {
  return <span aria-hidden className="mx-0.5 h-4 w-px bg-border" />;
}
