// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { createRoom } from "@/lib/api";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

export function CreateRoomDialog({ open, onClose, onCreated }: Props) {
  const [name, setName] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  if (!open) return null;

  const handleClose = () => {
    setError(null);
    onClose();
  };

  const handleCreate = async () => {
    setLoading(true);
    setError(null);
    try {
      await createRoom({ name, is_persistent: true });
      onCreated();
      onClose();
      setName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to create room");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 backdrop-blur-sm" onClick={handleClose}>
      <div className="bg-elevated border border-border rounded-xl p-6 w-[420px] shadow-2xl" onClick={e => e.stopPropagation()}>
        <h2 className="text-ui font-semibold text-text mb-1">Create room</h2>
        <p className="text-label text-muted-foreground mb-4">Give it a short, memorable name.</p>

        <Input
          value={name}
          onChange={e => {
            setName(e.target.value);
            if (error) setError(null);
          }}
          onKeyDown={e => e.key === "Enter" && name && !loading && handleCreate()}
          placeholder="design-review"
          autoFocus
        />

        {error && (
          <p role="alert" className="text-label text-red mt-3 break-words">
            {error}
          </p>
        )}

        <div className="flex gap-2 justify-end mt-5">
          <Button variant="ghost" onClick={handleClose}>
            Cancel
          </Button>
          <Button onClick={handleCreate} disabled={!name || loading}>
            {loading ? "Creating…" : "Create room"}
          </Button>
        </div>
      </div>
    </div>
  );
}
