// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Copy, MoreHorizontal, Trash2 } from "lucide-react";
import { DeleteRoomDialog } from "@/components/delete-room-dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

/**
 * The room's `…` menu in the header: what you do to the room rather than in
 * it. The room's MAS id lives here to be copied, not beside the name, and
 * deleting sits behind a menu instead of an icon next to the title.
 */
export function RoomMenu({ roomName, masId }: { roomName: string; masId: string | null }) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [copied, setCopied] = useState(false);

  const copyId = async () => {
    if (!masId) return;
    try {
      await navigator.clipboard.writeText(masId);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1200);
    } catch {
      // Clipboard blocked: the id is still shown to select by hand.
    }
  };

  const item =
    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-label transition-colors hover:bg-hairline";

  return (
    <>
      <Popover open={open} onOpenChange={setOpen}>
        <PopoverTrigger
          aria-label={`${roomName} options`}
          className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
        >
          <MoreHorizontal className="size-4" />
        </PopoverTrigger>
        <PopoverContent align="end" className="w-60 p-1">
          {masId && (
            <button type="button" onClick={copyId} className={item}>
              {copied ? (
                <Check className="size-3.5 flex-shrink-0 text-accent" />
              ) : (
                <Copy className="size-3.5 flex-shrink-0 text-muted-foreground" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block text-text">{copied ? "Copied" : "Copy room id"}</span>
                <span className="block truncate font-mono text-micro text-faint">{masId}</span>
              </span>
            </button>
          )}
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              setDeleteOpen(true);
            }}
            className={`${item} text-red`}
          >
            <Trash2 className="size-3.5 flex-shrink-0" />
            Delete room…
          </button>
        </PopoverContent>
      </Popover>
      <DeleteRoomDialog
        roomName={roomName}
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onDeleted={() => router.push("/")}
      />
    </>
  );
}
