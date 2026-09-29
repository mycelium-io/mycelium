// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { CheckCheck, MessageSquare, Split, UserPlus, type LucideIcon } from "lucide-react";
import { IntentDialog } from "@/components/intent-dialog";
import { AddMemberDialog } from "@/components/add-member-dialog";
import { useRoomAgents } from "@/lib/room-data";
import type { IntentId } from "@/lib/intents";

const STARTERS: { intent: IntentId; icon: LucideIcon; label: string; hint: string }[] = [
  {
    intent: "review",
    icon: CheckCheck,
    label: "Have one agent build something and another check it",
    hint: "The reviewer runs it and sends findings back until it passes.",
  },
  {
    intent: "split",
    icon: Split,
    label: "Put a few agents on one task",
    hint: "They say what they'd take, then the first one splits it into parts.",
  },
];

/**
 * What an empty room offers instead of an empty card: the things it is for,
 * each one click away. Each files a task and starts it in that task's thread.
 * A room with no agents yet leads with adding one, since nothing else here
 * can start without them.
 */
export function RoomStarters({
  roomName,
  onStarted,
}: {
  roomName: string;
  onStarted?: (episode: string) => void;
}) {
  const [open, setOpen] = useState<IntentId | null>(null);
  const [adding, setAdding] = useState(false);
  const { agents, loading, refresh } = useRoomAgents(roomName);
  const noAgents = !loading && agents.every(a => a.adapter === "engine");

  return (
    <div className="mx-auto flex h-full max-w-md flex-col justify-center px-6 py-10">
      <p className="mb-3 px-2 text-micro font-medium text-faint">Start something</p>
      {noAgents && (
        <Starter
          icon={UserPlus}
          label="Add an agent to this room"
          hint="A coding agent on your machine, or one the hub runs. The rest of this list needs one."
          onClick={() => setAdding(true)}
        />
      )}
      {STARTERS.map(s => (
        <Starter key={s.intent} icon={s.icon} label={s.label} hint={s.hint} onClick={() => setOpen(s.intent)} />
      ))}
      <div className="flex items-start gap-2.5 px-2 py-2">
        <MessageSquare className="mt-0.5 size-4 flex-shrink-0 text-faint" />
        <span className="text-micro text-muted-foreground">
          Or just talk: @-mention an agent below, or use + to file a task for later.
        </span>
      </div>
      {open && (
        <IntentDialog
          roomName={roomName}
          initial={open}
          onClose={() => setOpen(null)}
          onStarted={onStarted}
        />
      )}
      <AddMemberDialog open={adding} onOpenChange={setAdding} roomName={roomName} onAdded={refresh} />
    </div>
  );
}

function Starter({
  icon: Icon,
  label,
  hint,
  onClick,
}: {
  icon: LucideIcon;
  label: string;
  hint: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex w-full items-start gap-2.5 rounded px-2 py-2 text-left transition-colors hover:bg-hairline"
    >
      <Icon className="mt-0.5 size-4 flex-shrink-0 text-faint" />
      <span>
        <span className="block text-label text-text">{label}</span>
        <span className="block text-micro text-muted-foreground">{hint}</span>
      </span>
    </button>
  );
}
