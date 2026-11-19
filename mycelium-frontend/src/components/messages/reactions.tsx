// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * Emoji on a message: the chips under it, one per emoji with how many put it
 * on, and the picker that puts one on. A chip you're in is drawn as yours, and
 * clicking it takes yours off; clicking anyone else's adds you.
 *
 * Putting one on someone's message reaches them as a silent mention on their
 * next wake, so it never interrupts an agent at work. The hub folds each
 * reaction into its message, and the open channel folds a live one the same way.
 */

import { useEffect, useMemo, useRef, useState } from "react";
import { SmilePlus } from "lucide-react";
import { reactToMessage, type MessageReactions } from "@/lib/api";
import { loadEmoji, readRecentEmoji, recordEmoji, searchEmoji, type EmojiTable } from "@/lib/emoji";
import { useRoomRevalidate } from "@/lib/room-data";
import { useCurrentUser } from "@/components/current-user";
import { iconButtonClass } from "@/components/ui/icon-button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** What the picker offers before anything is typed, after your recent ones. */
const QUICK = ["👍", "❤️", "🎉", "😂", "👀", "🙏", "🚀", "✅", "🔥", "🤔", "👏", "💯"];
/** How many emoji the picker shows at once: four rows. */
const SHOWN = 32;

/** Who you are in the room, as reactions name people. */
function useMe(): string {
  const { principal } = useCurrentUser();
  return principal.trim().replace(/^@/, "").toLowerCase() || "user";
}

/**
 * Put an emoji on a message or take yours off. The thread view reads again at
 * once; the channel folds the live reaction when it lands.
 */
export function useReact(roomName: string, messageId: string | null | undefined) {
  const me = useMe();
  const revalidate = useRoomRevalidate(roomName);
  const [failed, setFailed] = useState<string | null>(null);
  const react = async (emoji: string, on: boolean) => {
    if (!messageId) return;
    setFailed(null);
    if (on) recordEmoji(emoji);
    try {
      await reactToMessage(roomName, messageId, { emoji, on, sender_handle: me });
      revalidate();
    } catch (e) {
      setFailed(e instanceof Error ? e.message : "Couldn't react");
    }
  };
  return { me, react, failed };
}

/** `@julia and @lead`, or `@julia, @lead and 2 others`. */
export function whoReacted(by: string[], me: string): string {
  const names = by.map((h) => (h === me ? "you" : `@${h}`));
  if (names.length <= 3) {
    return names.length > 1 ? `${names.slice(0, -1).join(", ")} and ${names[names.length - 1]}` : names[0] ?? "";
  }
  return `${names.slice(0, 2).join(", ")} and ${names.length - 2} others`;
}

interface ChipsProps {
  roomName: string;
  messageId: string | null;
  reactions: MessageReactions[];
}

/** The chips under a message. Nothing at all when it has none. */
export function ReactionChips(props: ChipsProps) {
  return props.reactions.length > 0 ? <Chips {...props} /> : null;
}

function Chips({ roomName, messageId, reactions }: ChipsProps) {
  const { me, react, failed } = useReact(roomName, messageId);
  const [picking, setPicking] = useState(false);
  const mine = (r: MessageReactions) => r.by.includes(me);
  return (
    <div className="mt-1 flex flex-wrap items-center gap-1">
      {reactions.map((r) => (
        <Tooltip key={r.emoji} content={whoReacted(r.by, me)}>
          <button
            type="button"
            aria-pressed={mine(r)}
            aria-label={`${r.emoji} from ${whoReacted(r.by, me)}`}
            onClick={() => void react(r.emoji, !mine(r))}
            className={cn(
              "flex h-6 items-center gap-1 rounded-full border px-2 text-label tabular transition-colors",
              mine(r)
                ? "border-accent/60 bg-accent/15 text-text"
                : "border-border bg-surface text-muted-foreground hover:border-border2 hover:text-text",
            )}
          >
            <span className="text-[14px] leading-none">{r.emoji}</span>
            {r.by.length}
          </button>
        </Tooltip>
      ))}
      <ReactionPicker
        open={picking}
        onOpenChange={setPicking}
        onPick={(emoji) => {
          const found = reactions.find((r) => r.emoji === emoji);
          void react(emoji, !found?.by.includes(me));
        }}
        trigger={
          <PopoverTrigger
            aria-label="Add a reaction"
            className={cn(
              iconButtonClass("sm", "size-6 rounded-full"),
              // Shown with the row's hover, or while its picker is open.
              picking ? "opacity-100" : "opacity-0 group-hover:opacity-100 focus-visible:opacity-100",
            )}
          >
            <SmilePlus />
          </PopoverTrigger>
        }
      />
      {failed && <span className="text-micro text-red">{failed}</span>}
    </div>
  );
}

/**
 * Find an emoji and pick it: your recent ones and a few common ones first,
 * then whatever matches what you type. Picking one you already put on takes it
 * off, as clicking its chip does.
 */
export function ReactionPicker({
  open,
  onOpenChange,
  onPick,
  trigger,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onPick: (emoji: string) => void;
  trigger: React.ReactNode;
}) {
  const [query, setQuery] = useState("");
  const [table, setTable] = useState<EmojiTable | null>(null);
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (!open) return;
    let live = true;
    loadEmoji().then(
      (t) => live && setTable(t),
      () => {},
    );
    return () => {
      live = false;
    };
  }, [open]);

  const shown = useMemo(() => {
    const recent = open ? readRecentEmoji() : [];
    const q = query.trim().replace(/^:/, "");
    if (q && table) return searchEmoji(table, q, recent, SHOWN).map((m) => ({ emoji: m.emoji, name: m.name }));
    const first = [...new Set([...recent, ...QUICK])].slice(0, SHOWN);
    return first.map((emoji) => ({ emoji, name: table?.entries.find((e) => e.emoji === emoji)?.names[0] ?? emoji }));
  }, [open, query, table]);

  // Each time it opens, it opens empty.
  const openChange = (next: boolean) => {
    if (!next) setQuery("");
    onOpenChange(next);
  };
  const pick = (emoji: string) => {
    onPick(emoji);
    openChange(false);
  };

  return (
    <Popover open={open} onOpenChange={openChange}>
      {trigger}
      <PopoverContent
        align="end"
        sideOffset={4}
        initialFocus={input}
        className="w-72 p-2"
      >
        <input
          ref={input}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && shown[0]) {
              e.preventDefault();
              pick(shown[0].emoji);
            }
          }}
          placeholder="Find an emoji"
          aria-label="Find an emoji"
          className="mb-2 h-8 w-full rounded-md border border-border bg-bg px-2 text-label text-text outline-none placeholder:text-faint focus:border-accent"
        />
        {shown.length > 0 ? (
          <div role="listbox" aria-label="Emoji" className="grid grid-cols-8 gap-0.5">
            {shown.map((m) => (
              <button
                key={m.emoji}
                type="button"
                role="option"
                aria-selected={false}
                title={`:${m.name}:`}
                aria-label={m.name}
                onClick={() => pick(m.emoji)}
                className="flex size-8 items-center justify-center rounded-md text-[18px] leading-none transition-colors hover:bg-hairline focus-visible:bg-hairline focus-visible:outline-none"
              >
                {m.emoji}
              </button>
            ))}
          </div>
        ) : (
          <p className="px-1 py-2 text-label text-muted-foreground">No emoji match that.</p>
        )}
      </PopoverContent>
    </Popover>
  );
}
