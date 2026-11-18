// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ModalDialog } from "@/components/ui/modal-dialog";

/** An opener and the dialog it mounts, the way the app's prompts are used. */
function Harness({ onClose = vi.fn(), lightDismiss }: { onClose?: () => void; lightDismiss?: boolean }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Open
      </button>
      {open && (
        <ModalDialog
          aria-label="Prompt"
          lightDismiss={lightDismiss}
          onClose={() => {
            setOpen(false);
            onClose();
          }}
        >
          <button type="button">First</button>
          <input aria-label="Name" data-autofocus />
          <button type="button" onClick={() => setOpen(false)}>
            Done
          </button>
        </ModalDialog>
      )}
    </>
  );
}

const dialog = () => screen.getByRole("dialog", { name: "Prompt" });
const pointer = (type: "pointerDown" | "pointerUp", target: Element, x: number) =>
  fireEvent[type](target, { clientX: x, clientY: x });

describe("<ModalDialog />", () => {
  it("opens as a native modal dialog with no role or aria-modal of its own", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Open" }));

    expect(dialog().tagName).toBe("DIALOG");
    expect(dialog()).toHaveAttribute("open");
    expect(dialog()).not.toHaveAttribute("role");
    expect(dialog()).not.toHaveAttribute("aria-modal");
  });

  it("focuses the element marked data-autofocus, not the first control", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(screen.getByLabelText("Name")).toHaveFocus();
  });

  it("closes on Escape and tells the parent", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<Harness onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Open" }));

    await user.keyboard("{Escape}");
    expect(onClose).toHaveBeenCalledTimes(1);
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
  });

  it("returns focus to the opener when the parent unmounts it", async () => {
    const user = userEvent.setup();
    render(<Harness />);
    const opener = screen.getByRole("button", { name: "Open" });
    await user.click(opener);

    await user.click(screen.getByRole("button", { name: "Done" }));
    expect(screen.queryByRole("dialog")).not.toBeInTheDocument();
    expect(opener).toHaveFocus();
  });

  it("closes on a press and release outside its box where closedby is missing", async () => {
    const onClose = vi.fn();
    const user = userEvent.setup();
    render(<Harness onClose={onClose} />);
    await user.click(screen.getByRole("button", { name: "Open" }));
    // jsdom lays nothing out, so the test gives the dialog its box.
    vi.spyOn(dialog(), "getBoundingClientRect").mockReturnValue(new DOMRect(10, 10, 100, 100));

    // A drag that starts inside, as a text selection would, doesn't dismiss.
    pointer("pointerDown", dialog(), 50);
    pointer("pointerUp", dialog(), 500);
    expect(onClose).not.toHaveBeenCalled();

    pointer("pointerDown", dialog(), 500);
    pointer("pointerUp", dialog(), 500);
    expect(onClose).toHaveBeenCalledTimes(1);
  });

  it("asks the browser for light dismiss, and leaves it off when told to", async () => {
    const user = userEvent.setup();
    const { unmount } = render(<Harness />);
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(dialog()).toHaveAttribute("closedby", "any");
    unmount();

    const onClose = vi.fn();
    render(<Harness onClose={onClose} lightDismiss={false} />);
    await user.click(screen.getByRole("button", { name: "Open" }));
    expect(dialog()).toHaveAttribute("closedby", "closerequest");
    pointer("pointerDown", dialog(), 500);
    pointer("pointerUp", dialog(), 500);
    expect(onClose).not.toHaveBeenCalled();
  });
});
