// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { InviteDialog } from "./invite-dialog";

const LINK = "https://hub.example.com/join?room=checkout";

describe("InviteDialog", () => {
  it("shows the link, selected, and says what it does", () => {
    render(<InviteDialog open onClose={() => {}} roomName="checkout" link={LINK} />);
    const field = screen.getByLabelText("Invite link") as HTMLTextAreaElement;
    expect(field.value).toBe(LINK);
    expect(field.readOnly).toBe(true);
    expect(document.activeElement).toBe(field);
    expect(field.selectionStart).toBe(0);
    expect(field.selectionEnd).toBe(LINK.length);
    expect(screen.getByText("Invite someone to checkout")).toBeTruthy();
    expect(screen.getByText(/opens the room in the Mycelium app/)).toBeTruthy();
  });

  it("copies the link and says so", async () => {
    const user = userEvent.setup();
    const writeText = vi.spyOn(navigator.clipboard, "writeText").mockResolvedValue();
    render(<InviteDialog open onClose={() => {}} roomName="checkout" link={LINK} />);
    await user.click(screen.getByRole("button", { name: "Copy link" }));
    expect(writeText).toHaveBeenCalledWith(LINK);
    expect(await screen.findByRole("button", { name: "Copied" })).toBeTruthy();
  });

  it("closes from Done", async () => {
    const onClose = vi.fn();
    render(<InviteDialog open onClose={onClose} roomName="checkout" link={LINK} />);
    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    expect(onClose).toHaveBeenCalled();
  });
});
