// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import TextareaAutosize from "react-textarea-autosize";
import {
  createEngine,
  createMemories,
  launchRunnerAgent,
  sendRoomMessage,
  type EngineKind,
  type Memory,
  type Runner,
} from "@/lib/api";
import { signFor } from "@/lib/device-key";
import { CandidateList, Signature, type Candidate, type Slot } from "@/components/composer-hints";
import { SendPlaneIcon } from "@/components/send-plane-icon";
import {
  useRoomMemories,
  useRoomProtocols,
  useRoomRevalidate,
  useRoomRoster,
  useRoomSkills,
} from "@/lib/room-data";
import { useKeyAction } from "@/components/keymap-provider";
import { useCurrentUser } from "@/components/current-user";
import { Kbd, KbdChord } from "@/components/ui/kbd";
import { StartSwarmDialog } from "@/components/start-swarm-dialog";
import { IntentDialog } from "@/components/intent-dialog";
import { NewMemoryDialog } from "@/components/new-memory-dialog";
import { AddMemberDialog, ENGINE_KINDS } from "@/components/add-member-dialog";
import { expandPath, handleValid, normHandle, tildePath } from "@/components/launch-agent-dialog";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { MENTION_SIGIL, SILENT_MENTION_SIGIL } from "@/lib/mentions";
import { mentionRank, nameOf, useNames } from "@/lib/people";
import { draftKey, loadDraft, saveDraft } from "@/lib/drafts";
import { FileText, ListTodo, Plus, UserPlus, X } from "lucide-react";
import { parseCapture } from "@/lib/board/capture";
import { fileCapture } from "@/lib/board/file-capture";
import {
  COMPOSER_COMMANDS,
  argValue,
  matchChoices,
  memoryKeyChoices,
  missingArg,
  parseCommand,
  parseSummon,
  type ParsedSummon,
  type Choice,
  type ChoiceSource,
  type ParsedCommand,
} from "@/lib/composer-commands";
import {
  JOB_STATUS_LABEL,
  hostMissing,
  hostOf,
  launchable,
  runnerName,
  useRunnerJob,
  useRunners,
} from "@/lib/runners";
import { STANDARD_FOLDERS, keyProblem } from "@/lib/memory-location";
import { agentLabel } from "@/lib/agent-label";
import { cn } from "@/lib/utils";

interface Props {
  roomName: string;
  /** Fired after a successful POST so the parent can refresh the event stream. */
  onSent?: () => void;
  className?: string;
  /**
   * The thread this composer writes into. Without one it writes to the room —
   * the same composer either way, since a thread is a tag over the room's own
   * channel and not a second place to type.
   */
  episode?: string | null;
  /** What to call that thread in the placeholder, e.g. a task's title. */
  threadLabel?: string | null;
  /** Opens a memory by key, e.g. the one the + or `/memory` just wrote. */
  onOpenMemory?: (key: string) => void;
}

/** What the composer's + adds to the room. */
const ADD_ITEMS = [
  { kind: "task", label: "Task or flow…", about: "work for someone to pick up", icon: ListTodo },
  { kind: "memory", label: "Memory…", about: "something the room should keep", icon: FileText },
  { kind: "member", label: "Agent…", about: "bring an agent or a person in", icon: UserPlus },
] as const;

// Three sigils, three vocabularies, one composer:
//   @   → agents        → inserts `@handle`
//   [[  → memories      → inserts `[[key]]` (resolves to myc://, clickable in chat)
//   /   → skills        → inserts `/name`
// Each detects an in-flight token by the cursor's prefix, offers a candidate
// popover, and inserts on select — the same machinery the `@` mention always had.
// A command's argument with a known set of values (`arg`) completes the same way.
// A conductor summon's flow name (`flow`) completes the same way again.
type TriggerKind = "agent" | "memory" | "skill" | "arg" | "flow";

interface Trigger {
  kind: TriggerKind;
  /** Index where the sigil begins (`@`, `[[`, or `/`) — the start of the replaced span. */
  start: number;
  /** Cursor position (the end of the replaced span). */
  end: number;
  query: string;
  /** An `@~` trigger: the member is named silently (`lib/mentions.ts`). */
  silent?: boolean;
}


/** Detect an in-flight trigger from the cursor's prefix. Order matters: `[[`
 *  is checked before `/` and `@` since a memory key can itself contain slashes. */
function detectTrigger(prefix: string, cursor: number): Trigger | null {
  const mem = prefix.match(/\[\[([^\]\n]*)$/);
  if (mem) {
    return { kind: "memory", start: cursor - mem[1].length - 2, end: cursor, query: mem[1] };
  }
  const agent = prefix.match(/(?:^|\s)(@~?)([a-z0-9._-]*)$/i);
  if (agent) {
    const [, sigil, query] = agent;
    const start = cursor - query.length - sigil.length;
    return { kind: "agent", start, end: cursor, query: query.toLowerCase(), silent: sigil === SILENT_MENTION_SIGIL };
  }
  const skill = prefix.match(/(?:^|\s)\/([a-z0-9._-]*)$/i);
  if (skill) {
    return { kind: "skill", start: cursor - skill[1].length - 1, end: cursor, query: skill[1].toLowerCase() };
  }
  return null;
}

function memoryKey(m: Memory): string {
  return m.key;
}

// Commands are the one kind of `/` that runs rather than inserts a reference,
// and only as the first word of the message: `/task fix it` files a task, while
// a `/name` anywhere else is a skill for an agent to read. They are listed
// ahead of the room's skills, and a skill with the same name is still reachable
// by picking it from the list. What each takes is `lib/composer-commands.ts`.

/** The trigger at `cursor` in `text`: a command argument's values or a summon's
 *  flow first, then the sigils. `conductors` are the handles a summon can start with. */
function triggerAt(text: string, cursor: number, conductors: readonly string[]): Trigger | null {
  const summon = parseSummon(text, cursor, conductors, []);
  if (summon?.active === "flow" && summon.word) {
    const { start, end, value } = summon.word;
    return { kind: "flow", start, end, query: value.slice(0, cursor - start) };
  }
  const parsed = parseCommand(text, cursor);
  if (parsed && parsed.active !== null && parsed.word) {
    const arg = parsed.command.args[parsed.active];
    const { start, end, value } = parsed.word;
    if (arg.choices) return { kind: "arg", start, end, query: value.slice(0, cursor - start) };
    // A new handle is a name being made up, not a member to mention.
    if (arg.names) return null;
  }
  return detectTrigger(text.slice(0, cursor), cursor);
}

/** Which row a new list opens on. An optional argument not yet started opens
 *  on none, so Enter still sends what's there; ↓ or Tab picks from it. */
function openingHighlight(text: string, cursor: number, trigger: Trigger | null): number {
  if (trigger?.kind !== "arg" || trigger.query !== "") return 0;
  const parsed = parseCommand(text, cursor);
  const arg = parsed?.active != null ? parsed.command.args[parsed.active] : undefined;
  return arg?.optional ? -1 : 0;
}

/** The machine an `/agent` starts on: the one named, else the first of yours that can start the harness. */
function pickMachine(machines: Runner[], named: string, harness: string): Runner | undefined {
  if (named) {
    const n = named.toLowerCase();
    return machines.find((r) => r.id.toLowerCase() === n || r.label.toLowerCase() === n);
  }
  const h = harness.toLowerCase();
  return (
    machines.find((r) => launchable(r).some((f) => f.id === h || f.name.toLowerCase() === h)) ??
    machines.find((r) => r.herdr) ??
    machines[0]
  );
}

/** An agent a `/agent` asked a machine to start, followed until it has. */
interface Launch {
  runner: string;
  job: string;
  handle: string;
}

export function RoomChatBox({
  roomName,
  onSent,
  className,
  episode = null,
  threadLabel = null,
  onOpenMemory,
}: Props) {
  const [content, setContent] = useState("");
  // What's typed is kept per room (and per thread) until it's sent, so moving
  // to another room and back finds it where it was. Read after mount, since the
  // server render has no browser storage; `draftFor` says whose text `content`
  // is, so a switch never writes one room's text under another's key.
  const key = draftKey(roomName, episode);
  const [draftFor, setDraftFor] = useState<string | null>(null);
  useEffect(() => {
    if (draftFor === key) saveDraft(key, content);
  }, [content, key, draftFor]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setContent(loadDraft(key));
    setDraftFor(key);
  }, [key]);
  // A human message is sent as the acting-as principal — the single source of
  // "who am I" (the account menu), not a per-composer handle. Anonymous falls
  // back to "user" so the room still has a sender to attribute the message to.
  const { principal } = useCurrentUser();
  const [sending, setSending] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [trigger, setTrigger] = useState<Trigger | null>(null);
  const [highlight, setHighlight] = useState(0);
  // The task a `/swarm` is being started on, while its dialog is open.
  const [swarmTask, setSwarmTask] = useState<string | null>(null);
  const [starting, setStarting] = useState(false);
  // What the + offers, and the title a `/memory` opened the memory dialog with.
  const [adding, setAdding] = useState(false);
  const [memoryTitle, setMemoryTitle] = useState<string | null>(null);
  const [memoryFolder, setMemoryFolder] = useState("context");
  const [addingMember, setAddingMember] = useState(false);
  const inputRef = useRef<HTMLTextAreaElement | null>(null);
  const [scrolls, setScrolls] = useState(false);
  // Where the cursor is, so a command being typed knows which argument it is on.
  const [cursor, setCursor] = useState(0);
  const parsed = useMemo(() => parseCommand(content, cursor), [content, cursor]);
  // What a command that ran says afterwards (an engine added), and an agent
  // being started on a machine, followed until it is in the room.
  const [notice, setNotice] = useState<string | null>(null);
  // The memory a notice is about, so it can offer to open it.
  const [noticeKey, setNoticeKey] = useState<string | null>(null);
  const [launch, setLaunch] = useState<Launch | null>(null);
  const dismissLaunch = useCallback(() => setLaunch(null), []);
  const revalidateRoom = useRoomRevalidate(roomName);
  // Your machines are read only while an `/agent` is being typed.
  const { connected: machines, loading: machinesLoading } = useRunners({
    enabled: parsed?.command.name === "agent",
  });

  // `@` reaches everyone in the room, off the same roster the Members rail
  // renders; `[[` reads the room's memory keys and `/` its skills. All three
  // are shared reads — opening a room fetches each of them once, however many
  // panels are looking.
  const { agents, people } = useRoomRoster(roomName);
  const { memories } = useRoomMemories(roomName);
  const memoryKeys = useMemo(() => memories.map(memoryKey), [memories]);
  const { skills } = useRoomSkills(roomName);

  // A message that starts by mentioning a conductor is a summon, with a
  // grammar of its own. The room's flows are read only once one is started.
  const conductors = useMemo(
    () => agents.filter((a) => a.adapter === "engine" && a.kind === "conductor").map((a) => a.handle.toLowerCase()),
    [agents],
  );
  const summoning = parseSummon(content, content.length, conductors, []) !== null;
  const { protocols } = useRoomProtocols(summoning ? roomName : "");
  const summon = useMemo(
    () => parseSummon(content, cursor, conductors, protocols),
    [content, cursor, conductors, protocols],
  );

  // The composer is a keybind target. Focus lands on the next frame because the
  // same keypress may be switching the channel pane back into view, and a
  // hidden textarea can't take focus.
  useKeyAction("focus.chat", () => {
    requestAnimationFrame(() => inputRef.current?.focus());
  });

  const handleChange = (e: React.ChangeEvent<HTMLTextAreaElement>) => {
    const next = e.target.value;
    setContent(next);
    const at = e.target.selectionStart ?? next.length;
    setCursor(at);
    const found = triggerAt(next, at, conductors);
    setTrigger(found);
    if (found) setHighlight(openingHighlight(next, at, found));
    setError(null);
    setNotice(null);
  };

  // The values an argument can take, as they stand now.
  const choicesFor = useCallback(
    (source: ChoiceSource, p: ParsedCommand): Choice[] => {
      switch (source) {
        case "engine":
          return ENGINE_KINDS.map((e) => ({ value: e.kind, about: e.blurb }));
        case "memory-key":
          return memoryKeyChoices(memoryKeys, STANDARD_FOLDERS, p.word?.value ?? "");
        case "machine":
          return machines.map((r) => ({
            value: r.id,
            about: [r.label !== r.id ? r.label : "", hostOf(r).name].filter(Boolean).join(" · "),
          }));
        case "harness": {
          const named = argValue(p, "machine");
          const pool = named ? machines.filter((r) => r === pickMachine(machines, named, "")) : machines;
          const seen = new Map<string, Choice>();
          for (const r of pool) {
            for (const f of launchable(r)) {
              if (!seen.has(f.id)) {
                // A CLI's version often says its own name again: "2.1.2 (Claude Code)".
                const version = f.version ? ` ${f.version.replace(/\s*\([^)]*\)\s*$/, "")}` : "";
                seen.set(f.id, { value: f.id, about: `${f.name}${version} on ${runnerName(r)}` });
              }
            }
          }
          return [...seen.values()];
        }
        case "folder": {
          const r = pickMachine(machines, argValue(p, "machine"), argValue(p, "harness"));
          return (r?.roots ?? []).map((root) => ({ value: tildePath(root), about: runnerName(r) }));
        }
      }
    },
    [machines, memoryKeys],
  );

  // Agents first, then people — the roster's order, labeled for the popover.
  // A person who gave a name is found by it and shown by it.
  const names = useNames();
  const mentionRoster = useMemo(
    () => [
      ...agents.map((a) => ({
        handle: a.handle,
        name: undefined as string | undefined,
        secondary: agentLabel(a),
        tertiary: a.description as string | undefined,
      })),
      ...people.map((p) => ({
        handle: p.handle,
        name: nameOf(names, p.handle),
        secondary: p.you ? "you" : p.presence?.kind === "slim" ? "person · here" : "person",
        tertiary: undefined as string | undefined,
      })),
    ],
    [agents, people, names],
  );

  const candidates = useMemo<Candidate[]>(() => {
    if (trigger === null) return [];
    if (trigger.kind === "flow") {
      const all = protocols.map((p) => ({ value: p.name, about: p.description }));
      if (all.some((c) => c.value === summon?.flow?.value.toLowerCase())) return [];
      return matchChoices(all, trigger.query)
        .slice(0, 8)
        .map((c) => {
          const roles = protocols.find((p) => p.name === c.value)?.roles ?? [];
          return {
            id: `flow:${c.value}`,
            insert: c.value,
            primary: c.value,
            // Who it asks for, which is what tells two flows apart at a glance.
            secondary: roles.length ? roles.map((r) => `@${r}`).join(" ") : "anyone",
            tertiary: c.about,
          };
        });
    }
    if (trigger.kind === "arg") {
      const arg = parsed?.active != null ? parsed.command.args[parsed.active] : undefined;
      if (!parsed || !arg?.choices) return [];
      const all = choicesFor(arg.choices, parsed);
      // Typed out in full: nothing left to complete, so Enter sends.
      if (all.some((c) => !c.open && c.value === parsed.word?.value)) return [];
      return matchChoices(all, trigger.query)
        .slice(0, 8)
        .map((c) => ({
          id: `arg:${c.value}`,
          insert: c.value,
          open: c.open,
          primary: c.value,
          secondary: arg.name,
          tertiary: c.about,
        }));
    }
    if (trigger.kind === "agent") {
      // Best match first; the roster's own order breaks ties.
      const pool = mentionRoster
        .map((r, i) => ({ r, i, rank: mentionRank(trigger.query, r.handle, r.name) }))
        .filter((x): x is typeof x & { rank: number } => x.rank !== null)
        .sort((a, b) => a.rank - b.rank || a.i - b.i)
        .map((x) => x.r);
      return pool.slice(0, 8).map((r) => ({
        id: r.handle,
        insert: `${trigger.silent ? SILENT_MENTION_SIGIL : MENTION_SIGIL}${r.handle}`,
        primary: r.name ?? `@${r.handle}`,
        named: Boolean(r.name),
        secondary: r.name ? `@${r.handle} · ${r.secondary}` : r.secondary,
        tertiary: r.tertiary,
      }));
    }
    if (trigger.kind === "memory") {
      const q = trigger.query.toLowerCase();
      const pool = q
        ? memories.filter((m) => memoryKey(m).toLowerCase().includes(q))
        : memories;
      return pool.slice(0, 6).map((m) => ({
        id: memoryKey(m),
        insert: `[[${memoryKey(m)}]]`,
        primary: `[[${memoryKey(m)}]]`,
        secondary: "memory",
        tertiary: `v${m.version} · ${m.created_by}`,
      }));
    }
    // `/`: the commands first (only as the message's first word, the one place
    // they run), then the room's skills.
    const q = trigger.query;
    const commands = trigger.start === 0 ? COMPOSER_COMMANDS.filter((c) => c.name.startsWith(q)) : [];
    const pool = q ? skills.filter((s) => s.name.toLowerCase().startsWith(q)) : skills;
    return [
      ...commands.map((c) => ({
        id: `command:${c.name}`,
        insert: `/${c.name}`,
        primary: `/${c.name}`,
        secondary: "command",
        tertiary: c.about,
      })),
      ...pool.slice(0, 6).map((s) => ({
        id: s.name,
        insert: `/${s.name}`,
        primary: `/${s.name}`,
        secondary: "skill",
        tertiary: s.description || undefined,
      })),
    ];
  }, [choicesFor, mentionRoster, memories, parsed, protocols, skills, summon, trigger]);

  const accept = useCallback(
    (candidate: Candidate) => {
      if (trigger === null) return;
      const before = content.slice(0, trigger.start);
      const after = content.slice(trigger.end);
      const insertion = candidate.open ? candidate.insert : `${candidate.insert} `;
      const next = `${before}${insertion}${after}`;
      const pos = before.length + insertion.length;
      setContent(next);
      setCursor(pos);
      // A command's next argument offers its values straight away.
      const following = triggerAt(next, pos, conductors);
      setTrigger(following);
      setHighlight(openingHighlight(next, pos, following));
      // Restore the cursor after the inserted token, unless typing already
      // moved on (a completion is often followed straight away by more).
      requestAnimationFrame(() => {
        const node = inputRef.current;
        if (!node || node.value !== next) return;
        node.focus();
        node.setSelectionRange(pos, pos);
      });
    },
    [conductors, content, trigger],
  );

  // `/agent <handle> <harness> [folder] [machine]`: the same launch the Add
  // member dialog queues, with what it asks for typed instead. Says what is
  // wrong and returns null rather than queuing a start that cannot work.
  const startAgent = useCallback(
    async (command: ParsedCommand, me: string): Promise<Launch | null> => {
      const handle = normHandle(argValue(command, "handle"));
      if (!handleValid(handle)) {
        setError(`@${handle} can't be a handle: use lowercase letters, digits, - and _.`);
        return null;
      }
      const harness = argValue(command, "harness");
      const named = argValue(command, "machine");
      const runner = pickMachine(machines, named, harness);
      if (!runner) {
        setError(
          machinesLoading
            ? "Still looking for your machines. Try again in a moment."
            : named
              ? `None of your machines is called ${named}.`
              : "None of your machines is connected. Start `mycelium runner` on one, then add it from Machines.",
        );
        return null;
      }
      if (!runner.herdr) {
        setError(hostMissing(runner));
        return null;
      }
      const h = harness.toLowerCase();
      const framework = launchable(runner).find((f) => f.id === h || f.name.toLowerCase() === h);
      if (!framework) {
        const can = launchable(runner).map((f) => f.id);
        setError(
          `${runnerName(runner)} can't start ${harness}.` + (can.length ? ` It can start ${can.join(", ")}.` : ""),
        );
        return null;
      }
      const folder = argValue(command, "folder");
      const cwd = folder ? expandPath(folder, runner.roots) : undefined;
      const signature = await signFor(runner, {
        kind: "launch",
        job: { room: roomName, handle, framework: framework.id, cwd: cwd ?? null, worktree: false },
      });
      const job = await launchRunnerAgent(runner.id, {
        room: roomName,
        handle,
        framework: framework.id,
        cwd,
        created_by: me,
        ...(signature ? { signature } : {}),
      });
      return { runner: runner.id, job: job.id, handle };
    },
    [machines, machinesLoading, roomName],
  );

  const submit = useCallback(async () => {
    const body = content.trim();
    if (!body || sending) return;
    const handle = principal.trim() || "user";
    const command = parseCommand(body);
    const cleared = () => {
      setContent("");
      setCursor(0);
      setTrigger(null);
    };
    if (command) {
      const missing = missingArg(command);
      if (missing) {
        setError(missing);
        return;
      }
    }
    const memoryAt = command?.command.name === "memory" ? argValue(command, "key").replace(/\/+$/, "") : "";
    const memoryText = command?.command.name === "memory" ? argValue(command, "text") : "";
    if (command?.command.name === "memory" && !memoryText) {
      // Nothing to write yet: the editor takes it from there, opened where the key points.
      const cut = memoryAt.lastIndexOf("/");
      setMemoryFolder(cut >= 0 ? memoryAt.slice(0, cut) : "context");
      setMemoryTitle(memoryAt.slice(cut + 1).replace(/[-_]+/g, " "));
      cleared();
      return;
    }
    if (command?.command.name === "memory") {
      const problem = keyProblem(memoryAt);
      if (problem) {
        setError(`${problem} The key is folder/name, as in context/launch-plan.`);
        return;
      }
    }
    if (command?.command.name === "swarm") {
      // A swarm spends model turns, so it asks first: the dialog takes it from here.
      setSwarmTask(argValue(command, "what"));
      cleared();
      return;
    }
    setSending(true);
    setError(null);
    setNotice(null);
    try {
      switch (command?.command.name) {
        case "task":
          await fileCapture(
            roomName,
            parseCapture(argValue(command, "what"), handle, new Date().toISOString()),
            handle,
          );
          break;
        case "agent": {
          const started = await startAgent(command, handle);
          if (!started) return;
          setLaunch(started);
          break;
        }
        case "memory": {
          // Replacing one is on purpose (the list said so), and only the version seen.
          const existing = memories.find((m) => m.key === memoryAt);
          await createMemories(roomName, [
            {
              key: memoryAt,
              value: memoryText,
              content_text: memoryText,
              created_by: handle,
              ...(existing && { base_version: existing.version }),
            },
          ]);
          revalidateRoom();
          setNotice(existing ? `Updated ${memoryAt}.` : `Saved ${memoryAt}.`);
          setNoticeKey(memoryAt);
          break;
        }
        case "engine": {
          const kind = argValue(command, "kind").toLowerCase();
          if (!ENGINE_KINDS.some((e) => e.kind === kind)) {
            setError(`There's no ${kind} engine. It can be ${ENGINE_KINDS.map((e) => e.kind).join(", ")}.`);
            return;
          }
          const name = normHandle(argValue(command, "handle") || kind);
          if (!handleValid(name)) {
            setError(`@${name} can't be a handle: use lowercase letters, digits, - and _.`);
            return;
          }
          await createEngine(roomName, { handle: name, kind: kind as EngineKind, description: "", created_by: handle });
          revalidateRoom();
          setNotice(`Added @${name}. Mention it to put it to work.`);
          setNoticeKey(null);
          break;
        }
        default:
          await sendRoomMessage(roomName, { sender_handle: handle, content: body, episode });
      }
      cleared();
      onSent?.();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setSending(false);
      // The textarea is disabled while sending; it re-enables on the next
      // render, so refocus after that commit lands to keep the user typing.
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [content, episode, onSent, roomName, principal, sending, startAgent, revalidateRoom, memories]);

  // Where this lands is the one thing the composer must never be coy about: the
  // same box writes to the room and into a thread, and the difference is whether
  // an argument stays inside a task or becomes everyone's.
  // The sigils live in the hint row below rather than in here: a placeholder is
  // gone the moment anybody types, and on a narrow box it wrapped the field to
  // two lines to say something the reader had already stopped reading.
  const placeholder = episode ? `Reply in ${threadLabel || "this thread"}…` : "Message the room…";

  // The button renders without chrome at rest; it colors up and grows a
  // hover surface once there is something to send.
  const armed = content.trim().length > 0 && !sending;

  const handleKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (trigger !== null && candidates.length > 0) {
      if (e.key === "ArrowDown") {
        e.preventDefault();
        setHighlight((h) => (h + 1) % candidates.length);
        return;
      }
      if (e.key === "ArrowUp") {
        e.preventDefault();
        setHighlight((h) => (h <= 0 ? candidates.length - 1 : h - 1));
        return;
      }
      // Enter picks the lit row; with none lit (an optional argument offering
      // itself) it sends. Tab always completes, to the first row if none is lit.
      if (e.key === "Tab" || (e.key === "Enter" && highlight >= 0)) {
        e.preventDefault();
        accept(candidates[Math.max(0, highlight)]);
        return;
      }
      if (e.key === "Escape") {
        e.preventDefault();
        setTrigger(null);
        return;
      }
    }
    if (e.key === "Enter" && !e.shiftKey) {
      e.preventDefault();
      submit();
    }
  };

  const showCandidates = trigger !== null && candidates.length > 0;
  const status = error ? (
    <StatusLine tone="error" onDismiss={() => setError(null)}>
      {error}
    </StatusLine>
  ) : launch ? (
    <LaunchStatus launch={launch} roomName={roomName} onDismiss={dismissLaunch} />
  ) : notice ? (
    <StatusLine onDismiss={() => setNotice(null)}>
      {notice}
      {noticeKey && onOpenMemory && (
        <>
          {" "}
          <button
            type="button"
            onMouseDown={(e) => e.preventDefault()}
            onClick={() => {
              onOpenMemory(noticeKey);
              setNotice(null);
            }}
            className="text-accent hover:underline"
          >
            Open it
          </button>
        </>
      )}
    </StatusLine>
  ) : null;

  return (
    <div data-tour="composer" className={`@container border-t border-border bg-bg px-4 py-3 flex-shrink-0${className ? ` ${className}` : ""}`}>
      <div className="relative">
        {/* Over the box, nearest it last: what the word being typed can be,
            the command's signature with that argument lit, then what the
            last command said. None of it moves the box. */}
        {(showCandidates || parsed || summon || status) && (
        <div className="absolute bottom-full left-0 z-20 mb-2 flex w-full max-w-md flex-col gap-1.5">
        {showCandidates && (
          <CandidateList candidates={candidates} highlight={highlight} onPick={accept} onHover={setHighlight} />
        )}
        {parsed && <CommandSignature parsed={parsed} completes={showCandidates} />}
        {summon && <SummonSignature summon={summon} completes={showCandidates} inTask={Boolean(episode)} />}
        {status}
        </div>
        )}

        {/* The text gets the box's full width, and what acts on it sits on a
            quiet row underneath, as a chat composer draws it rather than a
            form field: nothing beside the text, so a wrapped line starts
            where the first one did. */}
        <div className="group/composer rounded-xl border border-border bg-surface transition-colors focus-within:border-border2 focus-within:bg-bg">
          <TextareaAutosize
            ref={inputRef}
            value={content}
            onChange={handleChange}
            onKeyDown={handleKeyDown}
            onSelect={(e) => setCursor(e.currentTarget.selectionStart ?? 0)}
            placeholder={placeholder}
            minRows={1}
            maxRows={10}
            // Scrolls only once it's grown to its cap. Below that, WebKit (the
            // Mac app) can measure the box a fraction short of its text and
            // draws a scrollbar for nothing.
            onHeightChange={() => {
              const el = inputRef.current;
              if (el) setScrolls(el.scrollHeight > el.clientHeight + 1);
            }}
            style={{ overflowY: scrolls ? "auto" : "hidden" }}
            className="block w-full resize-none bg-transparent px-3 pb-1 pt-2.5 text-body font-[430] text-text leading-relaxed focus:outline-none placeholder:text-faint"
            disabled={sending}
          />
          <div className="flex items-center gap-2 px-1.5 pb-1.5">
            {/* In the room's own composer: add what a room holds, a task or
                flow, a memory or a member, without knowing which verb does it. */}
            {!episode && (
              <Popover open={adding} onOpenChange={setAdding}>
                <PopoverTrigger
                  aria-label="Add to the room"
                  title="Add to the room"
                  className="flex size-8 shrink-0 items-center justify-center rounded-md text-muted-foreground transition-colors hover:bg-accent-soft hover:text-accent data-[popup-open]:bg-accent-soft data-[popup-open]:text-accent"
                >
                  <Plus className="size-4" />
                </PopoverTrigger>
                <PopoverContent side="top" align="start" className="w-64 p-1">
                  {ADD_ITEMS.map((item) => (
                    <button
                      key={item.label}
                      type="button"
                      onClick={() => {
                        setAdding(false);
                        if (item.kind === "task") setStarting(true);
                        else if (item.kind === "memory") {
                          setMemoryFolder("context");
                          setMemoryTitle("");
                        }
                        else setAddingMember(true);
                      }}
                      className="flex w-full items-start gap-2.5 rounded-md px-2 py-1.5 text-left transition-colors hover:bg-hairline"
                    >
                      <item.icon className="mt-0.5 size-3.5 shrink-0 text-muted-foreground" />
                      <span className="min-w-0">
                        <span className="block text-label text-text">{item.label}</span>
                        <span className="block text-micro text-faint">{item.about}</span>
                      </span>
                    </button>
                  ))}
                </PopoverContent>
              </Popover>
            )}
            {/* What the composer answers to, said only while you're in it. The
                sigils are typed, so they hold at every width; the keycaps name
                keys a phone does not have, so they appear only when the box
                is wide enough (measured against the composer, not the window:
                it is this narrow on a phone and in a room with both rails open). */}
            <span className="min-w-0 truncate text-micro text-faint opacity-0 transition-opacity group-focus-within/composer:opacity-100">
              @ mention · @~ silent · [[ memory · / command
            </span>
            <div className="ml-auto flex shrink-0 items-center gap-2">
            <span className="hidden items-center gap-1.5 text-micro text-faint opacity-0 transition-opacity group-focus-within/composer:opacity-100 @[34rem]:flex">
              <Kbd size="xs" tone="muted">⇧↵</Kbd> newline
              <KbdChord size="xs" tone="muted" action="palette.open" /> commands
            </span>
            <button
              type="button"
              onClick={submit}
              disabled={!armed}
              aria-label="Send message"
              className={`group grid size-8 place-items-center rounded-md transition-colors ${
                armed ? "text-accent hover:bg-accent-soft" : "cursor-not-allowed text-faint"
              }`}
            >
              <SendPlaneIcon
                className={`size-[17px] transition-[transform,opacity] duration-200 ease-out ${
                  sending ? "translate-x-1.5 -translate-y-1.5 opacity-0" : ""
                } ${armed ? "group-hover:-translate-y-px group-hover:translate-x-px group-active:scale-90" : ""}`}
              />
            </button>
            </div>
          </div>
        </div>
      </div>
      {starting && <IntentDialog roomName={roomName} initial="task" onClose={() => setStarting(false)} />}
      <NewMemoryDialog
        open={memoryTitle !== null}
        onOpenChange={(open) => !open && setMemoryTitle(null)}
        roomName={roomName}
        initialTitle={memoryTitle ?? ""}
        initialFolder={memoryFolder}
        onCreated={onOpenMemory}
      />
      {addingMember && <AddMemberDialog open onOpenChange={setAddingMember} roomName={roomName} />}

      {swarmTask !== null && (
        <StartSwarmDialog
          open
          onClose={() => setSwarmTask(null)}
          roomName={roomName}
          initialTask={swarmTask}
        />
      )}
    </div>
  );
}

/** One part of a signature: how it's drawn, and whether something fills it yet. */
/** `/agent <handle> <harness> [folder] [machine]`, with the argument being typed lit and said. */
function CommandSignature({ parsed, completes }: { parsed: ParsedCommand; completes: boolean }) {
  const { command, active, args } = parsed;
  const arg = active !== null ? command.args[active] : null;
  const slots = command.args.map((a, i) => {
    const name = a.rest ? `${a.name}…` : a.name;
    return { label: a.optional ? `[${name}]` : `<${name}>`, filled: Boolean(args[i]?.value) };
  });
  return (
    <Signature
      label={`/${command.name} usage`}
      head={`/${command.name}`}
      slots={slots}
      active={active}
      about={arg ? arg.about : command.about}
      completes={completes}
    />
  );
}

/**
 * `@conductor gated @proposer @guardian <what…>`: once a flow is named, its
 * own roles are the member slots, lit one at a time as each is filled, so the
 * order they bind in is on screen rather than in a doc.
 */
function SummonSignature({
  summon,
  completes,
  inTask,
}: {
  summon: ParsedSummon;
  completes: boolean;
  inTask: boolean;
}) {
  const { protocol, members, active, slot } = summon;
  const roles = protocol?.roles ?? [];
  const memberSlots: Slot[] = roles.length
    ? roles.map((r, i) => ({ label: `@${r}`, filled: i < members.length }))
    : [{ label: protocol ? "[@member…]" : "@member…", filled: members.length > 0 }];
  const slots: Slot[] = [
    { label: summon.flow?.value.replace(/[:,;]+$/, "") || "<flow>", filled: Boolean(protocol) },
    ...memberSlots,
    { label: "<what…>", filled: summon.asked },
  ];
  const at =
    active === "flow" ? 0 : active === "member" ? 1 + Math.min(slot, memberSlots.length - 1) : active === "ask" ? slots.length - 1 : null;

  let about: string;
  if (active === "flow") {
    about = protocol?.description ?? "Which flow to run.";
  } else if (active === "member") {
    const role = roles[slot];
    about = role
      ? `Who plays ${role}. Type @ to pick them${roles.length > 1 ? `; members take the roles in order` : ""}.`
      : roles.length
        ? "Every role has someone. Say what it's about next."
        : "Who takes part. Name nobody and everyone in the room does.";
  } else if (active === "ask") {
    about = "What it's about. Every step's prompt carries it.";
  } else {
    about = "Runs a flow in this task, giving each member the floor in turn.";
  }
  const unknown = summon.flow && !protocol && active !== "flow" ? `There's no ${summon.flow.value} flow in this room.` : null;
  const warning = unknown ?? (inTask ? null : "A flow runs inside a task. Open one and summon it there; here the conductor can only list flows.");

  return (
    <Signature
      label={`@${summon.engine} usage`}
      head={`@${summon.engine}`}
      slots={slots}
      active={at}
      about={about}
      completes={completes}
      warning={warning}
    />
  );
}

function StatusLine({
  children,
  tone = "info",
  onDismiss,
}: {
  children: React.ReactNode;
  tone?: "info" | "error";
  onDismiss: () => void;
}) {
  return (
    <div
      role={tone === "error" ? "alert" : "status"}
      className={cn(
        "flex items-start gap-2 rounded-lg border bg-elevated px-2.5 py-1.5 text-micro shadow-lg",
        tone === "error" ? "border-red/40 text-red" : "border-border text-muted-foreground",
      )}
    >
      <span className="min-w-0 flex-1 break-words">{children}</span>
      <button
        type="button"
        aria-label="Dismiss"
        onMouseDown={(e) => e.preventDefault()}
        onClick={onDismiss}
        className="shrink-0 rounded text-muted-foreground hover:text-text"
      >
        <X className="size-3.5" />
      </button>
    </div>
  );
}

/** An `/agent` start, followed on its machine until the agent is in the room. */
function LaunchStatus({ launch, roomName, onDismiss }: { launch: Launch; roomName: string; onDismiss: () => void }) {
  const { job } = useRunnerJob(launch.runner, launch.job);
  const revalidate = useRoomRevalidate(roomName);
  const status = job?.status ?? "queued";
  useEffect(() => {
    if (status !== "done") return;
    revalidate();
    const t = setTimeout(onDismiss, 6000);
    return () => clearTimeout(t);
  }, [status, revalidate, onDismiss]);
  if (status === "failed") {
    return (
      <StatusLine tone="error" onDismiss={onDismiss}>
        @{launch.handle} didn&apos;t start: {job?.error ?? "the machine said no more"}
      </StatusLine>
    );
  }
  return (
    <StatusLine onDismiss={onDismiss}>
      {status === "done" ? `@${launch.handle} is starting. It joins once it has read its notes.` : `@${launch.handle}: ${JOB_STATUS_LABEL[status]}`}
    </StatusLine>
  );
}
