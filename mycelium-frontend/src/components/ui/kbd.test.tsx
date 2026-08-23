// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";

import { Kbd, KbdChord } from "@/components/ui/kbd";
import { KEYMAP } from "@/lib/keymap";

describe("<Kbd />", () => {
  it("renders a kbd element, so a key is marked up as one", () => {
    render(<Kbd>Esc</Kbd>);
    expect(screen.getByText("Esc").tagName).toBe("KBD");
  });

  it("draws every size at a height the 24px status rail can hold", () => {
    for (const size of ["xs", "sm", "md"] as const) {
      const { unmount } = render(<Kbd size={size}>K</Kbd>);
      const cap = screen.getByText("K");
      const height = /h-\[?(\d+)(?:px)?\]?/.exec(cap.className);
      expect(height, `${size} declares no height`).not.toBeNull();
      // Tailwind's bare scale is quarter-rems; an arbitrary value is px.
      const px = height![0].includes("[") ? Number(height![1]) : Number(height![1]) * 4;
      expect(px, `${size} is too tall for the status rail`).toBeLessThanOrEqual(24);
      unmount();
    }
  });
});

describe("<KbdChord />", () => {
  it("spells a chord for the platform it is told about", () => {
    const { unmount } = render(<KbdChord chord="mod+k" mac />);
    expect(screen.getByText("⌘K")).toBeInTheDocument();
    unmount();

    render(<KbdChord chord="mod+k" mac={false} />);
    expect(screen.getByText("Ctrl+K")).toBeInTheDocument();
  });

  it("reads the chord off the keymap when given an action", () => {
    render(<KbdChord action="palette.open" mac />);
    expect(screen.getByText("⌘K")).toBeInTheDocument();
  });

  it("renders nothing for an action the keymap does not bind, rather than an empty cap", () => {
    const { container } = render(<KbdChord action="does.not.exist" mac />);
    expect(container).toBeEmptyDOMElement();
  });

  it("defaults to the platform the browser reports", () => {
    vi.spyOn(navigator, "userAgent", "get").mockReturnValue("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)");
    render(<KbdChord chord="mod+k" />);
    expect(screen.getByText("⌘K")).toBeInTheDocument();
    vi.restoreAllMocks();
  });

  it("draws a legible cap for every binding, so the cheatsheet has no blanks", () => {
    for (const binding of KEYMAP) {
      const { container, unmount } = render(<KbdChord chord={binding.keys[0]} mac={false} />);
      expect(container.querySelector("kbd")?.textContent, binding.id).toBeTruthy();
      unmount();
    }
  });
});
