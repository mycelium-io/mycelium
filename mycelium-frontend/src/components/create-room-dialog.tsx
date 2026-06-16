// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { createRoom } from "@/lib/api";

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
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={handleClose}>
      <div className="bg-surface border border-border rounded-xl p-6 w-[420px] shadow-2xl" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold mb-4">Create Room</h2>

        <label className="block text-sm text-muted mb-1">Name</label>
        <input
          className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm font-mono focus:border-accent/50 focus:outline-none mb-4"
          value={name}
          onChange={e => {
            setName(e.target.value);
            if (error) setError(null);
          }}
          placeholder="design-review"
        />

        {error && (
          <p role="alert" className="text-sm text-red-400 mb-4 break-words">
            {error}
          </p>
        )}

        <div className="flex gap-3 justify-end">
          <button onClick={handleClose} className="px-4 py-2 text-sm text-muted hover:text-white transition-colors">
            Cancel
          </button>
          <button
            onClick={handleCreate}
            disabled={!name || loading}
            className="px-4 py-2 bg-accent/20 text-accent border border-accent/30 rounded-lg text-sm font-bold hover:bg-accent/30 transition-all disabled:opacity-50"
          >
            {loading ? "Creating..." : "Create"}
          </button>
        </div>
      </div>
    </div>
  );
}
