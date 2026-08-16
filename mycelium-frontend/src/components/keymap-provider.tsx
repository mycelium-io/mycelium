// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import {
  createContext,
  useCallback,
  useContext,
  useEffect,
  useMemo,
  useRef,
  useState,
  type ReactNode,
} from "react";
import { KeymapCheatsheet } from "@/components/keymap-cheatsheet";
import {
  eventToChord,
  isMacPlatform,
  isModifierKey,
  isSequencePrefix,
  matchBinding,
  type KeyScope,
} from "@/lib/keymap";

/** How long a half-typed sequence ("g" waiting for its second chord) stays
 *  pending before it lapses back to command mode. */
const SEQUENCE_TIMEOUT_MS = 1500;

type Handler = (sequence: string) => void;

interface KeymapApi {
  /** Handle an action from the keymap while mounted. */
  register: (id: string, handler: Handler) => () => void;
  /** Mark a scope live (its bindings fire and list in the cheatsheet). */
  pushScope: (scope: KeyScope) => () => void;
  /** Take the keyboard over wholesale (hint mode); the returned fn releases. */
  captureKeys: (handler: (e: KeyboardEvent) => void) => () => void;
  openHelp: () => void;
}

const KeymapContext = createContext<KeymapApi | null>(null);

function isEditable(el: Element | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

/** Keys stay out of the way of a modal: whatever is behind it isn't what the
 *  user is looking at, and the dialog owns its own Escape. */
function inModal(el: Element | null): boolean {
  if (typeof document !== "undefined" && document.querySelector('[aria-modal="true"]')) return true;
  return Boolean(el?.closest?.('[role="dialog"], [role="alertdialog"]'));
}

/** Hosts the app's keybinds: one document-level listener that resolves key
 *  events against the central keymap and dispatches to whoever registered the
 *  action. Typing is typing — while a text input holds focus nothing fires but
 *  Escape, which blurs back to command mode. */
export function KeymapProvider({ children }: { children: ReactNode }) {
  const handlers = useRef(new Map<string, Handler[]>());
  const capture = useRef<((e: KeyboardEvent) => void) | null>(null);
  const sequence = useRef<string[]>([]);
  const lapse = useRef<ReturnType<typeof setTimeout> | undefined>(undefined);
  const [pending, setPending] = useState<string[]>([]);
  const [scopeCounts, setScopeCounts] = useState<Partial<Record<KeyScope, number>>>({ global: 1 });
  const [helpOpen, setHelpOpen] = useState(false);
  // Resolved after mount: the server has no platform to read, and a guess would
  // hydrate a ⌘ over a Ctrl.
  const [mac, setMac] = useState(false);
  useEffect(() => setMac(isMacPlatform()), []);

  const scopes = useMemo(
    () => (Object.entries(scopeCounts) as [KeyScope, number][]).filter(([, n]) => n > 0).map(([s]) => s),
    [scopeCounts],
  );

  // The listener is installed once, so it reads live scopes/platform off refs
  // rather than resubscribing on every scope change.
  const scopesRef = useRef(scopes);
  const macRef = useRef(mac);
  useEffect(() => {
    scopesRef.current = scopes;
    macRef.current = mac;
  }, [scopes, mac]);

  const register = useCallback<KeymapApi["register"]>((id, handler) => {
    const list = handlers.current.get(id) ?? [];
    list.push(handler);
    handlers.current.set(id, list);
    return () => {
      const current = handlers.current.get(id);
      if (!current) return;
      const i = current.indexOf(handler);
      if (i >= 0) current.splice(i, 1);
      if (current.length === 0) handlers.current.delete(id);
    };
  }, []);

  const pushScope = useCallback<KeymapApi["pushScope"]>((scope) => {
    setScopeCounts((c) => ({ ...c, [scope]: (c[scope] ?? 0) + 1 }));
    return () => setScopeCounts((c) => ({ ...c, [scope]: Math.max(0, (c[scope] ?? 1) - 1) }));
  }, []);

  const captureKeys = useCallback<KeymapApi["captureKeys"]>((handler) => {
    capture.current = handler;
    return () => {
      if (capture.current === handler) capture.current = null;
    };
  }, []);

  const openHelp = useCallback(() => setHelpOpen(true), []);

  useEffect(() => {
    const reset = () => {
      sequence.current = [];
      setPending([]);
      clearTimeout(lapse.current);
    };

    const onKeyDown = (e: KeyboardEvent) => {
      // A component that already acted on the key owns it (the chat box's
      // Escape dismissing its mention popover, say) — the first Escape closes
      // the popover, a second one blurs.
      if (e.defaultPrevented || e.isComposing || isModifierKey(e.key)) return;

      const held = capture.current;
      if (held) {
        held(e);
        return;
      }

      const target = document.activeElement;
      if (inModal(target)) return;

      const chord = eventToChord(e, macRef.current);
      if (isEditable(target)) {
        if (chord === "Escape") {
          reset();
          (target as HTMLElement).blur();
        }
        return;
      }

      const typed = [...sequence.current, chord].join(" ");
      const binding = matchBinding(typed, scopesRef.current);
      if (binding) {
        reset();
        if (binding.id === "help.keys") {
          e.preventDefault();
          setHelpOpen(true);
          return;
        }
        const list = handlers.current.get(binding.id);
        if (list && list.length > 0) {
          e.preventDefault();
          // Every registrant runs: focusing the composer, for instance, is one
          // action the room page (switch to the channel pane) and the chat box
          // (focus the textarea) each own a half of.
          for (const handler of [...list]) handler(typed);
        }
        return;
      }

      if (isSequencePrefix(typed, scopesRef.current)) {
        e.preventDefault();
        sequence.current = typed.split(" ");
        setPending(sequence.current);
        clearTimeout(lapse.current);
        lapse.current = setTimeout(reset, SEQUENCE_TIMEOUT_MS);
        return;
      }

      reset();
    };

    window.addEventListener("keydown", onKeyDown);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      clearTimeout(lapse.current);
    };
  }, []);

  // Every member is a stable callback, so the context value never changes
  // identity — a scope declaring itself live must not invalidate the very
  // effect that declared it.
  const api = useMemo<KeymapApi>(
    () => ({ register, pushScope, captureKeys, openHelp }),
    [register, pushScope, captureKeys, openHelp],
  );

  return (
    <KeymapContext.Provider value={api}>
      {children}
      {pending.length > 0 && (
        <div
          role="status"
          aria-live="polite"
          className="pointer-events-none fixed bottom-9 right-4 z-50 rounded-md border border-border bg-elevated px-2 py-1 font-mono text-micro text-muted-foreground shadow-lg"
        >
          {pending.join(" ")}…
        </div>
      )}
      <KeymapCheatsheet open={helpOpen} onClose={() => setHelpOpen(false)} scopes={scopes} mac={mac} />
    </KeymapContext.Provider>
  );
}

/** Run `handler` when the keymap fires `id`. Latest render's closure wins, so
 *  the handler can close over state without re-registering. */
export function useKeyAction(id: string, handler: Handler, enabled = true): void {
  const api = useContext(KeymapContext);
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  useEffect(() => {
    if (!api || !enabled) return;
    return api.register(id, (sequence) => latest.current(sequence));
  }, [api, id, enabled]);
}

/** Declare a scope live for as long as the component is mounted. */
export function useKeyScope(scope: KeyScope): void {
  const api = useContext(KeymapContext);
  useEffect(() => api?.pushScope(scope), [api, scope]);
}

const NO_CAPTURE = () => () => {};

/** Claim every keystroke until released — how the room hint overlay reads its
 *  labels without every hint char needing a binding of its own. */
export function useKeyCapture(): KeymapApi["captureKeys"] {
  return useContext(KeymapContext)?.captureKeys ?? NO_CAPTURE;
}

/** The status-bar affordance that makes `?` findable without knowing `?`. */
export function KeymapHelpButton() {
  const api = useContext(KeymapContext);
  if (!api) return null;
  return (
    <button
      type="button"
      onClick={api.openHelp}
      title="Keyboard shortcuts"
      className="rounded px-1 text-micro text-muted-foreground transition-colors hover:text-text"
    >
      <kbd className="font-sans">?</kbd> keys
    </button>
  );
}
