// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

/**
 * A wake in an agent's window, drawn from its parts (`lib/wake-digest.ts`):
 * why it woke and the message that woke it, always shown, and the rest of
 * what the hub told it behind a fold. A wake the parser can't read is shown
 * as the text it was.
 */

import { useState } from "react";
import { Bell, ChevronRight } from "lucide-react";
import { parseWake, wakeField, type Wake, type WakeMessage } from "@/lib/wake-digest";
import { MarkdownContent } from "@/components/markdown-content";
import { Monogram } from "@/components/ui/monogram";
import { cn } from "@/lib/utils";

/** Which fields of the rest are worth a person's look, in this order. The
 *  others (Next, Find, Skill) are instructions to the agent. */
const SHOWN = ["Since", "Tasks", "Board", "Held", "Agreed", "Check", "Floor", "Schedule", "Watching"];

const STATE_TONE: Record<string, string> = {
  working: "bg-accent",
  idle: "bg-muted-foreground",
  blocked: "bg-yellow",
  done: "bg-green",
};

export function WakeRow({ text }: { text: string }) {
  const wake = parseWake(text);
  const [open, setOpen] = useState(false);
  const [raw, setRaw] = useState(false);
  if (!wake) return <PlainWake text={text} />;
  const why = wakeField(wake, "Why")[0] ?? "Woken by the room";
  const woke = wake.messages.find((m) => !m.also) ?? null;
  const others = wake.messages.filter((m) => m.also);
  const mentioned = wakeField(wake, "Mentioned");

  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex min-h-7 items-center gap-2 text-left text-micro text-muted-foreground hover:text-text"
      >
        <Bell className="size-3.5 flex-shrink-0 text-faint" aria-hidden />
        <span>{why}</span>
        <ChevronRight className={cn("size-3 flex-shrink-0 transition-transform", open && "rotate-90")} aria-hidden />
      </button>
      <div className="ml-[7px] border-l border-border pl-[14px]">
        {woke && <Quote message={woke} clamp={!open} />}
        {open && (
          <div className="space-y-3 pt-2 pb-1">
            {others.length > 0 && (
              <Group label="Also asking">
                {others.map((m) => (
                  <Quote key={m.id ?? m.body} message={m} clamp />
                ))}
              </Group>
            )}
            {mentioned.length > 1 && (
              <Group label="Named silently">
                <ul className="space-y-0.5">
                  {mentioned.slice(1).map((line) => (
                    <li key={line} className="text-micro text-muted-foreground">
                      {line.replace(/\s+\(mycelium room messages .*\)$/, "")}
                    </li>
                  ))}
                </ul>
              </Group>
            )}
            <Facts wake={wake} />
            {wake.members && wake.members.rows.length > 0 && (
              <Group label={wake.members.title}>
                <ul className="space-y-1">
                  {wake.members.rows.map((row) => (
                    <MemberRow key={`${row.state}${row.text}`} state={row.state} text={row.text} />
                  ))}
                </ul>
              </Group>
            )}
            <button
              type="button"
              onClick={() => setRaw((r) => !r)}
              className="text-micro text-faint hover:text-muted-foreground"
            >
              {raw ? "Hide the wake as sent" : "Show the wake as sent"}
            </button>
            {raw && <pre className="text-micro whitespace-pre-wrap text-muted-foreground">{text}</pre>}
          </div>
        )}
      </div>
    </div>
  );
}

/** A message from the wake: who, where and when, then what they said. */
function Quote({ message: m, clamp }: { message: WakeMessage; clamp: boolean }) {
  return (
    <div className="py-1">
      <div className="flex items-center gap-1.5 text-micro">
        <Monogram handle={m.sender} className="size-4 text-[8px]" />
        <span className="font-medium text-text">@{m.sender}</span>
        <span className="text-faint">
          {m.place} · {m.age}
        </span>
      </div>
      <div
        className={cn(
          "mt-0.5 pl-[22px] text-label text-text [&_p]:my-0.5",
          clamp && "line-clamp-3",
        )}
      >
        <MarkdownContent imagesAsLinks>{m.body}</MarkdownContent>
      </div>
      {m.note && <p className="pl-[22px] text-micro text-faint">{m.note}</p>}
    </div>
  );
}

function Group({ label, children }: { label: string; children: React.ReactNode }) {
  return (
    <section>
      <h4 className="mb-1 text-micro text-faint">{label}</h4>
      {children}
    </section>
  );
}

/** What changed and where its work stands, as label and lines. */
function Facts({ wake }: { wake: Wake }) {
  const facts = SHOWN.flatMap((label) => {
    const lines = wakeField(wake, label);
    return lines.length ? [{ label, lines }] : [];
  });
  if (facts.length === 0) return null;
  return (
    <dl className="grid grid-cols-[4.5rem_minmax(0,1fr)] gap-x-3 gap-y-1 text-micro">
      {facts.map((f) => (
        <div key={f.label} className="contents">
          <dt className="text-faint">{f.label}</dt>
          <dd className="space-y-0.5 text-muted-foreground">
            {f.lines.map((line) => (
              <p key={line}>{line}</p>
            ))}
          </dd>
        </div>
      ))}
    </dl>
  );
}

/** States whose row names one member and what it's on; the rest list handles. */
const ON_SOMETHING = new Set(["working", "blocked"]);

/** A members row: its state, each member's face, and what one is on. */
function MemberRow({ state, text }: { state: string; text: string }) {
  const one = ON_SOMETHING.has(state) ? /^@(\S+)\s+(.*)$/.exec(text) : null;
  const handles = one ? [one[1]] : [...text.matchAll(/@(\S+)/g)].map((m) => m[1]);
  const more = /\+\d+$/.exec(text)?.[0];
  return (
    <li className="flex items-center gap-2 text-micro">
      <span aria-hidden className={cn("size-1.5 flex-shrink-0 rounded-full", STATE_TONE[state] ?? "bg-faint")} />
      <span className="w-14 flex-shrink-0 text-faint">{state}</span>
      <span className="flex -space-x-1">
        {handles.map((h) => (
          <Monogram key={h} handle={h} kind="agent" className="size-4 text-[8px] ring-1 ring-bg" />
        ))}
      </span>
      <span className="truncate text-muted-foreground">
        {handles.map((h) => `@${h}`).join(" ")}
        {one && <span className="text-faint"> {one[2]}</span>}
      </span>
      {more && <span className="text-faint">{more}</span>}
    </li>
  );
}

/** A wake the parser couldn't read: the text, folded, as it was before. */
function PlainWake({ text }: { text: string }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <button
        type="button"
        aria-expanded={open}
        onClick={() => setOpen((o) => !o)}
        className="flex h-7 items-center gap-2 text-micro text-faint hover:text-muted-foreground"
      >
        <Bell className="size-3.5 flex-shrink-0" aria-hidden />
        Woken by the room
        <ChevronRight className={cn("size-3 transition-transform", open && "rotate-90")} aria-hidden />
      </button>
      {open && (
        <p className="mt-0.5 mb-1 ml-[7px] border-l border-border pl-[14px] font-mono text-micro whitespace-pre-wrap text-muted-foreground">
          {text}
        </p>
      )}
    </div>
  );
}
