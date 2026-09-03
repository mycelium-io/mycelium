// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import "@testing-library/jest-dom/vitest";

// Node 25 ships an incomplete native `localStorage` stub on `globalThis`
// (no `clear`, `getItem`, etc.) that shadows jsdom's working Storage because
// jsdom skips re-installing globals that already exist.  Detect the broken
// stub and replace it with an in-memory Storage before any test code runs.
if (typeof window !== "undefined") {
  const candidate = (globalThis as { localStorage?: Storage }).localStorage;
  const isBroken = !candidate || typeof candidate.getItem !== "function";
  if (isBroken) {
    // Each name gets its own backing map — sharing one would let a write to
    // localStorage be read back out of sessionStorage.
    const makeStorage = (): Storage => {
      const data = new Map<string, string>();
      return {
        get length() { return data.size; },
        clear()                           { data.clear(); },
        getItem(key: string)              { return data.get(key) ?? null; },
        setItem(key: string, val: string) { data.set(key, String(val)); },
        removeItem(key: string)           { data.delete(key); },
        key(index: number)                { return Array.from(data.keys())[index] ?? null; },
      };
    };
    const local = makeStorage();
    const session = makeStorage();
    for (const target of [globalThis, window] as unknown[]) {
      Object.defineProperty(target, "localStorage", { configurable: true, writable: true, value: local });
      Object.defineProperty(target, "sessionStorage", { configurable: true, writable: true, value: session });
    }
  }
}

// jsdom doesn't implement these DOM APIs the components lean on (scroll
// helpers, ResizeObserver for base-ui's dialog, matchMedia). Stub them so
// component tests exercise real render paths instead of tripping on the
// environment.
if (!Element.prototype.scrollTo) {
  Element.prototype.scrollTo = () => {};
}
if (!Element.prototype.scrollIntoView) {
  Element.prototype.scrollIntoView = () => {};
}
if (!Element.prototype.getAnimations) {
  Element.prototype.getAnimations = () => [];
}
if (!("ResizeObserver" in globalThis)) {
  globalThis.ResizeObserver = class {
    observe() {}
    unobserve() {}
    disconnect() {}
  };
}
// Node 22+ ships its own Web Storage, and Node hands over an empty object with
// none of the `Storage` methods on it when that's enabled without a valid
// `--localstorage-file` (it says so: "`--localstorage-file` was provided without
// a valid path"). That bare global then shadows the implementation jsdom would
// have installed, so anything calling `localStorage.getItem` fails on the
// environment rather than on its own behaviour.
//
// Installed only when the global isn't usable, so a runtime whose Web Storage
// works keeps it. In-memory rather than file-backed on purpose: tests must not
// inherit state from the last run.
if (typeof globalThis.localStorage?.getItem !== "function") {
  const entries = new Map<string, string>();
  const storage: Storage = {
    get length() {
      return entries.size;
    },
    key: index => [...entries.keys()][index] ?? null,
    getItem: key => entries.get(String(key)) ?? null,
    setItem: (key, value) => void entries.set(String(key), String(value)),
    removeItem: key => void entries.delete(String(key)),
    clear: () => entries.clear(),
  };
  // Configurable + writable so a test can still swap in its own store; several
  // assert on how the code behaves when storage is absent or throwing.
  Object.defineProperty(globalThis, "localStorage", { value: storage, configurable: true, writable: true });
}

if (!globalThis.matchMedia) {
  globalThis.matchMedia = (query: string) => ({
    matches: false,
    media: query,
    onchange: null,
    addListener: () => {},
    removeListener: () => {},
    addEventListener: () => {},
    removeEventListener: () => {},
    dispatchEvent: () => false,
  }) as unknown as MediaQueryList;
}
