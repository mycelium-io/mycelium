// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { Loader2, Mic } from "lucide-react";
import type { MicState } from "@/components/voice/use-voice-input";
import { KbdChord } from "@/components/ui/kbd";
import { Tooltip } from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

/** The composer's mic: a toggle that stays on until it's pressed again (or its
 *  key, named in the tooltip). A ring breathes while it hears speech, so you
 *  can see it's listening. */
export function MicToggle({
  state,
  speaking,
  onToggle,
}: {
  state: MicState;
  speaking: boolean;
  onToggle: () => void;
}) {
  const on = state !== "off";
  const label = on ? "Turn the mic off" : "Turn the mic on";
  return (
    <Tooltip
      content={
        <span className="inline-flex items-center gap-1.5">
          {label} <KbdChord size="xs" tone="muted" action="composer.mic" />
        </span>
      }
    >
      <button
        type="button"
        onMouseDown={(e) => e.preventDefault()}
        onClick={onToggle}
        aria-pressed={on}
        aria-label={label}
        className={cn(
          "relative grid size-8 shrink-0 place-items-center rounded-md transition-colors",
          on ? "bg-accent-soft text-accent" : "text-muted-foreground hover:bg-accent-soft hover:text-accent",
        )}
      >
        {state === "starting" ? <Loader2 className="size-4 animate-spin" /> : <Mic className="size-4" />}
        {state === "listening" && (
          <span
            aria-hidden
            className={cn(
              "pointer-events-none absolute inset-0 rounded-md ring-2 ring-accent/60 transition-opacity",
              speaking ? "animate-pulse opacity-100" : "opacity-30",
            )}
          />
        )}
      </button>
    </Tooltip>
  );
}
