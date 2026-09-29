// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState } from "react";
import { ChevronRight, Workflow } from "lucide-react";
import type { ConductorLine } from "@/lib/conductor-line";
import { MessageBody } from "@/components/message-body";

interface Props {
  line: ConductorLine;
  /** The post's prose: the prompt a member was given, kept behind a toggle. */
  text: string;
  onOpenMemory?: (key: string) => void;
}

function Handle({ children }: { children: string }) {
  return <span className="font-medium text-text">{children}</span>;
}

/**
 * One conductor post, drawn from its structured line rather than its prose.
 *
 * The prose is what the members read — the whole prompt, the check-ins so far —
 * and in a thread it reads as the conductor talking over the members. So a
 * turn is one line naming the step and who it went to, with the prompt a click
 * away, and the opening and the end are one line each.
 */
export function ConductorRow({ line, text, onOpenMemory }: Props) {
  const [open, setOpen] = useState(false);
  const expandable = line.event === "turn" || line.event === "open";

  let body: React.ReactNode;
  switch (line.event) {
    case "open":
      body = (
        <>
          <span>Running</span> <span className="font-medium text-accent">{line.protocol}</span>
          {Object.entries(line.roles).map(([role, who]) => (
            <span key={role}>
              {" · "}
              <Handle>{who}</Handle> as {role}
            </span>
          ))}
          {line.members.length > 0 && (
            <span>
              {" · "}
              {line.members.map((m, i) => (
                <span key={m}>
                  {i > 0 && ", "}
                  <Handle>{m}</Handle>
                </span>
              ))}
            </span>
          )}
        </>
      );
      break;
    case "turn":
      body = (
        <>
          <span className="font-medium text-accent">{line.step}</span>
          <span> {line.tell ? "told" : "→"} </span>
          <Handle>{line.to}</Handle>
          <span className="text-faint">
            {" · "}turn {line.turn} of {line.cap}
            {line.rounds ? ` · round ${line.round} of ${line.rounds}` : ""}
          </span>
        </>
      );
      break;
    case "edge": {
      const said =
        line.stance === "accept"
          ? "accepted"
          : line.stance === "reject"
            ? "blocked"
            : line.stance === "silent"
              ? "did not answer"
              : "stated no stance";
      body = (
        <>
          <span className="font-medium text-accent">{line.step}</span>
          <span>: </span>
          <Handle>{line.who}</Handle>
          <span> {said}, on to </span>
          <span className="font-medium text-accent">{line.next}</span>
        </>
      );
      break;
    }
    case "close": {
      const good = line.outcome === "resolved";
      body = (
        <>
          <span className="font-medium" style={{ color: good ? "var(--green)" : "var(--yellow)" }}>
            {good ? "✓" : "✗"} {line.protocol} {good ? "done" : line.outcome}
          </span>
          <span className="text-faint">
            {" · "}
            {line.steps} step{line.steps === 1 ? "" : "s"}
            {!good && line.reason ? ` · ${line.reason}` : ""}
          </span>
        </>
      );
      break;
    }
  }

  return (
    <div data-testid="conductor-row" className="px-5 py-1">
      <div className="flex items-center gap-2 text-micro text-muted-foreground">
        <span className="flex w-7 flex-shrink-0 justify-center" aria-hidden>
          <Workflow className="size-3.5" />
        </span>
        <span className="min-w-0 flex-1 truncate">{body}</span>
        {expandable && text.trim() && (
          <button
            type="button"
            onClick={() => setOpen(v => !v)}
            aria-expanded={open}
            className="flex flex-shrink-0 items-center gap-0.5 rounded px-1 text-faint transition-colors hover:text-text"
          >
            <ChevronRight className={`size-3 transition-transform ${open ? "rotate-90" : ""}`} />
            {line.event === "turn" ? "prompt" : "flow"}
          </button>
        )}
      </div>
      {open && (
        <div className="ml-9 mt-1 rounded-md border border-border px-3 py-2 text-muted-foreground">
          <MessageBody content={text} onOpenMemory={onOpenMemory} />
        </div>
      )}
    </div>
  );
}
