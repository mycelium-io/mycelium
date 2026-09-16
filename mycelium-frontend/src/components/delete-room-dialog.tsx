// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useEffect, useState } from "react";
import { deleteRoom } from "@/lib/api";
import { Button } from "@/components/ui/button";
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
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (open) setError(null);
  }, [open, roomName]);

  const handleDelete = async () => {
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
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !loading) onClose();
      }}
    >
      <DialogContent>
        <DialogHeader>
          <DialogTitle>Delete “{roomName}”?</DialogTitle>
          <DialogDescription>
            This permanently deletes the room, including its messages and stored memories. This cannot be undone.
          </DialogDescription>
        </DialogHeader>
        {error && (
          <p role="alert" className="text-label text-red break-words">
            {error}
          </p>
        )}
        <DialogFooter>
          <Button variant="outline" onClick={onClose} disabled={loading}>
            Cancel
          </Button>
          <Button variant="destructive" onClick={handleDelete} disabled={loading}>
            {loading ? "Deleting…" : "Delete room"}
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}
