// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { ArrowDown } from "lucide-react";
import { Button } from "@/components/ui/button";

/** The pill that floats over the bottom of a message list once the reader has
 *  scrolled up off its newest message: "Jump to latest", or "3 new messages"
 *  when messages have landed meanwhile. Its parent must be `relative`. Every
 *  list drives it the same way (`messages/use-follow-latest.ts`). */
export function JumpToLatest({ unread, onClick }: { unread: number; onClick: () => void }) {
  return (
    <div className="pointer-events-none absolute inset-x-0 bottom-3 flex justify-center">
      <Button
        size="sm"
        variant="secondary"
        onClick={onClick}
        aria-label={unread > 0 ? `Jump to latest, ${unread} new` : "Jump to latest"}
        className="pointer-events-auto rounded-full border-border bg-elevated shadow-lg motion-safe:animate-in motion-safe:fade-in-0 motion-safe:slide-in-from-bottom-1"
      >
        <ArrowDown className="size-3.5" />
        {unread > 0 ? `${unread} new ${unread === 1 ? "message" : "messages"}` : "Jump to latest"}
      </Button>
    </div>
  );
}
