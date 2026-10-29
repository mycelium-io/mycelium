// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { AlertTriangle } from "lucide-react";
import { Monogram } from "@/components/ui/monogram";
import { Button } from "@/components/ui/button";
import { Kbd } from "@/components/ui/kbd";
import type { MentionGroupMember, MentionGroups } from "@/lib/api";
import type { ComposerMentionKind } from "@/lib/composer-mentions";
import type { MentionGroupName } from "@/lib/mentions";
import { Ago } from "@/lib/relative-time";

/** A group listed one member per row up to this many; more are drawn as a
 *  count and a row of faces per kind. */
const LIST_UP_TO = 6;
const FACES = 8;

/** A message that would wake this many agents asks before it goes. */
export const WAKE_WARN_AT = 4;

/** What a group mention does to the members it reaches, in the form it's written. */
export function groupReach(groups: MentionGroups, name: MentionGroupName, kind: ComposerMentionKind) {
  const members = groups[name].members;
  // `@!` stops only an agent that's mid-turn. The rest are mentioned as usual.
  const stopped = kind === "interrupt" ? members.filter((m) => m.kind === "agent" && m.status === "working") : [];
  return { members, stopped };
}

function note(m: MentionGroupMember) {
  if (m.role === "holder" && !m.posted_at) return <>holds it · hasn&apos;t posted</>;
  if (m.role === "assignee" && !m.posted_at) return <>it&apos;s for them · hasn&apos;t posted</>;
  const state = m.kind === "person" ? "person" : m.status === "working" ? "working" : m.status === "blocked" ? "blocked" : "waiting";
  return m.posted_at ? (
    <>
      {state} · posted <Ago at={m.posted_at} />
    </>
  ) : (
    <>{state}</>
  );
}

/**
 * Who `@here` or `@all` reaches, beside the `@` list while a group is lit and
 * over the box while the cursor is on one already written. It reads the same
 * answer the hub delivers by, so the count is who gets woken.
 */
export function GroupMentionCard({
  groups,
  name,
  kind,
  inThread,
}: {
  groups: MentionGroups;
  name: MentionGroupName;
  kind: ComposerMentionKind;
  inThread: boolean;
}) {
  const { members, stopped } = groupReach(groups, name, kind);
  const sigil = kind === "interrupt" ? "@!" : kind === "silent" ? "@~" : "@";
  const verb = kind === "interrupt" ? "interrupts" : kind === "silent" ? "names" : "pings";
  const count = kind === "interrupt" ? stopped.length : groups[name].count;
  const scope = name === "here" && inThread ? "Everyone in this task" : "Everyone in the room";
  const people = members.filter((m) => m.kind === "person");
  const agents = members.filter((m) => m.kind === "agent");
  return (
    <div
      role="dialog"
      aria-label={`Who ${sigil}${name} reaches`}
      className="w-64 shrink-0 rounded-xl border border-border bg-elevated p-1 shadow-xl"
    >
      <div className="flex items-baseline gap-2 px-2.5 pt-1.5 pb-1">
        <span className="font-mono text-label text-accent">
          {sigil}
          {name}
        </span>
        <span className="text-micro tabular text-muted-foreground">
          {verb} {count}
        </span>
      </div>
      <div className="px-2.5 pb-1 text-micro text-muted-foreground">{scope}</div>
      {members.length === 0 ? (
        <p className="px-2.5 pb-1.5 text-micro text-muted-foreground">Nobody else yet.</p>
      ) : members.length <= LIST_UP_TO ? (
        members.map((m) => (
          <div key={m.handle} className="flex items-center gap-2 rounded-lg px-2.5 py-1">
            <Monogram
              handle={m.handle}
              kind={m.kind}
              className="size-5 text-[9px]"
              presence={m.kind === "agent" ? "herdr" : undefined}
              status={m.status ?? undefined}
              mutePresence
            />
            <span className="text-label text-text">{m.handle}</span>
            <span className="ml-auto truncate text-micro text-muted-foreground">{note(m)}</span>
          </div>
        ))
      ) : (
        [
          { label: "People", list: people, kind: "person" as const },
          { label: "Agents", list: agents, kind: "agent" as const },
        ]
          .filter((g) => g.list.length > 0)
          .map((g) => (
            <div key={g.label} className="px-2.5 py-1.5">
              <div className="flex items-baseline gap-1.5 text-micro">
                <span className="text-text">{g.label}</span>
                <span className="tabular text-muted-foreground">{g.list.length}</span>
              </div>
              <div className="mt-1 flex -space-x-1.5">
                {g.list.slice(0, FACES).map((m) => (
                  <div key={m.handle} className="rounded-full ring-2 ring-elevated">
                    <Monogram handle={m.handle} kind={g.kind} className="size-6 text-[9px]" />
                  </div>
                ))}
                {g.list.length > FACES && (
                  <span className="z-10 flex size-6 items-center justify-center rounded-full bg-hairline text-[9px] text-muted-foreground ring-2 ring-elevated">
                    +{g.list.length - FACES}
                  </span>
                )}
              </div>
              <div className="mt-1 truncate text-micro text-muted-foreground">
                {g.list.map((m) => m.handle).join(", ")}
              </div>
            </div>
          ))
      )}
    </div>
  );
}

/** What a message would wake, worked out from the group mentions in it. */
export interface BigSend {
  agents: number;
  people: number;
  interruptsAll: boolean;
}

/** The warning before a message that wakes many agents goes. */
export function BigSendWarning({
  send,
  onCancel,
  onSilent,
  onSend,
}: {
  send: BigSend;
  onCancel: () => void;
  onSilent: () => void;
  onSend: () => void;
}) {
  const agents = `${send.agents} agent${send.agents === 1 ? "" : "s"}`;
  return (
    <div role="alertdialog" aria-label="Wake many agents?" className="rounded-lg border border-yellow/40 bg-elevated px-3 py-2.5 shadow-lg">
      <div className="flex items-start gap-2">
        <AlertTriangle className="mt-0.5 size-3.5 shrink-0 text-yellow" />
        <div className="min-w-0 flex-1">
          <p className="text-label text-text">
            This wakes <span className="font-semibold">{agents}</span>
            {send.people > 0 && `, and notifies ${send.people} ${send.people === 1 ? "person" : "people"}`}.
            {send.interruptsAll && " Any agent in the middle of a turn is stopped."}
          </p>
          <p className="mt-0.5 text-micro text-muted-foreground">
            Each one starts a turn to read it. Send it silently to tag them without waking anyone.
          </p>
        </div>
      </div>
      <div className="mt-2.5 flex items-center justify-end gap-1.5">
        <Button variant="ghost" size="xs" onMouseDown={(e) => e.preventDefault()} onClick={onCancel}>
          Cancel <Kbd size="xs" tone="muted">esc</Kbd>
        </Button>
        <Button variant="outline" size="xs" onMouseDown={(e) => e.preventDefault()} onClick={onSilent}>
          Send silently
        </Button>
        <Button size="xs" onMouseDown={(e) => e.preventDefault()} onClick={onSend}>
          Wake {send.agents} <Kbd size="xs" tone="muted">↵</Kbd>
        </Button>
      </div>
    </div>
  );
}

/** Turns every group mention in `text` silent, leaving mentions of members as they are. */
export function silenceGroups(text: string): string {
  return text.replace(/(^|[\s(<])@[!~]?(here|all)\b/gi, (_, lead: string, name: string) => `${lead}@~${name}`);
}
