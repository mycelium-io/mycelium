// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { createContext, useContext, type ReactElement } from "react";
import {
  ArrowUpRight,
  Ban,
  CheckCircle2,
  CircleDot,
  Copy,
  Hand,
  Link2,
  MessageSquare,
  Undo2,
  Vote,
  X,
  type LucideIcon,
} from "lucide-react";
import {
  ContextMenu,
  ContextMenuContent,
  ContextMenuItem,
  ContextMenuSeparator,
  ContextMenuSub,
  ContextMenuTrigger,
} from "@/components/ui/context-menu";
import { openableThread } from "@/components/board/board-cells";
import { attentionFilterOf, ROW_ACTIONS, type LiveItem, type RowAction } from "@/lib/board/item";
import { fieldAsList } from "@/lib/board/fields";
import { absoluteUrl, copyText } from "@/lib/clipboard";

/** What a board row can do, from the board that owns the rows. */
interface BoardRowActions {
  now: number;
  onVerb: (item: LiveItem, action: RowAction) => void;
  onAnswer: (item: LiveItem, choice: string) => void;
  onOpenThread?: (episode: string) => void;
}

const BoardRowActionsContext = createContext<BoardRowActions | null>(null);

const ACTION_ICONS: Partial<Record<RowAction, LucideIcon>> = {
  claim: Hand,
  release: Undo2,
  resolve: CheckCircle2,
  block: Ban,
  promote: ArrowUpRight,
  dismiss: X,
};

export const BoardRowActionsProvider = BoardRowActionsContext.Provider;

/**
 * A board row's right-click menu, the same in every view: open its thread, the
 * row actions the triage strip and the board's keys already offer (filtered the
 * same way, with the same keys), a decision's answers, and copying it.
 * Outside a board it adds nothing.
 */
export function BoardRowMenu({ item, children }: { item: LiveItem; children: ReactElement }) {
  const actions = useContext(BoardRowActionsContext);
  if (!actions) return children;
  const { now, onVerb, onAnswer, onOpenThread } = actions;
  const resolved = attentionFilterOf(item, now) === "resolved";
  const thread = openableThread(item);
  const choices = resolved ? [] : fieldAsList(item, "choices");
  const key = item.source.kind === "memory" ? item.source.label : null;
  const href = item.source.kind === "memory" ? item.source.href : undefined;
  return (
    <ContextMenu>
      <ContextMenuTrigger>{children}</ContextMenuTrigger>
      <ContextMenuContent>
        {thread && onOpenThread && (
          <>
            <ContextMenuItem icon={MessageSquare} keys="t" onClick={() => onOpenThread(thread)}>
              Open thread
            </ContextMenuItem>
            <ContextMenuSeparator />
          </>
        )}
        {ROW_ACTIONS.filter((a) => !(resolved && (a.id === "resolve" || a.id === "dismiss"))).map((a) => (
          <ContextMenuItem key={a.id} icon={ACTION_ICONS[a.id] ?? CircleDot} keys={a.key} onClick={() => onVerb(item, a.id)}>
            {a.label}
          </ContextMenuItem>
        ))}
        {choices.length > 0 && (
          <ContextMenuSub label="Answer" icon={Vote}>
            {choices.map((choice) => (
              <ContextMenuItem key={choice} onClick={() => onAnswer(item, choice)}>
                {choice}
              </ContextMenuItem>
            ))}
          </ContextMenuSub>
        )}
        {key && (
          <>
            <ContextMenuSeparator />
            <ContextMenuItem icon={Copy} onClick={() => void copyText(key)}>
              Copy key
            </ContextMenuItem>
            <ContextMenuItem icon={Link2} onClick={() => void copyText(`[[${key}]]`)}>
              Copy as [[link]]
            </ContextMenuItem>
            {href && (
              <ContextMenuItem icon={Link2} onClick={() => void copyText(absoluteUrl(href))}>
                Copy page link
              </ContextMenuItem>
            )}
          </>
        )}
      </ContextMenuContent>
    </ContextMenu>
  );
}
