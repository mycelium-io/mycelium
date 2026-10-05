// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import { StatusButton, machinesSummary } from "@/components/status-items";
import type { Runner } from "@/lib/api";
import { TooltipProvider } from "@/components/ui/tooltip";

vi.mock("next/navigation", () => ({ usePathname: () => "/" }));

function renderCell(action?: string) {
  return render(
    <TooltipProvider>
      <StatusButton onClick={() => {}} tooltip="View agents" action={action}>
        <span>3 agents</span>
      </StatusButton>
    </TooltipProvider>,
  );
}

describe("<StatusButton />", () => {
  it("names the key that does the same thing, so the rail teaches the shortcut", async () => {
    const user = userEvent.setup();
    const { container } = renderCell("rail.agents");

    await user.hover(screen.getByRole("button"));

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("View agents");
    // Portaled out of `container`, so the cap is looked for in the document.
    expect(tooltip.querySelector("kbd")?.textContent).toBe("Alt+A");
    expect(container.querySelector("kbd")).toBeNull();
  });

  it("keeps the bare label for a cell no key reaches", async () => {
    const user = userEvent.setup();
    renderCell();

    await user.hover(screen.getByRole("button"));

    const tooltip = await screen.findByRole("tooltip");
    expect(tooltip).toHaveTextContent("View agents");
    expect(tooltip.querySelector("kbd")).toBeNull();
  });
});

describe("machinesSummary", () => {
  const runner = (over: Partial<Runner> = {}): Runner => ({
    id: "r1",
    label: "morgans-mbp",
    owner: null,
    platform: "darwin-arm64",
    version: "0.14.0",
    herdr: true,
    roots: [],
    frameworks: [],
    agents: [],
    connected: true,
    last_seen: "",
    started_at: "",
    ...over,
  });

  it("names the one machine, and says when there is none", () => {
    expect(machinesSummary([])).toEqual({ text: "no machines", tone: "off", problems: 0 });
    expect(machinesSummary([runner()])).toEqual({ text: "morgans-mbp", tone: "ok", problems: 0 });
  });

  it("counts several, and warns when one is offline", () => {
    const s = machinesSummary([runner(), runner({ id: "r2", connected: false })]);
    expect(s).toEqual({ text: "2", tone: "warn", problems: 0 });
    expect(machinesSummary([runner({ connected: false })]).tone).toBe("bad");
  });

  it("counts what needs fixing on machines that are up", () => {
    const problem = { kind: "stopped" as const, text: "stopped", fix: null, handles: [] };
    const machine = { problems: [problem, problem] } as unknown as Runner["machine"];
    expect(machinesSummary([runner({ machine })])).toMatchObject({ tone: "warn", problems: 2 });
    expect(machinesSummary([runner({ machine, connected: false })]).problems).toBe(0);
  });
});
