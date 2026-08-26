// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { act, useState } from "react";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useCollapsibleRail } from "@/lib/use-collapsible-rail";
import { SETTLE_MS } from "@/lib/use-viewport";

const FOLD_WIDTH = 600;

/** A matchMedia the test drives: jsdom has none, and the window is what this
 *  hook reads. Every listener is told the truth about the width it asked about. */
const listeners: (() => void)[] = [];
let windowWidth = FOLD_WIDTH + 200;

function stubMatchMedia(): void {
  vi.stubGlobal("matchMedia", (query: string) => {
    const max = Number(/max-width:\s*(\d+)px/.exec(query)?.[1] ?? 0);
    return {
      get matches() {
        return windowWidth <= max;
      },
      addEventListener: (_: string, onChange: () => void) => listeners.push(onChange),
      removeEventListener: (_: string, onChange: () => void) => {
        const at = listeners.indexOf(onChange);
        if (at >= 0) listeners.splice(at, 1);
      },
    };
  });
}

/** Resize, then let the hook's settle delay pass — it acts on a window that
 *  has stopped moving, not on every width a drag passes through. */
async function windowAt(width: number): Promise<void> {
  windowWidth = width;
  await act(async () => {
    for (const onChange of [...listeners]) onChange();
    await new Promise(resolve => setTimeout(resolve, SETTLE_MS + 50));
  });
}

/** A rail with no panel behind it: the hook's panel calls no-op on a null ref,
 *  which leaves exactly the open/closed decision this file is about. */
function Rail() {
  const [open, setOpen] = useState(true);
  useCollapsibleRail({
    foldWidth: FOLD_WIDTH,
    defaultWidth: "300px",
    open,
    onOpenChange: setOpen,
  });
  return (
    <>
      <button onClick={() => setOpen(!open)}>toggle</button>
      <span data-testid="rail">{open ? "open" : "closed"}</span>
    </>
  );
}

const rail = () => screen.getByTestId("rail").textContent;

describe("useCollapsibleRail", () => {
  beforeEach(() => {
    listeners.length = 0;
    windowWidth = FOLD_WIDTH + 200;
    stubMatchMedia();
  });

  it("folds the rail away once the window can't hold it", async () => {
    render(<Rail />);
    await windowAt(FOLD_WIDTH + 200);
    expect(rail()).toBe("open");

    await windowAt(FOLD_WIDTH - 1);
    expect(rail()).toBe("closed");
  });

  // Deliberately one-way. Which rails are open is the reader's call, and a
  // window that grew is not them asking for one back — the strip is one click.
  it("leaves the rail folded when the window grows again", async () => {
    render(<Rail />);
    await windowAt(FOLD_WIDTH - 1);
    expect(rail()).toBe("closed");

    await windowAt(FOLD_WIDTH + 200);
    expect(rail()).toBe("closed");
  });

  it("keeps out of the reader's way while the window stays narrow", async () => {
    const user = userEvent.setup();
    render(<Rail />);
    await windowAt(FOLD_WIDTH - 1);
    expect(rail()).toBe("closed");

    // Opening it on a narrow window sticks — the fold is a nudge, not a lock.
    await user.click(screen.getByText("toggle"));
    expect(rail()).toBe("open");
    await windowAt(FOLD_WIDTH - 50);
    expect(rail()).toBe("open");
  });

  // The fold acts on the crossing, so a rail reopened inside a narrow window
  // isn't folded again until the window has been wide enough to hold it.
  it("folds again after the window has been wide in between", async () => {
    const user = userEvent.setup();
    render(<Rail />);
    await windowAt(FOLD_WIDTH - 1);
    await user.click(screen.getByText("toggle"));
    expect(rail()).toBe("open");

    await windowAt(FOLD_WIDTH + 200);
    await windowAt(FOLD_WIDTH - 1);
    expect(rail()).toBe("closed");
  });
});
