// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { Loader2, Plus } from "lucide-react";
import { createRoom } from "@/lib/api";
import { Kbd } from "@/components/ui/kbd";

interface Props {
  open: boolean;
  onClose: () => void;
  onCreated: () => void;
}

/**
 * A room is one name, so it is asked for the way the command palette asks for
 * anything: a slim prompt near the top of the window, Enter to create it, Esc
 * to leave. No card of buttons for a single field.
 */
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
    if (!name.trim() || loading) return;
    setLoading(true);
    setError(null);
    try {
      await createRoom({ name: name.trim(), is_persistent: true });
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
    <div className="fixed inset-0 z-50 flex items-start justify-center p-6 pt-[12vh]">
      <div
        className="absolute inset-0 bg-black/30 motion-safe:animate-in motion-safe:fade-in-0"
        onClick={handleClose}
        aria-hidden
      />
      <div
        role="dialog"
        aria-modal="true"
        aria-label="New room"
        className="relative w-full max-w-md overflow-hidden rounded-lg border border-border bg-elevated shadow-2xl motion-safe:animate-in motion-safe:fade-in-0 motion-safe:zoom-in-95"
      >
        <div className="flex h-11 items-center gap-2.5 px-3">
          {loading ? (
            <Loader2 className="size-4 flex-shrink-0 animate-spin text-accent" />
          ) : (
            <Plus className="size-4 flex-shrink-0 text-faint" />
          )}
          <input
            value={name}
            onChange={e => {
              setName(e.target.value);
              if (error) setError(null);
            }}
            onKeyDown={e => {
              if (e.key === "Enter") void handleCreate();
              if (e.key === "Escape") handleClose();
            }}
            placeholder="Name the room, e.g. design-review"
            aria-label="Room name"
            autoFocus
            spellCheck={false}
            className="min-w-0 flex-1 bg-transparent text-body text-text placeholder:text-faint focus:outline-none"
          />
        </div>
        {error && (
          <p role="alert" className="border-t border-border px-3 py-2 text-label break-words text-red">
            {error}
          </p>
        )}
        <div className="flex items-center gap-3 border-t border-border px-3 py-1.5 text-micro text-faint">
          <span>New room</span>
          <span className="ml-auto flex items-center gap-1">
            <Kbd size="xs" tone="muted">↵</Kbd> create
          </span>
          <span className="flex items-center gap-1">
            <Kbd size="xs" tone="muted">esc</Kbd> cancel
          </span>
        </div>
      </div>
    </div>
  );
}
