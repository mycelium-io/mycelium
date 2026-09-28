// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { ChevronDown, Trash2 } from "lucide-react";
import {
  BUILT_IN,
  deleteExample,
  loadSaved,
  saveExample,
  type InstructionExample,
} from "@/lib/instruction-examples";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";

/**
 * A menu of example instructions to start from, and a way to keep your own.
 * Yours are saved in this browser only.
 */
export function InstructionExamples({
  current,
  onPick,
}: {
  /** What the instructions box holds now, which "Save as example" keeps. */
  current: string;
  onPick: (example: InstructionExample) => void;
}) {
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<InstructionExample[]>([]);
  const [naming, setNaming] = useState(false);
  const [name, setName] = useState("");

  const canSave = current.trim().length > 0;

  return (
    <Popover
      open={open}
      onOpenChange={(next) => {
        setOpen(next);
        if (next) setSaved(loadSaved());
        else setNaming(false);
      }}
    >
      <PopoverTrigger
        render={
          <button
            type="button"
            className="ml-auto flex items-center gap-1 text-micro text-muted-foreground hover:text-text"
          />
        }
      >
        Examples <ChevronDown className="size-3" />
      </PopoverTrigger>
      <PopoverContent className="w-72 p-1" align="end">
        {[...saved, ...BUILT_IN].map((e) => (
          <div key={`${e.saved ? "saved" : "built"}-${e.name}`} className="group flex items-start">
            <button
              type="button"
              onClick={() => {
                onPick(e);
                setOpen(false);
              }}
              className="min-w-0 flex-1 rounded-md px-2.5 py-1.5 text-left hover:bg-hairline"
            >
              <span className="block text-label font-medium text-text">
                {e.name}
                {e.saved && <span className="ml-1.5 text-micro font-normal text-faint">yours</span>}
              </span>
              <span className="line-clamp-1 text-micro text-muted-foreground">{e.text}</span>
            </button>
            {e.saved && (
              <button
                type="button"
                aria-label={`Delete ${e.name}`}
                onClick={() => setSaved(deleteExample(e.name))}
                className="mt-1.5 mr-1 rounded p-1 text-faint opacity-0 hover:text-red group-hover:opacity-100 focus:opacity-100"
              >
                <Trash2 className="size-3.5" />
              </button>
            )}
          </div>
        ))}
        <div className="mt-1 border-t border-border p-1.5">
          {naming ? (
            <form
              className="flex gap-1.5"
              onSubmit={(ev) => {
                ev.preventDefault();
                if (!name.trim()) return;
                setSaved(saveExample(name, current));
                setName("");
                setNaming(false);
              }}
            >
              <input
                autoFocus
                aria-label="Example name"
                value={name}
                onChange={(ev) => setName(ev.target.value)}
                placeholder="Name"
                className="min-w-0 flex-1 rounded-md border border-border bg-bg px-2 py-1 text-label text-text outline-none focus:border-accent"
              />
              <Button type="submit" size="sm" disabled={!name.trim()}>
                Save
              </Button>
            </form>
          ) : (
            <button
              type="button"
              disabled={!canSave}
              onClick={() => setNaming(true)}
              className="w-full rounded-md px-1.5 py-1 text-left text-micro text-accent hover:bg-hairline disabled:cursor-not-allowed disabled:text-faint disabled:hover:bg-transparent"
            >
              {canSave ? "Save these instructions as an example" : "Write instructions to save them"}
            </button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
