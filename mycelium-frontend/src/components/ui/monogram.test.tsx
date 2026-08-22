// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { Monogram } from "@/components/ui/monogram";
import { RoomAvatar } from "@/components/ui/room-avatar";
import { avatarTint, initials } from "@/lib/avatar-color";

describe("avatarTint", () => {
  it("gives a handle the same tint every time", () => {
    expect(avatarTint("backend-lead")).toBe(avatarTint("backend-lead"));
  });

  it("ignores case, so @Growth and growth are one identity", () => {
    expect(avatarTint("Growth")).toBe(avatarTint("growth"));
  });

  it("stays inside the palette the stylesheet defines", () => {
    for (const name of ["a", "atlas-migration", "risk", "", "…"]) {
      expect(avatarTint(name)).toMatch(/^var\(--avatar-[1-6]\)$/);
    }
  });

  it("spreads names across the palette instead of piling onto one tint", () => {
    // The plain FNV-1a this is built on mixes its low bits poorly, and the slot
    // is a small modulo — without the avalanche step most names collide.
    const names = Array.from({ length: 300 }, (_, i) => `room-${i}`);
    const used = new Set(names.map(avatarTint));
    expect(used.size).toBe(6);

    const counts = new Map<string, number>();
    for (const name of names) {
      const tint = avatarTint(name);
      counts.set(tint, (counts.get(tint) ?? 0) + 1);
    }
    // An even split is 50 each; allow a wide band and still catch a pile-up.
    for (const count of counts.values()) expect(count).toBeGreaterThan(20);
  });
});

describe("initials", () => {
  it.each([
    ["backend-lead", "BL"],
    ["oc-test2", "OT"],
    ["main", "MA"],
    ["atlas-migration", "AM"],
  ])("renders %s as %s", (input, expected) => {
    expect(initials(input)).toBe(expected);
  });
});

describe("<Monogram />", () => {
  it("names the presence tier for a screen reader, not just in colour", () => {
    render(<Monogram handle="growth" presence="slim" />);
    expect(screen.getByLabelText("SLIM connected")).toBeInTheDocument();
  });

  it("breathes the halo for a poll in flight and holds it steady for a socket", () => {
    const { container: lease } = render(<Monogram handle="growth" presence="lease" />);
    expect(lease.querySelector(".avatar-halo.pulse")).toBeTruthy();

    const { container: slim } = render(<Monogram handle="growth" presence="slim" />);
    expect(slim.querySelector(".avatar-halo")).toBeTruthy();
    expect(slim.querySelector(".avatar-halo.pulse")).toBeNull();
  });

  it("draws no halo at all for a handle that is not present", () => {
    const { container } = render(<Monogram handle="growth" />);
    expect(container.querySelector(".avatar-halo")).toBeNull();
  });

  it("keeps the disc opaque, so a pile of them does not go muddy", () => {
    const { container } = render(<Monogram handle="growth" />);
    const disc = container.querySelector("[aria-hidden]") as HTMLElement;
    expect(disc.style.background).toContain("var(--paper)");
    expect(disc.style.background).not.toContain("transparent");
  });
});

describe("<RoomAvatar />", () => {
  it("draws the room's monogram", () => {
    render(<RoomAvatar name="atlas-migration" />);
    expect(screen.getByText("AM")).toBeInTheDocument();
  });

  it("is decorative — the room name is always spelled beside it", () => {
    const { container } = render(<RoomAvatar name="atlas-migration" />);
    expect(container.firstElementChild).toHaveAttribute("aria-hidden");
  });

  it("lifts the tile when it is the open room", () => {
    const { container: resting } = render(<RoomAvatar name="scratch" />);
    const { container: active } = render(<RoomAvatar name="scratch" active />);
    const bg = (c: Element) => (c.firstElementChild as HTMLElement).style.background;
    expect(bg(active)).not.toBe(bg(resting));
  });
});
