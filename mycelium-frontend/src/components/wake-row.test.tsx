// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import fs from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { WakeRow } from "@/components/wake-row";

const { samples } = JSON.parse(
  fs.readFileSync(path.resolve(__dirname, "../../../contracts/wake-digests.json"), "utf8"),
) as { samples: { name: string; text: string }[] };
const withMembers = samples.find((s) => s.text.includes("\nMembers ("))!;

describe("<WakeRow />", () => {
  it("leads with why it woke and the message that woke it", () => {
    render(<WakeRow text={withMembers.text} />);
    expect(screen.getByRole("button", { name: /it's your turn in the room/ })).toBeInTheDocument();
    expect(screen.getByText("@hay")).toBeInTheDocument();
    expect(screen.getByText(/does the rounding cover refunds/)).toBeInTheDocument();
    // The rest waits behind the fold.
    expect(screen.queryByText("Since")).toBeNull();
  });

  it("opens to what changed, the room's agents and the wake as sent", async () => {
    render(<WakeRow text={withMembers.text} />);
    await userEvent.click(screen.getByRole("button", { name: /it's your turn in the room/ }));
    expect(screen.getByText("Since")).toBeInTheDocument();
    expect(screen.getByText("Named silently")).toBeInTheDocument();
    expect(screen.getByText("@desktop")).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Show the wake as sent" }));
    expect(screen.getByText(/^mycelium wake for @builder/)).toBeInTheDocument();
  });

  it("shows a wake it can't read as the text it was", async () => {
    render(<WakeRow text="Please look at the build." />);
    await userEvent.click(screen.getByRole("button", { name: "Woken by the room" }));
    expect(screen.getByText("Please look at the build.")).toBeInTheDocument();
  });
});
