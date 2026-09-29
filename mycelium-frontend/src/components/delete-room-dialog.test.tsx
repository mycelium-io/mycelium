// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { DeleteRoomDialog } from "@/components/delete-room-dialog";
import { deleteRoom } from "@/lib/api";
import { renderWithSWR } from "@/test/swr";

vi.mock("@/lib/api", () => ({
  deleteRoom: vi.fn(),
}));

describe("<DeleteRoomDialog />", () => {
  beforeEach(() => {
    vi.mocked(deleteRoom).mockReset();
  });

  it("deletes only after confirmation and reports success", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    const onDeleted = vi.fn();
    vi.mocked(deleteRoom).mockResolvedValue(undefined);

    renderWithSWR(
      <DeleteRoomDialog
        roomName="design review"
        open
        onClose={onClose}
        onDeleted={onDeleted}
      />,
    );

    const button = screen.getByRole("button", { name: "Delete room" });
    expect(button).toBeDisabled();
    await user.type(screen.getByLabelText("Type the room name to confirm"), "design review");
    expect(button).toBeEnabled();
    await user.click(button);

    expect(deleteRoom).toHaveBeenCalledWith("design review");
    expect(onDeleted).toHaveBeenCalledOnce();
    expect(onClose).toHaveBeenCalledOnce();
  });

  it("keeps the dialog open and reports deletion errors", async () => {
    const user = userEvent.setup();
    const onClose = vi.fn();
    vi.mocked(deleteRoom).mockRejectedValue(new Error("Room is unavailable"));

    renderWithSWR(
      <DeleteRoomDialog
        roomName="design review"
        open
        onClose={onClose}
        onDeleted={vi.fn()}
      />,
    );

    await user.type(screen.getByLabelText("Type the room name to confirm"), "design review");
    await user.click(screen.getByRole("button", { name: "Delete room" }));

    expect(screen.getByRole("alert")).toHaveTextContent("Room is unavailable");
    expect(onClose).not.toHaveBeenCalled();
  });

  it("stays disabled until the name typed is the room's, and Enter can't get around it", async () => {
    const user = userEvent.setup();
    vi.mocked(deleteRoom).mockResolvedValue(undefined);

    renderWithSWR(
      <DeleteRoomDialog roomName="design review" open onClose={vi.fn()} onDeleted={vi.fn()} />,
    );

    const field = screen.getByLabelText("Type the room name to confirm");
    await user.type(field, "design reviw{Enter}");
    expect(screen.getByRole("button", { name: "Delete room" })).toBeDisabled();
    expect(deleteRoom).not.toHaveBeenCalled();

    await user.clear(field);
    await user.type(field, "design review{Enter}");
    expect(deleteRoom).toHaveBeenCalledWith("design review");
  });
});
