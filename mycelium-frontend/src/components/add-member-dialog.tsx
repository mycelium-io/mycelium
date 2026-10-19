// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useState, useSyncExternalStore } from "react";
import { Cpu, Globe, Laptop, Play, SquareTerminal, type LucideIcon } from "lucide-react";
import {
  createEngine,
  createInvite,
  createMemories,
  registerA2aAgent,
  type EngineKind,
  type JoinCode,
} from "@/lib/api";
import { agentHandoffPrompt } from "@/lib/install";
import { useRoomRevalidate } from "@/lib/room-data";
import { useCurrentUser } from "@/components/current-user";
import { Button } from "@/components/ui/button";
import { CopyAction } from "@/components/ui/copy-field";
import { Dialog, DialogContent, DialogDescription, DialogTitle } from "@/components/ui/dialog";
import {
  IdentityRow,
  InstructionsEditor,
  LaunchAgentForm,
  MemberFooter,
  handleValid,
  normHandle,
} from "@/components/launch-agent-dialog";
import { RunningAgentMember } from "@/components/running-agent-member";
import { cn } from "@/lib/utils";

/** The ways a member can join a room, in the order the dialog offers them. */
export type MemberKind = "machine" | "running" | "engine" | "a2a" | "session";

const KINDS: { kind: MemberKind; icon: LucideIcon; label: string; hint: string; about: string }[] = [
  {
    kind: "machine",
    icon: Laptop,
    label: "Your machine",
    hint: "Start a new one",
    about:
      "A coding agent on your machine that joins this room as a member, working the way you describe here.",
  },
  {
    kind: "running",
    icon: Play,
    label: "Running agent",
    hint: "Already running",
    about:
      "An agent already running on your machine that isn't in a room yet. It keeps its session and joins this room as a member.",
  },
  {
    kind: "engine",
    icon: Cpu,
    label: "Engine",
    hint: "Runs on this hub",
    about: "A capability the hub runs for this room. Nothing to install; summon it with its @handle.",
  },
  {
    kind: "a2a",
    icon: Globe,
    label: "A2A service",
    hint: "Runs elsewhere",
    about:
      "An Agent2Agent service somewhere else. The hub calls it when someone mentions it here and posts its answer.",
  },
  {
    kind: "session",
    icon: SquareTerminal,
    label: "Open session",
    hint: "Paste a prompt",
    about:
      "An agent session you already have open, on this machine or another. It joins as the member you name here, with a code in the prompt you paste into it.",
  },
];

/** The engines the hub runs, and what each does, in a sentence. */
export const ENGINE_KINDS: { kind: EngineKind; blurb: string }[] = [
  { kind: "aligner", blurb: "Mediates a negotiation until the members agree." },
  { kind: "synthesizer", blurb: "Distills the room's conversation into memory." },
  { kind: "persona", blurb: "Plays a member in character, from its notes, and remembers." },
  { kind: "worker", blurb: "Takes work off the board in its own checkout, asks for review, resolves it." },
  { kind: "conductor", blurb: "Runs a protocol inside a task, giving the floor one step at a time." },
  {
    kind: "verifier",
    blurb: "Checks what agents say about approvals and merges against this room's records, and notes what it can't find.",
  },
  { kind: "hello", blurb: "Answers once and writes nothing. Proves the path works." },
];

/** Engines whose notes are who they are, so the dialog asks for them. */
const NOTED: Partial<Record<EngineKind, string>> = {
  persona:
    "Who is this member?\n\nHow they talk, what they care about, what they push back on. " +
    "It plays this in character every time it answers.",
  worker:
    "What should this worker own, and how should it work?\n\nIt works in its own checkout " +
    "on the hub, asks a teammate to review, and resolves what it finishes.",
};

interface Props {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  roomName: string;
  /** Which kind to open on; the machine when not said. */
  initialKind?: MemberKind;
  /** Called with the new member's handle once it is in the room. */
  onAdded?: (handle: string) => void;
}

/**
 * Add a member to a room, whatever kind it is.
 *
 * Every kind reads the same way: who it is (its avatar and `@handle`), what
 * it does (a role and instructions, an engine, a service's card), and, along
 * the bottom, where it runs beside the one button that adds it.
 */
export function AddMemberDialog({ open, onOpenChange, roomName, initialKind = "machine", onAdded }: Props) {
  const [kind, setKind] = useState<MemberKind>(initialKind);
  const [shownFor, setShownFor] = useState(initialKind);
  // A new ask for a kind (the palette's "invite an engine") wins over the last pick.
  if (shownFor !== initialKind) {
    setShownFor(initialKind);
    setKind(initialKind);
  }
  const about = KINDS.find((k) => k.kind === kind)?.about;
  const close = () => onOpenChange(false);
  const added = (handle: string) => onAdded?.(handle);

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="grid-cols-1 gap-0 overflow-hidden p-0 sm:max-w-2xl [&>*]:min-w-0">
        <div className="border-b border-border px-5 pt-4 pb-3">
          <DialogTitle className="text-ui font-semibold text-text">
            Add a member to <span className="font-mono">{roomName}</span>
          </DialogTitle>
          <DialogDescription className="mt-1 text-label text-muted-foreground">{about}</DialogDescription>
          <KindPicker value={kind} onChange={setKind} />
        </div>
        {open && kind === "machine" && (
          <LaunchAgentForm roomName={roomName} onLaunched={added} onClose={close} />
        )}
        {open && kind === "running" && (
          <RunningAgentMember roomName={roomName} onAdded={added} onClose={close} />
        )}
        {open && kind === "engine" && (
          <EngineMember roomName={roomName} onAdded={(h) => (added(h), close())} />
        )}
        {open && kind === "a2a" && (
          <A2aMember roomName={roomName} onAdded={(h) => (added(h), close())} />
        )}
        {open && kind === "session" && <SessionMember roomName={roomName} onDone={close} />}
      </DialogContent>
    </Dialog>
  );
}

function KindPicker({ value, onChange }: { value: MemberKind; onChange: (k: MemberKind) => void }) {
  return (
    <div role="tablist" aria-label="Kind of member" className="mt-4 grid grid-cols-2 gap-1.5 sm:grid-cols-5">
      {KINDS.map(({ kind, icon: Icon, label, hint }) => {
        const active = kind === value;
        return (
          <button
            key={kind}
            type="button"
            role="tab"
            aria-selected={active}
            onClick={() => onChange(kind)}
            className={cn(
              "flex min-w-0 flex-col items-start gap-1 rounded-lg border px-3 py-2 text-left transition-colors",
              active
                ? "border-accent bg-accent/10"
                : "border-border hover:border-border2 hover:bg-hairline",
            )}
          >
            <Icon className={cn("size-4 flex-shrink-0", active ? "text-accent" : "text-muted-foreground")} />
            <span className="w-full min-w-0">
              <span
                className={cn("block truncate text-label font-medium", active ? "text-text" : "text-muted-foreground")}
              >
                {label}
              </span>
              {/* The chosen card's tint lifts its ground, so its hint steps up a level to stay legible. */}
              <span className={cn("block truncate text-micro", active ? "text-muted-foreground" : "text-faint")}>
                {hint}
              </span>
            </span>
          </button>
        );
      })}
    </div>
  );
}

function ErrorLine({ error }: { error: string | null }) {
  if (!error) return null;
  return (
    <p role="alert" className="break-words text-label text-red">
      {error}
    </p>
  );
}

function EngineMember({ roomName, onAdded }: { roomName: string; onAdded: (handle: string) => void }) {
  const { principal } = useCurrentUser();
  const revalidate = useRoomRevalidate(roomName);
  const [engine, setEngine] = useState<EngineKind>("aligner");
  const [handle, setHandle] = useState("aligner");
  const [touched, setTouched] = useState(false);
  const [notes, setNotes] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmed = normHandle(handle);
  const noted = NOTED[engine];
  const canSubmit = handleValid(handle) && !submitting;
  const blurb = ENGINE_KINDS.find((e) => e.kind === engine)?.blurb;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    const me = principal.trim() || "web-ui";
    try {
      await createEngine(roomName, { handle: trimmed, kind: engine, description: "", created_by: me });
      if (noted && notes.trim()) {
        await createMemories(roomName, [
          { key: `agents/${trimmed}/notes`, value: notes.trim(), created_by: me },
        ]);
      }
      revalidate();
      onAdded(trimmed);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not add the engine");
    } finally {
      setSubmitting(false);
    }
  };

  return (
    <>
      <div className="space-y-4 px-5 py-4">
        <div>
          <p id="engine-kind-label" className="mb-2 text-micro font-medium text-muted-foreground">
            What it does
          </p>
          <div role="radiogroup" aria-labelledby="engine-kind-label" className="flex flex-wrap gap-1.5">
            {ENGINE_KINDS.map(({ kind }) => (
              <button
                key={kind}
                type="button"
                role="radio"
                aria-checked={engine === kind}
                onClick={() => {
                  setEngine(kind);
                  if (!touched) setHandle(kind);
                }}
                className={cn(
                  "rounded-full border px-3 py-1 text-label transition-colors",
                  engine === kind
                    ? "border-accent bg-accent/10 text-text"
                    : "border-border text-muted-foreground hover:border-border2 hover:text-text",
                )}
              >
                {kind}
              </button>
            ))}
          </div>
          <p className="mt-2 text-label text-muted-foreground">{blurb}</p>
        </div>

        <IdentityRow
          value={handle}
          onChange={(v) => {
            setHandle(v);
            setTouched(true);
            setError(null);
          }}
          hint={`Summon it in a message with @${trimmed || engine}.`}
        />

        {noted && (
          <InstructionsEditor
            handle={trimmed}
            value={notes}
            onChange={setNotes}
            draft={engine === "persona" || engine === "worker" ? { room: roomName, kind: engine } : undefined}
            placeholder={noted}
            rows={6}
          />
        )}
        <ErrorLine error={error} />
      </div>
      <MemberFooter
        action={
          <Button onClick={submit} disabled={!canSubmit}>
            {/* A fixed label: the handle is in the field above, and a button that
                grows with each keystroke moves under the pointer. */}
            {submitting ? "Adding…" : "Add to room"}
          </Button>
        }
      >
        <Cpu className="size-4 flex-shrink-0" aria-hidden />
        <span className="truncate">Runs on this hub. Nothing to install.</span>
      </MemberFooter>
    </>
  );
}

function A2aMember({ roomName, onAdded }: { roomName: string; onAdded: (handle: string) => void }) {
  const revalidate = useRoomRevalidate(roomName);
  const [handle, setHandle] = useState("");
  const [card, setCard] = useState("");
  const [description, setDescription] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmed = normHandle(handle);
  const canSubmit = handleValid(handle) && card.trim().length > 0 && !submitting;

  const submit = async () => {
    if (!canSubmit) return;
    setSubmitting(true);
    setError(null);
    try {
      await registerA2aAgent(roomName, {
        handle: trimmed,
        card: card.trim(),
        description: description.trim(),
      });
      revalidate();
      onAdded(trimmed);
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not connect the service");
    } finally {
      setSubmitting(false);
    }
  };

  const field =
    "w-full rounded-lg border border-border bg-bg px-3 py-2 text-label text-text outline-none transition-colors placeholder:text-faint hover:border-border2 focus:border-accent";

  return (
    <>
      <div className="space-y-4 px-5 py-4">
        <IdentityRow
          value={handle}
          onChange={(v) => {
            setHandle(v);
            setError(null);
          }}
          hint="How the room mentions it. The hub calls the service each time."
        />
        <div className="space-y-1.5">
          <label htmlFor="a2a-card" className="block text-micro font-medium text-muted-foreground">
            Agent card URL
          </label>
          <input
            id="a2a-card"
            value={card}
            onChange={(e) => {
              setCard(e.target.value);
              setError(null);
            }}
            onKeyDown={(e) => e.key === "Enter" && submit()}
            placeholder="https://agent.example.com"
            spellCheck={false}
            autoCapitalize="none"
            className={cn(field, "font-mono")}
          />
          <p className="text-micro text-faint">
            The hub reads the card to find the service&apos;s endpoint and the skills it offers.
          </p>
        </div>
        <div className="space-y-1.5">
          <label htmlFor="a2a-description" className="block text-micro font-medium text-muted-foreground">
            What it does in this room <span className="font-normal text-faint">optional</span>
          </label>
          <input
            id="a2a-description"
            value={description}
            onChange={(e) => setDescription(e.target.value)}
            placeholder="Looks up customer accounts"
            className={field}
          />
        </div>
        <ErrorLine error={error} />
      </div>
      <MemberFooter
        action={
          <Button onClick={submit} disabled={!canSubmit}>
            {submitting ? "Connecting…" : `Connect ${trimmed && handleValid(handle) ? `@${trimmed}` : "service"}`}
          </Button>
        }
      >
        <Globe className="size-4 flex-shrink-0" aria-hidden />
        <span className="truncate">Runs elsewhere. The hub relays for it and sees what it says.</span>
      </MemberFooter>
    </>
  );
}

/** How long a session's join code can wait to be used, shortest first. The
 *  first is the default: a code's lifetime is part of what keeps it safe. */
export const CODE_LIFETIMES: { minutes: number; label: string }[] = [
  { minutes: 10, label: "10 minutes" },
  { minutes: 60, label: "1 hour" },
  { minutes: 24 * 60, label: "1 day" },
];

/** Whether `url` names this machine only (localhost, 127.x, ::1), so a
 *  session on another machine couldn't reach it. */
export function isLocalAddress(url: string): boolean {
  try {
    const host = new URL(url).hostname.replace(/^\[|\]$/g, "");
    return host === "localhost" || host === "::1" || host.startsWith("127.");
  } catch {
    return false;
  }
}

function SessionMember({ roomName, onDone }: { roomName: string; onDone: () => void }) {
  const { principal } = useCurrentUser();
  const revalidate = useRoomRevalidate(roomName);
  const hubUrl = useSyncExternalStore(
    () => () => {},
    () => window.location.origin,
    () => "<this-hub-url>",
  );
  const [handle, setHandle] = useState("");
  const [minutes, setMinutes] = useState(CODE_LIFETIMES[0].minutes);
  const [invite, setInvite] = useState<JoinCode | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const trimmed = normHandle(handle);

  // Enabled with nothing typed, and saying what's missing when pressed: a
  // dimmed button over a dimmed page reads as pressable anyway.
  const submit = async () => {
    if (submitting) return;
    if (!handleValid(handle)) {
      setError(
        trimmed
          ? "A handle is lowercase letters, digits, - and _, starting with a letter or digit."
          : "Give the agent a handle first.",
      );
      return;
    }
    setSubmitting(true);
    setError(null);
    try {
      setInvite(
        await createInvite(roomName, {
          handle: trimmed,
          ttl_minutes: minutes,
          created_by: principal.trim() || undefined,
        }),
      );
      revalidate();
    } catch (e) {
      setError(e instanceof Error ? e.message : "Could not make a join code");
    } finally {
      setSubmitting(false);
    }
  };

  if (invite) {
    // With its zone: the session reading it is often on a machine in another.
    const until = new Date(invite.expires_at).toLocaleString(undefined, {
      weekday: minutes > 60 ? "short" : undefined,
      hour: "numeric",
      minute: "2-digit",
      timeZoneName: "short",
    });
    const prompt = agentHandoffPrompt({ hubUrl, roomName, handle: invite.handle, code: invite.code, until });
    return (
      <>
        <div className="space-y-3 px-5 py-4">
          {/* Whole, never scrolled: its last line, keeping `await` running, is
              the point of it. */}
          <div className="rounded-lg border border-border bg-bg">
            <pre className="whitespace-pre-wrap px-4 py-3 font-mono text-micro leading-relaxed text-muted-foreground">
              {prompt}
            </pre>
          </div>
          <p className="text-micro text-faint">
            Paste it into the session. @{invite.handle} shows up in Members once it has joined.
            {isLocalAddress(hubUrl) && " This hub's address only works for a session on this machine."}
          </p>
        </div>
        <MemberFooter
          action={
            <div className="flex gap-2">
              <CopyAction value={prompt} label="Copy prompt" />
              <Button onClick={onDone}>Done</Button>
            </div>
          }
        >
          <SquareTerminal className="size-4 flex-shrink-0" aria-hidden />
          <span className="truncate">Runs wherever that session is.</span>
        </MemberFooter>
      </>
    );
  }

  return (
    <>
      <div className="space-y-4 px-5 py-4">
        <IdentityRow
          value={handle}
          onChange={(v) => {
            setHandle(v);
            setError(null);
          }}
          hint="The member the session joins as. It gets a join code for it."
        />
        <div>
          <p id="code-lifetime-label" className="mb-2 text-micro font-medium text-muted-foreground">
            The code works for
          </p>
          <div role="radiogroup" aria-labelledby="code-lifetime-label" className="flex flex-wrap gap-1.5">
            {CODE_LIFETIMES.map((option) => (
              <button
                key={option.minutes}
                type="button"
                role="radio"
                aria-checked={minutes === option.minutes}
                onClick={() => setMinutes(option.minutes)}
                className={cn(
                  "rounded-full border px-3 py-1 text-label transition-colors",
                  minutes === option.minutes
                    ? "border-accent bg-accent/10 text-text"
                    : "border-border text-muted-foreground hover:border-border2 hover:text-text",
                )}
              >
                {option.label}
              </button>
            ))}
          </div>
          <p className="mt-2 text-label text-muted-foreground">
            The code works once. Keep it short unless the session will start later.
          </p>
        </div>
        <ErrorLine error={error} />
      </div>
      <MemberFooter
        action={
          <Button onClick={submit} disabled={submitting}>
            {submitting ? "Making the prompt…" : "Make the prompt"}
          </Button>
        }
      >
        <SquareTerminal className="size-4 flex-shrink-0" aria-hidden />
        <span className="truncate">Runs wherever that session is.</span>
      </MemberFooter>
    </>
  );
}
