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
