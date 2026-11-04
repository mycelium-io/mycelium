// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

/** The link that invites a person into a room, shown so it can be read before
 *  it's sent: selected when it opens, and copied with one button. */
export function InviteDialog({
  open,
  onClose,
  roomName,
  link,
}: {
  open: boolean;
  onClose: () => void;
  roomName: string;
  link: string;
}) {
  const [copied, setCopied] = useState(false);
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(link);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard blocked: the link is selected in the field to copy by hand.
    }
  };
  return (
    <Dialog open={open} onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-md">
        <DialogHeader>
          <DialogTitle>Invite someone to {roomName}</DialogTitle>
          <DialogDescription>
            Send them this link. It opens the room in the Mycelium app if they have it, and offers the download or
            the browser if they don&apos;t.
          </DialogDescription>
        </DialogHeader>
        <textarea
          readOnly
          autoFocus
          rows={2}
          value={link}
          aria-label="Invite link"
          onFocus={(e) => e.currentTarget.select()}
          className="w-full resize-none rounded-lg border border-border bg-bg px-2 py-1.5 font-mono text-micro text-text outline-none focus:border-accent [overflow-wrap:anywhere]"
        />
        <DialogFooter>
          <Button variant="ghost" size="sm" onClick={onClose}>
            Done
          </Button>
          <Button size="sm" onClick={copy}>
            {copied ? <Check className="size-3.5" /> : <Copy className="size-3.5" />}
            {copied ? "Copied" : "Copy link"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
