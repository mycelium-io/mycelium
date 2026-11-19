// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

const refresh = vi.fn();
let session = { signedIn: true, needsHandle: true, suggested: "avery" as string | null };

vi.mock("@/lib/api", () => ({ pickHandle: vi.fn() }));
vi.mock("@/components/auth-session", () => ({
  useAuthSession: () => ({ ...session, refresh }),
}));

import { HandlePicker } from "@/components/handle-picker";
import { pickHandle } from "@/lib/api";

beforeEach(() => {
  vi.clearAllMocks();
  session = { signedIn: true, needsHandle: true, suggested: "avery" };
  vi.mocked(pickHandle).mockResolvedValue({ handle: "aquinn" });
});

describe("<HandlePicker />", () => {
  it("asks a signed-in person whose short handle is taken to pick one, and keeps it", async () => {
    render(<HandlePicker />);
    expect(screen.getByText(/@avery is taken here/)).toBeInTheDocument();
    await userEvent.type(screen.getByLabelText("Your handle"), "@AQuinn");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(pickHandle).toHaveBeenCalledWith("aquinn");
    expect(refresh).toHaveBeenCalled();
  });

  it("says the hub's reason when it refuses", async () => {
    vi.mocked(pickHandle).mockRejectedValueOnce(new Error("@aquinn is taken. Pick another."));
    render(<HandlePicker />);
    await userEvent.type(screen.getByLabelText("Your handle"), "aquinn");
    await userEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("@aquinn is taken");
  });

  it("asks nobody who has a handle", () => {
    session = { signedIn: true, needsHandle: false, suggested: null };
    render(<HandlePicker />);
    expect(screen.queryByText("Pick your handle")).not.toBeInTheDocument();
  });
});
