// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useLayoutEffect, useRef, useState } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { X } from "lucide-react";
import { OPEN_TASK_EVENT, useNotifications, type OpenTaskDetail } from "@/components/notifications-provider";
import { entryHref, entryTitle, lastAsk, MOVE_LABEL, MOVE_TONE } from "@/lib/task-inbox";

/** How long a toast stays while you're looking at the window. */
export const TOAST_MS = 8000;
/** The gap kept from the screen's edges, the status bar and the composer. */
const GAP = 12;
const STATUS_BAR = 24;

/**
 * The one toast: a task just became your move (asked, blocked, CI red on
 * yours, ready to merge). Bottom-right, small and silent, with one action. It
 * waits while the pointer is on it or the window isn't focused, so it is still
 * there when you come back, and it is in the bell either way. It lifts itself
 * above the composer whenever the two would overlap.
 */
export function TaskToast() {
  const { toast, tasks, dismissToast, markTaskSeen } = useNotifications();
  const entry = toast ? tasks.find((t) => t.id === toast.id) : undefined;
  const [hovered, setHovered] = useState(false);
  const [focused, setFocused] = useState(true);
  const [bottom, setBottom] = useState(STATUS_BAR + GAP);
  const ref = useRef<HTMLDivElement>(null);
  const router = useRouter();

  // A system notification, clicked while you were elsewhere, opens its task.
  useEffect(() => {
    const open = (e: Event) => {
      const detail = (e as CustomEvent<OpenTaskDetail>).detail;
      if (!detail?.href) return;
      markTaskSeen(detail.id);
      router.push(detail.href);
    };
    window.addEventListener(OPEN_TASK_EVENT, open);
    return () => window.removeEventListener(OPEN_TASK_EVENT, open);
  }, [router, markTaskSeen]);

  useEffect(() => {
    const sync = () => setFocused(document.hasFocus());
    sync();
    window.addEventListener("focus", sync);
    window.addEventListener("blur", sync);
    return () => {
      window.removeEventListener("focus", sync);
      window.removeEventListener("blur", sync);
    };
  }, []);

  // Counts down only while you could be reading it. A new toast (or a change
  // folded into this one) starts the count again.
  useEffect(() => {
    if (!toast || hovered || !focused) return;
    const timer = window.setTimeout(dismissToast, TOAST_MS);
    return () => window.clearTimeout(timer);
  }, [toast, hovered, focused, dismissToast]);

  // Never over the composer: sit above any composer this would cover.
  useLayoutEffect(() => {
    if (!toast || !ref.current) return;
    const place = () => {
      const box = ref.current?.getBoundingClientRect();
      if (!box) return;
      let lift = STATUS_BAR + GAP;
      for (const el of document.querySelectorAll<HTMLElement>('[data-tour="composer"]')) {
        const r = el.getBoundingClientRect();
        if (r.width === 0 || r.right <= box.left || r.left >= box.right) continue;
        lift = Math.max(lift, window.innerHeight - r.top + GAP);
      }
      setBottom(lift);
    };
    place();
    window.addEventListener("resize", place);
    return () => window.removeEventListener("resize", place);
  }, [toast]);

  if (!toast || !entry) return null;
  const ask = toast.move === "asks" ? lastAsk(entry) : null;
  const detail = ask?.text ? `${ask.actor}: ${ask.text}` : entry.pr.ref ? `${entry.room} · ${entry.pr.ref.split("/").pop()}` : entry.room;

  return (
    <div
      ref={ref}
      role="status"
      aria-live="polite"
      onPointerEnter={() => setHovered(true)}
      onPointerLeave={() => setHovered(false)}
      onFocus={() => setHovered(true)}
      onBlur={() => setHovered(false)}
      style={{ bottom }}
      className="fixed right-3 z-50 flex w-72 items-start gap-2.5 rounded-lg border border-border2 bg-elevated px-3 py-2.5 shadow-lg"
    >
      <span className="mt-1.5 size-1.5 flex-shrink-0 rounded-full" style={{ background: MOVE_TONE[toast.move] }} aria-hidden />
      <div className="min-w-0 flex-1">
        <p className="text-micro font-semibold" style={{ color: MOVE_TONE[toast.move] }}>
          {MOVE_LABEL[toast.move]}
        </p>
        <p className="truncate text-label font-medium text-text">{entryTitle(entry)}</p>
        <p className="truncate text-micro text-muted-foreground">{detail}</p>
        <Link
          href={entryHref(entry)}
          onClick={() => markTaskSeen(entry.id)}
          className="mt-1.5 inline-flex h-6 items-center rounded-md border border-border2 px-2 text-micro text-text transition-colors hover:bg-hairline"
        >
          Open
        </Link>
      </div>
      <button
        type="button"
        onClick={dismissToast}
        aria-label="Dismiss"
        className="flex size-5 flex-shrink-0 items-center justify-center rounded text-faint hover:bg-hairline hover:text-text"
      >
        <X className="size-3" />
      </button>
    </div>
  );
}
