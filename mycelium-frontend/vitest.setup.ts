// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import "@testing-library/jest-dom/vitest";

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
