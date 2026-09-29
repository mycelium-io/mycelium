// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { fireEvent, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { renderWithSWR } from "@/test/swr";

const setPrincipal = vi.fn();
let principal = "";
let signedIn = false;

vi.mock("@/lib/api", () => ({
  fetchUsers: vi.fn(),
  createUser: vi.fn(),
}));
vi.mock("@/components/current-user", () => ({
  useCurrentUser: () => ({ principal, setPrincipal, ready: true }),
}));
vi.mock("@/components/auth-session", () => ({
  useAuthSession: () => ({ loading: false, signedIn }),
}));

import { NamePrompt } from "@/components/name-prompt";
import { SenderName } from "@/components/sender-name";
import { createUser, fetchUsers, type User } from "@/lib/api";
import { handleFromName, mentionRank } from "@/lib/people";

const morgan: User = { handle: "operator", display_name: "Morgan Reyes", teams: [], notify: null, owns: [] };

beforeEach(() => {
  vi.clearAllMocks();
  window.localStorage.clear();
  principal = "";
  signedIn = false;
  vi.mocked(fetchUsers).mockResolvedValue([morgan]);
  vi.mocked(createUser).mockImplementation(async u => ({ ...morgan, ...u, display_name: u.display_name ?? "" }));
});

describe("handleFromName", () => {
  it("makes a handle a person would recognise", () => {
    expect(handleFromName("Julia Valenti")).toBe("julia-valenti");
    expect(handleFromName("  Zoë  O'Neil ")).toBe("zoe-o-neil");
    expect(handleFromName("!!!")).toBe("");
  });
});

describe("mentionRank", () => {
  it("finds a person by their name, not only their handle", () => {
    expect(mentionRank("jul", "julia@example.com", "Julia Valenti")).toBe(0);
    expect(mentionRank("val", "julia@example.com", "Julia Valenti")).toBe(1);
    expect(mentionRank("lent", "j@example.com", "Julia Valenti")).toBe(2);
    expect(mentionRank("jv", "j@example.com", "Julia Valenti")).toBe(3);
    expect(mentionRank("zed", "j@example.com", "Julia Valenti")).toBeNull();
  });

  it("matches everyone on an empty query, and agents by handle as before", () => {
    expect(mentionRank("", "backfill")).toBe(0);
    expect(mentionRank("back", "backfill")).toBe(0);
    expect(mentionRank("fill", "backfill")).toBe(2);
  });
});

describe("<SenderName />", () => {
  it("shows the name someone gave themselves, with their handle beside it", async () => {
    renderWithSWR(<SenderName handle="operator" />);
    expect(await screen.findByText("Morgan Reyes")).toBeInTheDocument();
    expect(screen.getByText("@operator")).toBeInTheDocument();
  });

  it("shows the handle alone for anyone without a name", async () => {
    renderWithSWR(<SenderName handle="backfill" />);
    await waitFor(() => expect(fetchUsers).toHaveBeenCalled());
    expect(screen.getByText("backfill")).toBeInTheDocument();
    expect(screen.queryByText("@backfill")).not.toBeInTheDocument();
  });
});

describe("<NamePrompt />", () => {
  it("asks a browser that hasn't said who it is, and saves the name it's given", async () => {
    renderWithSWR(<NamePrompt />);
    const name = await screen.findByLabelText("Your name");
    fireEvent.change(name, { target: { value: "Julia Valenti" } });
    expect(screen.getByText("@julia-valenti")).toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    await waitFor(() =>
      expect(createUser).toHaveBeenCalledWith({ handle: "julia-valenti", display_name: "Julia Valenti" }),
    );
    expect(setPrincipal).toHaveBeenCalledWith("julia-valenti");
    expect(window.localStorage.getItem("mycelium.name-asked")).toBe("1");
  });

  it("lets someone already on the hub pick themselves", async () => {
    renderWithSWR(<NamePrompt />);
    fireEvent.click(await screen.findByRole("button", { name: /Morgan Reyes/ }));
    expect(setPrincipal).toHaveBeenCalledWith("operator");
    expect(createUser).not.toHaveBeenCalled();
  });

  it("won't take a handle someone else already has", async () => {
    renderWithSWR(<NamePrompt />);
    await screen.findByRole("button", { name: /Morgan Reyes/ });
    fireEvent.click(screen.getByRole("button", { name: "Change it" }));
    fireEvent.change(screen.getByLabelText("Your name"), { target: { value: "Morgan" } });
    fireEvent.change(screen.getByLabelText("Your handle"), { target: { value: "operator" } });
    fireEvent.click(screen.getByRole("button", { name: "Continue" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("already @operator");
    expect(createUser).not.toHaveBeenCalled();
  });

  it("asks once: not again after Not now, nor of someone already named or signed in", async () => {
    window.localStorage.setItem("mycelium.name-asked", "1");
    const { unmount } = renderWithSWR(<NamePrompt />);
    await waitFor(() => expect(fetchUsers).toHaveBeenCalled());
    expect(screen.queryByText("What should we call you?")).not.toBeInTheDocument();
    unmount();

    window.localStorage.clear();
    principal = "julia";
    const second = renderWithSWR(<NamePrompt />);
    expect(screen.queryByText("What should we call you?")).not.toBeInTheDocument();
    second.unmount();

    principal = "";
    signedIn = true;
    renderWithSWR(<NamePrompt />);
    expect(screen.queryByText("What should we call you?")).not.toBeInTheDocument();
  });
});
