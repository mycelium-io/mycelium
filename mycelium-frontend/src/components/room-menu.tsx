// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { useRouter } from "next/navigation";
import { Check, Copy, Link2, Lock, MoreHorizontal, Trash2, Users } from "lucide-react";
import { setRoomPrivate } from "@/lib/api";
import { useRooms } from "@/lib/room-data";
import { usePrincipal } from "@/components/current-user";
import { DeleteRoomDialog } from "@/components/delete-room-dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

/**
 * The room's `…` menu in the header: what you do to the room rather than in
 * it. The link to what you're looking at and the room's MAS id live here to be
 * copied, not beside the name, and deleting sits behind a menu instead of an
 * icon next to the title. The link matters most in the Mac app, which has no
 * address bar to copy it from.
 */
export function RoomMenu({
  roomName,
  masId,
  isPrivate = false,
  onChanged,
}: {
  roomName: string;
  masId: string | null;
  /** Listed only for its owner and members. */
  isPrivate?: boolean;
  /** Called after the room itself changed, so its reader can refetch. */
  onChanged?: () => void;
}) {
  const router = useRouter();
  const principal = usePrincipal();
  const { refresh: refreshRooms } = useRooms();
  const [open, setOpen] = useState(false);
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [copied, setCopied] = useState<"link" | "id" | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  // Read when the menu opens, so it names the task or view open right now.
  const link = open && typeof window !== "undefined" ? window.location.href : "";

  const copy = async (what: "link" | "id", text: string) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopied(what);
      window.setTimeout(() => setCopied(null), 1200);
    } catch {
      // Clipboard blocked: the text is still shown to select by hand.
    }
  };

  const togglePrivate = async () => {
    if (busy) return;
    setBusy(true);
    setError(null);
    try {
      await setRoomPrivate(roomName, !isPrivate, principal);
      onChanged?.();
      refreshRooms();
      setOpen(false);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Couldn't change the room");
    } finally {
      setBusy(false);
    }
  };

  const item =
    "flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-label transition-colors hover:bg-hairline";

  return (
    <>
      <Popover
        open={open}
        onOpenChange={next => {
          setOpen(next);
          if (!next) setError(null);
        }}
      >
        <PopoverTrigger
          aria-label={`${roomName} options`}
          className="flex size-7 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
        >
          <MoreHorizontal className="size-4" />
        </PopoverTrigger>
        <PopoverContent align="end" className="w-60 p-1">
          <button type="button" onClick={() => copy("link", link)} className={item}>
            {copied === "link" ? (
              <Check className="size-3.5 flex-shrink-0 text-accent" />
            ) : (
              <Link2 className="size-3.5 flex-shrink-0 text-muted-foreground" />
            )}
            <span className="min-w-0 flex-1">
              <span className="block text-text">{copied === "link" ? "Copied" : "Copy link"}</span>
              <span className="block truncate font-mono text-micro text-faint">{link}</span>
            </span>
          </button>
          {masId && (
            <button type="button" onClick={() => copy("id", masId)} className={item}>
              {copied === "id" ? (
                <Check className="size-3.5 flex-shrink-0 text-accent" />
              ) : (
                <Copy className="size-3.5 flex-shrink-0 text-muted-foreground" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block text-text">{copied === "id" ? "Copied" : "Copy room id"}</span>
                <span className="block truncate font-mono text-micro text-faint">{masId}</span>
              </span>
            </button>
          )}
          {/* Making a room private needs someone to list it for; sharing it
              again needs nobody. */}
          {(isPrivate || principal) && (
            <button type="button" onClick={togglePrivate} disabled={busy} className={item}>
              {isPrivate ? (
                <Users className="size-3.5 flex-shrink-0 text-muted-foreground" />
              ) : (
                <Lock className="size-3.5 flex-shrink-0 text-muted-foreground" />
              )}
              <span className="min-w-0 flex-1">
                <span className="block text-text">{isPrivate ? "Share with everyone" : "Make private"}</span>
                <span className="block text-micro text-faint">
                  {isPrivate ? "List it for everyone on the hub" : "Hide it from other people's room lists"}
                </span>
              </span>
            </button>
          )}
          {error && (
            <p role="alert" className="px-2 py-1 text-micro break-words text-red">
              {error}
            </p>
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
