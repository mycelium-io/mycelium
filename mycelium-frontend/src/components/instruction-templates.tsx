// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { ChevronDown, Trash2 } from "lucide-react";
import {
  BUILT_IN,
  deleteTemplate,
  loadSaved,
  saveTemplate,
  type InstructionTemplate,
} from "@/lib/instruction-templates";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Button } from "@/components/ui/button";

/**
 * A menu of instruction templates to start from, and a way to keep your own.
 * Yours are saved in this browser only.
 */
export function InstructionTemplates({
  current,
  onPick,
}: {
  /** What the instructions box holds now, which "Save as a template" keeps. */
  current: string;
  onPick: (template: InstructionTemplate) => void;
}) {
  const [open, setOpen] = useState(false);
  const [saved, setSaved] = useState<InstructionTemplate[]>([]);
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
        Templates <ChevronDown className="size-3" />
      </PopoverTrigger>
      <PopoverContent className="w-72 p-1" align="end">
        {[...saved, ...BUILT_IN].map((t) => (
          <div key={`${t.saved ? "saved" : "built"}-${t.name}`} className="group flex items-start">
            <button
              type="button"
              onClick={() => {
                onPick(t);
                setOpen(false);
              }}
              className="min-w-0 flex-1 rounded-md px-2.5 py-1.5 text-left hover:bg-hairline"
            >
              <span className="block text-label font-medium text-text">
                {t.name}
                {t.saved && <span className="ml-1.5 text-micro font-normal text-faint">yours</span>}
              </span>
              <span className="line-clamp-1 text-micro text-muted-foreground">{t.text}</span>
            </button>
            {t.saved && (
              <button
                type="button"
                aria-label={`Delete ${t.name}`}
                onClick={() => setSaved(deleteTemplate(t.name))}
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
                setSaved(saveTemplate(name, current));
                setName("");
                setNaming(false);
              }}
            >
              <input
                autoFocus
                aria-label="Template name"
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
              {canSave ? "Save these instructions as a template" : "Write instructions to save them"}
            </button>
          )}
        </div>
      </PopoverContent>
    </Popover>
  );
}
