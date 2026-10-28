// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { memo, useCallback, useLayoutEffect, useMemo, useRef, useState } from "react";
import { ChevronDown, ChevronUp } from "lucide-react";
import { MarkdownContent, type ThreadTarget } from "@/components/markdown-content";
import type { Highlight } from "@/components/ui/highlight-text";
import { AttachmentStrip } from "@/components/uploads/attachment-strip";
import { UploadPreviewDialog } from "@/components/uploads/upload-preview";
import type { Upload } from "@/lib/api";
import { useRoomUploads } from "@/lib/room-data";
import { isUploadKey, uploadKeysIn, withoutTrailingUploadLinks } from "@/lib/uploads";

/** How tall a message's prose gets before it clamps behind a "Show more" —
 *  roughly eight lines of body text. Long enough that ordinary messages never
 *  clamp, short enough that a wall of text can't swallow the timeline. */
const CLAMP_PX = 168;

/** The clamp's fade is a mask on the prose rather than a gradient painted over
 *  it, so it fades into whatever the message sits on: the channel's page, a
 *  thread's surface card, the memory tab's paper. */
const CLAMP_MASK = "linear-gradient(to bottom, black calc(100% - 3.5rem), transparent)";
/** A fold is a line or two, so it fades over less of it. */
const FOLD_MASK = "linear-gradient(to bottom, black calc(100% - 1.25rem), transparent)";

/**
 * A message's prose, clamped when it runs long.
 *
 * Both the room channel and a task's discussion are scannable logs, so one
 * message shouldn't be able to fill the viewport. Past ~eight lines the body is
 * capped with a soft fade and a muted "Show more" toggle; expanding is in place
 * and reversible, and nothing is summarized or thrown away — the reader still
 * gets every word on demand. Only the measured-too-tall case grows the control,
 * so short messages are untouched. Shared by the channel (`event-stream`) and
 * the thread pane (`task-conversation`) so the affordance is identical in both.
 */
export const MessageBody = memo(MessageBodyImpl, sameBody);

interface MessageBodyProps {
  content: string;
  hit?: Highlight;
  /** Words the verifier couldn't confirm, underlined. A find hit draws instead
   *  while one is open. */
  claims?: string[];
  onOpenMemory?: (key: string) => void;
  /** The room the message is in. With it, the files the message links are
   *  drawn under it and a link to one opens its preview. */
  roomName?: string;
  /** Fold to this height instead (px): for prose that says again what is
   *  drawn above it, such as a reply whose values are shown as bars. */
  foldTo?: number;
  /** The room's threads by short id: a thread id the message quotes gets a
   *  link to its task. */
  threads?: ReadonlyMap<string, ThreadTarget>;
  onOpenThread?: (episode: string) => void;
}

/** Whether a message would draw the same: its text, where it links, and its
 *  find mark compared by what it marks rather than by object. A channel
 *  re-renders on every keystroke in its find bar, and re-parsing every loaded
 *  message's markdown each time is what made find slow. */
function sameBody(a: MessageBodyProps, b: MessageBodyProps): boolean {
  return (
    a.content === b.content &&
    a.onOpenMemory === b.onOpenMemory &&
    a.roomName === b.roomName &&
    a.foldTo === b.foldTo &&
    a.threads === b.threads &&
    a.onOpenThread === b.onOpenThread &&
    a.hit?.query === b.hit?.query &&
    a.hit?.active === b.hit?.active &&
    (a.claims ?? []).join("\n") === (b.claims ?? []).join("\n")
  );
}

function MessageBodyImpl({ content, hit, claims, onOpenMemory, roomName, foldTo, threads, onOpenThread }: MessageBodyProps) {
  const clampPx = foldTo ?? CLAMP_PX;
  // A fold is asked for, so even a little more than it folds; the usual clamp
  // leaves a message that is only a little long alone.
  const slack = foldTo === undefined ? 24 : 4;
  const claimKey = (claims ?? []).join("\n");
  const marks = useMemo<Highlight | undefined>(
    () => hit ?? (claimKey ? { query: claimKey.split("\n"), variant: "claim" } : undefined),
    [hit, claimKey],
  );
  const ref = useRef<HTMLDivElement>(null);
  const [overflows, setOverflows] = useState(false);
  const [expanded, setExpanded] = useState(false);
  const [previewing, setPreviewing] = useState<Upload | null>(null);
  const attached = useMemo(() => (roomName ? uploadKeysIn(content) : []), [roomName, content]);
  // The files are drawn under the prose, so the line of links naming them isn't repeated above.
  const prose = attached.length ? withoutTrailingUploadLinks(content) : content;
  const { uploads } = useRoomUploads(attached.length ? (roomName ?? "") : "");
  // This message's files, in the order it links them: what the preview steps through.
  const attachedUploads = useMemo(
    () => attached.flatMap((key) => uploads.filter((u) => u.key === key)),
    [attached, uploads],
  );

  // An upload's chip in the prose opens the same preview its card does; any
  // other memory link goes where it always went.
  const openLink = useCallback(
    (key: string) => {
      const upload = isUploadKey(key) ? uploads.find((u) => u.key === key) : undefined;
      if (upload) setPreviewing(upload);
      else onOpenMemory?.(key);
    },
    [uploads, onOpenMemory],
  );

  // Measure the natural height (scrollHeight ignores the clamp) and re-measure on
  // width changes, since re-wrapping changes how tall the prose is.
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || typeof ResizeObserver === "undefined") {
      if (el) setOverflows(el.scrollHeight > clampPx + slack);
      return;
    }
    const measure = () => setOverflows(el.scrollHeight > clampPx + slack);
    measure();
    const observer = new ResizeObserver(measure);
    observer.observe(el);
    return () => observer.disconnect();
  }, [content, clampPx, slack]);

  // A find match forces the message open: the hit could be in the clamped-off
  // tail, and a highlight the reader can't see is a broken search. The manual
  // toggle steps aside while a match holds it open.
  const forceOpen = Boolean(hit);
  const clamped = overflows && !expanded && !forceOpen;

  return (
    <>
      <div
        ref={ref}
        className="overflow-hidden"
        style={
          clamped
            ? {
                maxHeight: clampPx,
                maskImage: foldTo === undefined ? CLAMP_MASK : FOLD_MASK,
                WebkitMaskImage: foldTo === undefined ? CLAMP_MASK : FOLD_MASK,
              }
            : undefined
        }
      >
        <MarkdownContent
          className="contrast text-body leading-relaxed"
          onLinkClick={onOpenMemory || attached.length ? openLink : undefined}
          highlight={marks}
          threads={threads}
          onOpenThread={onOpenThread}
        >
          {prose}
        </MarkdownContent>
      </div>
      {/* With the prose it opens, above any files the message carries. */}
      {overflows && !forceOpen && (
        <button
          type="button"
          onClick={() => setExpanded((v) => !v)}
          className="mt-1 inline-flex items-center gap-0.5 text-micro font-medium text-muted-foreground transition-colors hover:text-text"
        >
          {expanded ? (
            <>Show less <ChevronUp className="size-3" /></>
          ) : (
            <>Show more <ChevronDown className="size-3" /></>
          )}
        </button>
      )}
      {roomName && attached.length > 0 && (
        <>
          <AttachmentStrip roomName={roomName} keys={attached} onOpen={setPreviewing} />
          <UploadPreviewDialog
            upload={previewing}
            onClose={() => setPreviewing(null)}
            onOpenMemory={onOpenMemory}
            set={attachedUploads}
            onShow={setPreviewing}
          />
        </>
      )}
    </>
  );
}
