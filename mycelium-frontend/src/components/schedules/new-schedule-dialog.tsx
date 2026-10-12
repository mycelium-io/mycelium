// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Dialog, DialogContent } from "@/components/ui/dialog";
import type { ScheduleDraft } from "@/lib/composer-commands";
import { useRoomSchedules } from "@/lib/room-data";
import { ScheduleForm } from "./schedule-form";

/**
 * The New Schedule form in a dialog, for opening from somewhere other than the
 * Schedules tab: the composer's + menu and its `/schedule` command. It's the
 * same form, with the room's pre-checks read here, and whatever `/schedule`
 * filled in already set. Nothing is saved until the person saves it.
 */
export function NewScheduleDialog({
  roomName,
  draft,
  onClose,
  onSaved,
}: {
  roomName: string;
  draft: ScheduleDraft;
  onClose: () => void;
  onSaved: () => void;
}) {
  const { checks, refresh } = useRoomSchedules(roomName);
  return (
    <Dialog open onOpenChange={(next) => !next && onClose()}>
      <DialogContent className="sm:max-w-xl">
        <ScheduleForm
          roomName={roomName}
          schedule={null}
          draft={draft}
          checks={checks}
          onClose={onClose}
          onSaved={() => {
            refresh();
            onSaved();
          }}
        />
      </DialogContent>
    </Dialog>
  );
}
