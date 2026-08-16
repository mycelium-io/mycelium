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
  matchBinding,
  REVEAL_MODIFIER_KEY,
  type KeyScope,
} from "@/lib/keymap";

type Handler = (chord: string) => void;

interface KeymapApi {
  /** Handle an action from the keymap while mounted. */
  register: (id: string, handler: Handler) => () => void;
  /** Mark a scope live (its bindings fire and list in the cheatsheet). */
  pushScope: (scope: KeyScope) => () => void;
  /** Take the keyboard over wholesale (hint mode); the returned fn releases. */
  captureKeys: (handler: (e: KeyboardEvent) => void) => () => void;
  openHelp: () => void;
  subscribeReveal: (listener: (revealed: boolean) => void) => () => void;
  revealed: () => boolean;
}

const KeymapContext = createContext<KeymapApi | null>(null);

function useKeymap(hook: string): KeymapApi {
  const api = useContext(KeymapContext);
  if (!api) throw new Error(`${hook} must be used within a KeymapProvider`);
  return api;
}

function isEditable(el: Element | null): boolean {
  if (!(el instanceof HTMLElement)) return false;
  const tag = el.tagName;
  return tag === "INPUT" || tag === "TEXTAREA" || tag === "SELECT" || el.isContentEditable;
}

/** Keys stay out of the way of an open dialog: what's behind it isn't what the
 *  user is looking at, and the dialog owns its own Escape. Presence is the
 *  test, not focus — a click on the backdrop moves focus out of the dialog
 *  without closing it, and the keys must stay inert through that. Dialogs are
 *  portaled in only while open, so an unmounted one can't block anything. */
function modalIsOpen(): boolean {
  if (typeof document === "undefined") return false;
  return Boolean(document.querySelector('[role="dialog"], [role="alertdialog"], [aria-modal="true"]'));
}

/** Hosts the app's keybinds: one document-level listener that resolves key
 *  events against the central keymap and dispatches to whoever registered the
 *  action. Typing is typing — while a text input holds focus nothing fires but
 *  Escape, which blurs back to command mode.
 *
 *  It must sit above every page, not inside a page's shell, or a page that
 *  registers its own bindings ends up outside the context it registers into. */
export function KeymapProvider({ children }: { children: ReactNode }) {
  const handlers = useRef(new Map<string, Handler[]>());
  const capture = useRef<((e: KeyboardEvent) => void) | null>(null);
  const [scopeCounts, setScopeCounts] = useState<Partial<Record<KeyScope, number>>>({ global: 1 });
  const [helpOpen, setHelpOpen] = useState(false);
  // Resolved after mount: the server has no platform to read, and a guess would
  // hydrate a ⌘ over a Ctrl.
  const [mac, setMac] = useState(false);
  useEffect(() => setMac(isMacPlatform()), []);

  // Reveal is pushed to subscribers rather than held in state: holding ⌥ would
  // otherwise re-render the whole app through the context value.
  const revealRef = useRef(false);
  const revealListeners = useRef(new Set<(revealed: boolean) => void>());
  const setRevealed = useCallback((next: boolean) => {
    if (revealRef.current === next) return;
    revealRef.current = next;
    for (const listener of [...revealListeners.current]) listener(next);
  }, []);

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

  const pushScope = useCallback<KeymapApi["pushScope"]>(scope => {
    setScopeCounts(c => ({ ...c, [scope]: (c[scope] ?? 0) + 1 }));
    return () => setScopeCounts(c => ({ ...c, [scope]: Math.max(0, (c[scope] ?? 1) - 1) }));
  }, []);

  const captureKeys = useCallback<KeymapApi["captureKeys"]>(handler => {
    capture.current = handler;
    return () => {
      if (capture.current === handler) capture.current = null;
    };
  }, []);

  const openHelp = useCallback(() => setHelpOpen(true), []);

  const subscribeReveal = useCallback<KeymapApi["subscribeReveal"]>(listener => {
    revealListeners.current.add(listener);
    return () => {
      revealListeners.current.delete(listener);
    };
  }, []);

  const revealed = useCallback(() => revealRef.current, []);

  useEffect(() => {
    const onKeyDown = (e: KeyboardEvent) => {
      // A component that already acted on the key owns it (the chat box's
      // Escape dismissing its mention popover, say) — the first Escape closes
      // the popover, a second one blurs.
      if (e.defaultPrevented || e.isComposing) return;

      const held = capture.current;
      if (held) {
        held(e);
        return;
      }

      if (modalIsOpen()) return;
      const target = document.activeElement;

      // Holding the reveal modifier over the app draws every navigation key on
      // the thing it selects. Not while typing: there the modifier is composing
      // a character, and the keys are inert anyway.
      if (e.key === REVEAL_MODIFIER_KEY) {
        if (!isEditable(target)) setRevealed(true);
        return;
      }
      if (isModifierKey(e.key)) return;

      const chord = eventToChord(e, macRef.current);
      if (isEditable(target)) {
        if (chord === "Escape") (target as HTMLElement).blur();
        return;
      }

      const binding = matchBinding(chord, scopesRef.current);
      if (!binding) return;
      if (binding.id === "help.keys") {
        e.preventDefault();
        setRevealed(false);
        setHelpOpen(true);
        return;
      }
      const list = handlers.current.get(binding.id);
      if (!list || list.length === 0) return;
      e.preventDefault();
      setRevealed(false);
      // Every registrant runs: focusing the composer, for instance, is one
      // action the room page (switch to the channel pane) and the chat box
      // (focus the textarea) each own a half of.
      for (const handler of [...list]) handler(chord);
    };

    const onKeyUp = (e: KeyboardEvent) => {
      if (e.key === REVEAL_MODIFIER_KEY) setRevealed(false);
    };
    // Tabbing away mid-hold never delivers the keyup, so the badges would stick.
    const onBlur = () => setRevealed(false);

    window.addEventListener("keydown", onKeyDown);
    window.addEventListener("keyup", onKeyUp);
    window.addEventListener("blur", onBlur);
    return () => {
      window.removeEventListener("keydown", onKeyDown);
      window.removeEventListener("keyup", onKeyUp);
      window.removeEventListener("blur", onBlur);
    };
  }, [setRevealed]);

  // Every member is a stable callback, so the context value never changes
  // identity — a scope declaring itself live must not invalidate the very
  // effect that declared it.
  const api = useMemo<KeymapApi>(
    () => ({ register, pushScope, captureKeys, openHelp, subscribeReveal, revealed }),
    [register, pushScope, captureKeys, openHelp, subscribeReveal, revealed],
  );

  return (
    <KeymapContext.Provider value={api}>
      {children}
      <KeymapCheatsheet open={helpOpen} onClose={() => setHelpOpen(false)} scopes={scopes} mac={mac} />
    </KeymapContext.Provider>
  );
}

/** Run `handler` when the keymap fires `id`. Latest render's closure wins, so
 *  the handler can close over state without re-registering. */
export function useKeyAction(id: string, handler: Handler): void {
  const api = useKeymap("useKeyAction");
  const latest = useRef(handler);
  useEffect(() => {
    latest.current = handler;
  });
  useEffect(() => api.register(id, chord => latest.current(chord)), [api, id]);
}

/** Declare a scope live for as long as the component is mounted. */
export function useKeyScope(scope: KeyScope): void {
  const api = useKeymap("useKeyScope");
  useEffect(() => api.pushScope(scope), [api, scope]);
}

/** Claim every keystroke until released — how the room hint overlay reads its
 *  labels without every hint char needing a binding of its own. */
export function useKeyCapture(): KeymapApi["captureKeys"] {
  return useKeymap("useKeyCapture").captureKeys;
}

/** True while the reveal modifier is held: the cue for a target to draw its own
 *  key. Safe outside a provider (a component may render in isolation) — it just
 *  never reveals. */
export function useKeyReveal(): boolean {
  const api = useContext(KeymapContext);
  const [revealed, setRevealed] = useState(false);
  useEffect(() => {
    if (!api) return;
    setRevealed(api.revealed());
    return api.subscribeReveal(setRevealed);
  }, [api]);
  return revealed;
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
