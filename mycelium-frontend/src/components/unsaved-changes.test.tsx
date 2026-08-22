// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { useUnsavedGuard } from "@/components/unsaved-changes";

/** Minimal stand-in for a host that owns an editor and a way to leave it. */
function Harness({ onLeave }: { onLeave: () => void }) {
  const { setDirty, guard, dialog } = useUnsavedGuard();
  return (
    <div>
      <button onClick={() => setDirty(true)}>Make dirty</button>
      <button onClick={() => guard(onLeave)}>Leave</button>
      {dialog}
    </div>
  );
}

describe("useUnsavedGuard", () => {
  it("lets the action through when nothing is unsaved", async () => {
    const user = userEvent.setup();
    const onLeave = vi.fn();
    render(<Harness onLeave={onLeave} />);

    await user.click(screen.getByRole("button", { name: "Leave" }));

    expect(onLeave).toHaveBeenCalledTimes(1);
    expect(screen.queryByText(/discard unsaved changes/i)).not.toBeInTheDocument();
  });

  it("holds the action back and prompts when there are unsaved edits", async () => {
    const user = userEvent.setup();
    const onLeave = vi.fn();
    render(<Harness onLeave={onLeave} />);

    await user.click(screen.getByRole("button", { name: "Make dirty" }));
    await user.click(screen.getByRole("button", { name: "Leave" }));

    expect(onLeave).not.toHaveBeenCalled();
    expect(await screen.findByText(/discard unsaved changes/i)).toBeInTheDocument();
  });

  it("runs the held action once the user confirms", async () => {
    const user = userEvent.setup();
    const onLeave = vi.fn();
    render(<Harness onLeave={onLeave} />);

    await user.click(screen.getByRole("button", { name: "Make dirty" }));
    await user.click(screen.getByRole("button", { name: "Leave" }));
    await user.click(await screen.findByRole("button", { name: "Discard" }));

    await waitFor(() => expect(onLeave).toHaveBeenCalledTimes(1));
  });

  it("drops the held action when the user keeps editing", async () => {
    const user = userEvent.setup();
    const onLeave = vi.fn();
    render(<Harness onLeave={onLeave} />);

    await user.click(screen.getByRole("button", { name: "Make dirty" }));
    await user.click(screen.getByRole("button", { name: "Leave" }));
    await user.click(await screen.findByRole("button", { name: "Keep editing" }));

    expect(onLeave).not.toHaveBeenCalled();
    await waitFor(() =>
      expect(screen.queryByText(/discard unsaved changes/i)).not.toBeInTheDocument(),
    );
  });

  it("asks the browser to confirm a tab close only while dirty", async () => {
    const user = userEvent.setup();
    render(<Harness onLeave={vi.fn()} />);

    const fire = () => {
      const e = new Event("beforeunload", { cancelable: true });
      window.dispatchEvent(e);
      return e.defaultPrevented;
    };

    expect(fire()).toBe(false);
    await user.click(screen.getByRole("button", { name: "Make dirty" }));
    await waitFor(() => expect(fire()).toBe(true));
  });

  it("stops prompting once the editor reports itself clean again", async () => {
    const user = userEvent.setup();
    const onLeave = vi.fn();
    function CleanableHarness() {
      const { setDirty, guard, dialog } = useUnsavedGuard();
      return (
        <div>
          <button onClick={() => setDirty(true)}>Make dirty</button>
          <button onClick={() => setDirty(false)}>Mark saved</button>
          <button onClick={() => guard(onLeave)}>Leave</button>
          {dialog}
        </div>
      );
    }
    render(<CleanableHarness />);

    await user.click(screen.getByRole("button", { name: "Make dirty" }));
    await user.click(screen.getByRole("button", { name: "Mark saved" }));
    await user.click(screen.getByRole("button", { name: "Leave" }));

    expect(onLeave).toHaveBeenCalledTimes(1);
  });
});
