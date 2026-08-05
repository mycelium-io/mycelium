// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Button } from "@/components/ui/button";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";
import type { PendingInvite } from "@/lib/api";

interface Props {
  invite: PendingInvite | null;
  onAccept: (invite: PendingInvite) => void;
  onDecline: (invite: PendingInvite) => void;
}

/**
 * Consent-to-be-woken prompt (Step 6, the hero-demo differentiator). When a
 * human `@`-mentions an agent that isn't in the room yet, the backend raises a
 * pending invite and pushes a `consent_request` event; this surfaces it as an
 * accept/decline call. It should feel like accepting a phone call — nothing
 * joins until Accept, and dismissing the prompt declines.
 */
export function ConsentDialog({ invite, onAccept, onDecline }: Props) {
  return (
    <Dialog
      open={invite !== null}
      onOpenChange={(next) => {
        if (!next && invite) onDecline(invite);
      }}
    >
      {invite && (
        <DialogContent showCloseButton={false}>
          <DialogHeader>
            <DialogTitle>Incoming agent request</DialogTitle>
            <DialogDescription>
              <span className="font-medium text-foreground">@{invite.requested_by}</span> wants to
              bring <span className="font-medium text-foreground">@{invite.agent}</span> into this
              room.
              {invite.trigger_text ? (
                <span className="mt-2 block italic">“{invite.trigger_text}”</span>
              ) : null}
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => onDecline(invite)}>
              Decline
            </Button>
            <Button onClick={() => onAccept(invite)}>Accept</Button>
          </DialogFooter>
        </DialogContent>
      )}
    </Dialog>
  );
}
