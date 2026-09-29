// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Check, Copy } from "lucide-react";
import { deleteRoom } from "@/lib/api";
import { copyText } from "@/lib/clipboard";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from "@/components/ui/dialog";

interface Props {
  roomName: string;
  open: boolean;
  onClose: () => void;
  onDeleted: () => void;
}

export function DeleteRoomDialog({ roomName, open, onClose, onDeleted }: Props) {
  const [loading, setLoading] = useState(false);

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !loading) onClose();
      }}
    >
      <DialogContent>
        {/* Mounted per opening, so each one starts with an empty field. */}
        {open && (
          <ConfirmDelete
            key={roomName}
            roomName={roomName}
            loading={loading}
            setLoading={setLoading}
            onClose={onClose}
            onDeleted={onDeleted}
          />
        )}
      </DialogContent>
    </Dialog>
  );
}

function ConfirmDelete({
  roomName,
  loading,
  setLoading,
  onClose,
  onDeleted,
}: {
  roomName: string;
  loading: boolean;
  setLoading: (loading: boolean) => void;
  onClose: () => void;
  onDeleted: () => void;
}) {
  const [error, setError] = useState<string | null>(null);
  // Deleting takes typing the room's name, so a misclick can't lose a room.
  const [typed, setTyped] = useState("");
  const [copied, setCopied] = useState(false);
  const confirmed = typed.trim() === roomName;

  const copyName = async () => {
    await copyText(roomName);
    setCopied(true);
    window.setTimeout(() => setCopied(false), 1200);
  };

  const handleDelete = async () => {
    if (!confirmed || loading) return;
    setLoading(true);
    setError(null);
    try {
      await deleteRoom(roomName);
      onDeleted();
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to delete room");
    } finally {
      setLoading(false);
    }
  };

  return (
    <>
      <DialogHeader>
        <DialogTitle>Delete “{roomName}”?</DialogTitle>
        <DialogDescription>
          This permanently deletes the room, including its messages and stored memories. This cannot be undone.
        </DialogDescription>
      </DialogHeader>
      <form
        className="flex flex-col gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void handleDelete();
        }}
      >
        <p className="flex flex-wrap items-center gap-1.5 text-label text-muted-foreground">
          Type
          <span className="inline-flex items-center gap-1 rounded bg-hairline py-0.5 pl-1.5 pr-0.5 font-mono text-text">
            <span className="select-all">{roomName}</span>
            <button
              type="button"
              onClick={() => void copyName()}
              aria-label="Copy the room name"
              title="Copy the room name"
              className="grid size-5 place-items-center rounded text-muted-foreground transition-colors hover:bg-border hover:text-text"
            >
              {copied ? <Check className="size-3 text-accent" /> : <Copy className="size-3" />}
            </button>
          </span>
          to confirm.
        </p>
        <Input
          aria-label="Type the room name to confirm"
          value={typed}
          onChange={(e) => setTyped(e.target.value)}
          placeholder={roomName}
          autoComplete="off"
          spellCheck={false}
          autoFocus
          disabled={loading}
          className="font-mono"
        />
      </form>
      {error && (
        <p role="alert" className="text-label text-red break-words">
          {error}
        </p>
      )}
      <DialogFooter>
        <Button variant="outline" onClick={onClose} disabled={loading}>
          Cancel
        </Button>
        <Button variant="destructive" onClick={handleDelete} disabled={loading || !confirmed}>
          {loading ? "Deleting…" : "Delete room"}
        </Button>
      </DialogFooter>
    </>
  );
}
