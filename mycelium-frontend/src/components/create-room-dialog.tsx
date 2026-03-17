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
  const [mode, setMode] = useState("async");
  const [threshold, setThreshold] = useState("5");
  const [loading, setLoading] = useState(false);

  if (!open) return null;

  const handleCreate = async () => {
    setLoading(true);
    try {
      const trigger = mode !== "sync" ? { type: "threshold", min_contributions: parseInt(threshold) } : undefined;
      await createRoom({ name, mode, trigger_config: trigger, is_persistent: mode !== "sync" });
      onCreated();
      onClose();
      setName("");
    } finally {
      setLoading(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-surface border border-border rounded-xl p-6 w-[420px] shadow-2xl" onClick={e => e.stopPropagation()}>
        <h2 className="text-lg font-bold mb-4">Create Room</h2>

        <label className="block text-sm text-muted mb-1">Name</label>
        <input
          className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm font-mono focus:border-accent/50 focus:outline-none mb-4"
          value={name}
          onChange={e => setName(e.target.value)}
          placeholder="design-review"
        />

        <label className="block text-sm text-muted mb-1">Mode</label>
        <div className="flex gap-2 mb-4">
          {["sync", "async", "hybrid"].map(m => (
            <button
              key={m}
              onClick={() => setMode(m)}
              className={`flex-1 py-2 rounded-lg text-sm font-bold uppercase tracking-wider border transition-all ${
                mode === m
                  ? "border-accent/40 bg-accent/10 text-accent"
                  : "border-border text-muted hover:border-border/80"
              }`}
            >
              {m}
            </button>
          ))}
        </div>

        {mode !== "sync" && (
          <>
            <label className="block text-sm text-muted mb-1">Synthesis trigger (memory threshold)</label>
            <input
              className="w-full bg-bg border border-border rounded-lg px-3 py-2 text-sm font-mono focus:border-accent/50 focus:outline-none mb-4"
              type="number"
              value={threshold}
              onChange={e => setThreshold(e.target.value)}
            />
          </>
        )}

        <div className="flex gap-3 justify-end">
          <button onClick={onClose} className="px-4 py-2 text-sm text-muted hover:text-white transition-colors">
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
