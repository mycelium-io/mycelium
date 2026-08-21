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
  useSyncExternalStore,
  type ReactNode,
} from "react";
import { useIsMac } from "@/lib/client-hooks";
import { CommandPalette } from "@/components/command-palette";
import { KeymapCheatsheet } from "@/components/keymap-cheatsheet";
import { loadRecent, pushRecent, saveRecent, type PaletteCommand } from "@/lib/commands";
import {
  chordFor,
  eventToChord,
  formatChord,
  isCommandChord,
  isModifierKey,
  matchBinding,
  paletteBindings,
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
  /** Offer commands to the palette while mounted. One list per source, keyed by
   *  a token, so a source can revise its list without disturbing the others. */
  registerCommands: (token: symbol, commands: PaletteCommand[]) => () => void;
  openHelp: () => void;
  openPalette: () => void;
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
  const commandSources = useRef(new Map<symbol, PaletteCommand[]>());
  const [scopeCounts, setScopeCounts] = useState<Partial<Record<KeyScope, number>>>({ global: 1 });
  const [helpOpen, setHelpOpen] = useState(false);
  const [paletteOpen, setPaletteOpen] = useState(false);
  // Which commands ran, most recent first. Hydrated from localStorage after mount
  // so that SSR and the first hydration render both produce [] (no mismatch).
  const [recent, setRecent] = useState<string[]>([]);
  useEffect(() => {
    // SSR hydration: localStorage unavailable on server; useSyncExternalStore would
    // still need a separate setRecent for command-use writes, so this is simpler.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setRecent(loadRecent());
  }, []);
  const mac = useIsMac();

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

  // Registering the same ids again is the common case — a source re-runs its
  // effect whenever its list is rebuilt — and must not invalidate anything, or
  // a caller that forgot to memoize would spin. Only the *set* of commands is
  // state; the palette reads each command's current closure off the ref.
  const [commandEpoch, setCommandEpoch] = useState(0);
  const registerCommands = useCallback<KeymapApi["registerCommands"]>((token, commands) => {
    const sameIds = (a: readonly PaletteCommand[], b: readonly PaletteCommand[]) =>
      a.length === b.length && a.every((command, i) => command.id === b[i].id);
    const previous = commandSources.current.get(token);
    commandSources.current.set(token, commands);
    if (!previous || !sameIds(previous, commands)) setCommandEpoch(e => e + 1);
    return () => {
      commandSources.current.delete(token);
      setCommandEpoch(e => e + 1);
    };
  }, []);

  const dispatch = useCallback((id: string, chord: string): boolean => {
    const list = handlers.current.get(id);
    if (!list || list.length === 0) return false;
    // Every registrant runs: focusing the composer, for instance, is one
    // action the room page (switch to the channel pane) and the chat box
    // (focus the textarea) each own a half of.
    for (const handler of [...list]) handler(chord);
    return true;
  }, []);

  /** What the palette can run right now. Registered commands come first, so a
   *  room outranks "Next room" under the same heading; a binding contributes a
   *  row only where something has registered to handle it, which is what keeps
   *  the list honest about the current context. */
  const collectCommands = useCallback((activeScopes: readonly KeyScope[]): PaletteCommand[] => {
    const collected: PaletteCommand[] = [];
    const seen = new Set<string>();
    const add = (command: PaletteCommand) => {
      if (seen.has(command.id)) return;
      seen.add(command.id);
      collected.push(command);
    };
    for (const commands of commandSources.current.values()) {
      for (const command of commands) add({ ...command, shortcut: command.shortcut ?? chordFor(command.id) });
    }
    for (const binding of paletteBindings(activeScopes)) {
      if (!handlers.current.has(binding.id)) continue;
      add({
        id: binding.id,
        title: binding.label,
        group: binding.group,
        shortcut: binding.keys[0],
        run: () => dispatch(binding.id, binding.keys[0]),
      });
    }
    return collected;
  }, [dispatch]);

  const commands = useMemo(
    () => {
      // collectCommands reads commandSources.current and handlers.current (refs).
      // Moving this into useEffect + setState would introduce set-state-in-effect;
      // the refs are intentionally stable mutable registries — reading them here is safe.
      // eslint-disable-next-line react-hooks/refs
      return paletteOpen ? collectCommands(scopes) : [];
    },
    // commandEpoch is a cache-bust epoch that increments on registration changes;
    // it is not referenced in the callback body (refs are read via collectCommands)
    // but IS required so the list recomputes when registrations change.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [paletteOpen, commandEpoch, scopes, collectCommands],
  );

  const runCommand = useCallback(
    (id: string) => {
      const command = collectCommands(scopesRef.current).find(c => c.id === id);
      if (!command) return;
      setRecent(previous => {
        const next = pushRecent(previous, id);
        saveRecent(next);
        return next;
      });
      setPaletteOpen(false);
      command.run();
    },
    [collectCommands],
  );

  const openHelp = useCallback(() => setHelpOpen(true), []);
  const openPalette = useCallback(() => setPaletteOpen(true), []);
  const closePalette = useCallback(() => setPaletteOpen(false), []);

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
        if (chord === "Escape") {
          (target as HTMLElement).blur();
          return;
        }
        // Typing is typing, with one exception: a ⌘/Ctrl chord isn't a
        // character, so the palette stays reachable from the composer.
        if (!isCommandChord(chord)) return;
      }

      const binding = matchBinding(chord, scopesRef.current);
      if (!binding) return;

      // The two surfaces the provider owns; everything else is dispatched to
      // whoever registered it, and an unclaimed binding leaves the key alone.
      const surface = { "help.keys": setHelpOpen, "palette.open": setPaletteOpen }[binding.id];
      if (!surface && !handlers.current.has(binding.id)) return;
      e.preventDefault();
      setRevealed(false);
      if (surface) surface(true);
      else dispatch(binding.id, chord);
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
  }, [setRevealed, dispatch]);

  // Every member is a stable callback, so the context value never changes
  // identity — a scope declaring itself live must not invalidate the very
  // effect that declared it.
  const api = useMemo<KeymapApi>(
    () => ({ register, pushScope, captureKeys, registerCommands, openHelp, openPalette, subscribeReveal, revealed }),
    [register, pushScope, captureKeys, registerCommands, openHelp, openPalette, subscribeReveal, revealed],
  );

  return (
    <KeymapContext.Provider value={api}>
      {children}
      <KeymapCheatsheet open={helpOpen} onClose={() => setHelpOpen(false)} scopes={scopes} mac={mac} />
      <CommandPalette
        open={paletteOpen}
        onClose={closePalette}
        commands={commands}
        recent={recent}
        onRun={runCommand}
        mac={mac}
      />
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

/** Offer commands to the palette while this component is mounted — the whole
 *  of the context-awareness: a room's commands leave with the room.
 *
 *  Memoize `commands`; an unmemoized array re-registers on every render, which
 *  costs a map write rather than a loop, but is still churn worth avoiding. */
export function useCommands(commands: PaletteCommand[]): void {
  const api = useKeymap("useCommands");
  const token = useMemo(() => Symbol("commands"), []);
  useEffect(() => api.registerCommands(token, commands), [api, token, commands]);
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
  // useSyncExternalStore is the idiomatic fit: subscribe to an external signal
  // (the hold/release of the reveal modifier) and snapshot its current value.
  return useSyncExternalStore(
    (listener) => api?.subscribeReveal(listener) ?? (() => {}),
    () => api?.revealed() ?? false,
    () => false,
  );
}

/** The status-bar affordances that make `?` and ⌘K findable without knowing
 *  either. The palette is itself the discovery surface for everything else, so
 *  it earns a permanent seat next to the cheatsheet. */
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

export function CommandPaletteButton() {
  const api = useContext(KeymapContext);
  const mac = useIsMac();
  if (!api) return null;
  return (
    <button
      type="button"
      onClick={api.openPalette}
      title="Command palette"
      className="rounded px-1 text-micro text-muted-foreground transition-colors hover:text-text"
    >
      <kbd className="font-sans">{formatChord(chordFor("palette.open") ?? "", mac)}</kbd> commands
    </button>
  );
}

