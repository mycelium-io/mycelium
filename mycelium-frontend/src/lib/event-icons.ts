// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The icon and color for each kind of event line, in one table both the chat
 * (`event-stream.tsx`) and the Stream tab (`stream/room-stream.tsx`) read, so
 * the two views agree on what a task being filed or a pull request merging
 * looks like.
 *
 * Colors carry the same meaning everywhere: green when work lands or clears,
 * red when it's blocked or failing, yellow when it's back up for grabs, and
 * the accent while it's in hand. Every board notice and every pull request
 * change frozen in the contracts has an entry; `event-icons.test.ts` walks
 * those lists, so a new kind can't arrive without an icon.
 */

import {
  Ban,
  BadgeCheck,
  BookOpen,
  CircleCheck,
  CircleCheckBig,
  CircleX,
  Clock,
  Eye,
  GitMerge,
  GitPullRequest,
  GitPullRequestClosed,
  Hand,
  Handshake,
  LockOpen,
  Megaphone,
  MessageSquareText,
  OctagonAlert,
  PencilLine,
  SquarePlus,
  StickyNote,
  TimerOff,
  TriangleAlert,
  Undo2,
  UserPlus,
  Vote,
  type LucideIcon,
} from "lucide-react";

export interface EventIcon {
  Icon: LucideIcon;
  /** A CSS color: one of the theme's tokens. */
  tone: string;
  /** What happened, for screen readers and the tooltip ("Task resolved"). */
  label: string;
}

const GREEN = "var(--green)";
const RED = "var(--red)";
const YELLOW = "var(--yellow)";
const ACCENT = "var(--accent)";
const QUIET = "var(--muted-foreground)";

/** What a board change did to a task, by notice subkind (`contracts/slim-wire.json`). */
export const NOTICE_ICONS: Record<string, EventIcon> = {
  filed: { Icon: SquarePlus, tone: GREEN, label: "New task" },
  claimed: { Icon: Hand, tone: ACCENT, label: "Task claimed" },
  released: { Icon: Undo2, tone: YELLOW, label: "Task released" },
  resolved: { Icon: CircleCheckBig, tone: GREEN, label: "Task resolved" },
  blocked: { Icon: Ban, tone: RED, label: "Task blocked" },
  unblocked: { Icon: LockOpen, tone: GREEN, label: "Task unblocked" },
  expired: { Icon: Clock, tone: YELLOW, label: "Claim expired" },
  quiet: { Icon: Clock, tone: QUIET, label: "Gone quiet" },
  floor: { Icon: Megaphone, tone: ACCENT, label: "Turn to speak" },
};

/** What happened to a linked pull request, by `upstream` change. */
export const UPSTREAM_ICONS: Record<string, EventIcon> = {
  opened: { Icon: GitPullRequest, tone: ACCENT, label: "Pull request opened" },
  review_requested: { Icon: Eye, tone: ACCENT, label: "Review requested" },
  approved: { Icon: BadgeCheck, tone: GREEN, label: "Pull request approved" },
  changes_requested: { Icon: PencilLine, tone: RED, label: "Changes requested" },
  ci_passed: { Icon: CircleCheck, tone: GREEN, label: "CI passed" },
  ci_failed: { Icon: CircleX, tone: RED, label: "CI failed" },
  merged: { Icon: GitMerge, tone: GREEN, label: "Pull request merged" },
  closed: { Icon: GitPullRequestClosed, tone: ACCENT, label: "Pull request closed" },
};

/** A filed row by its kind (the board's `kind` field), labelled with the words
 *  the line itself says ("New blocker"), so the icon never contradicts them.
 *  A blocker is red and a concern yellow, since filing one isn't work landing. */
export const FILED_ICONS: Record<string, EventIcon> = {
  action: { Icon: SquarePlus, tone: GREEN, label: "New task" },
  review: { Icon: SquarePlus, tone: GREEN, label: "New task" },
  decision: { Icon: Vote, tone: GREEN, label: "New decision" },
  blocked: { Icon: OctagonAlert, tone: RED, label: "New blocker" },
  concern: { Icon: TriangleAlert, tone: YELLOW, label: "New concern" },
  signal: { Icon: StickyNote, tone: ACCENT, label: "New note" },
};

/** Lines that aren't board notices. */
export const THREAD_ICON: EventIcon = { Icon: MessageSquareText, tone: ACCENT, label: "Message in a thread" };
export const MEMORY_ICON: EventIcon = { Icon: BookOpen, tone: YELLOW, label: "Memory updated" };
export const AGREED_ICON: EventIcon = { Icon: Handshake, tone: GREEN, label: "Agreed" };
export const DONE_ICON: EventIcon = { Icon: CircleCheckBig, tone: GREEN, label: "Done" };
export const TIMEOUT_ICON: EventIcon = { Icon: TimerOff, tone: YELLOW, label: "Timed out" };
export const JOIN_ICON: EventIcon = { Icon: UserPlus, tone: QUIET, label: "Joined" };

const UNKNOWN_NOTICE: EventIcon = { Icon: SquarePlus, tone: ACCENT, label: "Task changed" };
const UNKNOWN_UPSTREAM: EventIcon = { Icon: GitPullRequest, tone: ACCENT, label: "Pull request changed" };

/** The icon for a board notice: its subkind, or for `upstream` the change,
 *  and for `filed` the kind of row that was filed. */
export function noticeIcon(subkind: string, change?: string | null, kind?: string | null): EventIcon {
  if (subkind === "upstream") return (change && UPSTREAM_ICONS[change]) || UNKNOWN_UPSTREAM;
  if (subkind === "filed" && kind && FILED_ICONS[kind]) return FILED_ICONS[kind];
  return NOTICE_ICONS[subkind] ?? UNKNOWN_NOTICE;
}
