// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { MemoryDetail, type MemoryLike } from "@/components/memory-detail";

vi.mock("@/lib/api", () => ({
  fetchMemoryLinks: vi.fn(),
}));

import { fetchMemoryLinks } from "@/lib/api";

const memory: MemoryLike = {
  key: "context/overview",
  value: { text: "See [[decisions/db]]" },
  content_text: "See [[decisions/db]]",
  version: 1,
  created_by: "alice",
};

describe("MemoryDetail", () => {
  beforeEach(() => {
    vi.mocked(fetchMemoryLinks).mockResolvedValue({
      key: memory.key,
      outbound: [
        {
          target: "decisions/db",
          kind: "wikilink",
          raw: "[[decisions/db]]",
          resolved: true,
        },
      ],
      backlinks: [
        {
          target: memory.key,
          source: "plan/title",
          kind: "wikilink",
          raw: "[[context/overview]]",
          resolved: true,
        },
      ],
    });
  });

  it("renders neighbors on the page variant", async () => {
    const onNavigate = vi.fn();
    render(<MemoryDetail memory={memory} roomName="demo" variant="page" onNavigate={onNavigate} />);
    const relatedSection = (await screen.findByText("Related")).closest("div")?.parentElement;
    expect(relatedSection).toBeTruthy();
    const related = within(relatedSection!);
    expect(related.getByRole("button", { name: "decisions/db" })).toBeInTheDocument();
    expect(related.getByRole("button", { name: "plan/title" })).toBeInTheDocument();
  });

  it("shows integrity banner when this memory has broken outbound links", async () => {
    render(
      <MemoryDetail
        memory={memory}
        roomName="demo"
        variant="page"
        integrity={{
          broken: [
            {
              source: memory.key,
              target: "gone",
              kind: "wikilink",
              raw: "[[gone]]",
              resolved: false,
            },
          ],
          orphans: [],
          total_memories: 1,
          total_links: 1,
        }}
      />,
    );
    expect(await screen.findByRole("status")).toHaveTextContent(/broken outbound link/i);
  });

  it("shows the integrity banner on the rail (default) variant too (#599)", async () => {
    render(
      <MemoryDetail
        memory={memory}
        roomName="demo"
        integrity={{
          broken: [],
          orphans: [memory.key],
          total_memories: 1,
          total_links: 0,
        }}
      />,
    );
    expect(await screen.findByRole("status")).toHaveTextContent(/orphan/i);
  });

  it("uses renderedBody in Rendered mode", async () => {
    render(
      <MemoryDetail
        memory={{ ...memory, content_text: "Original body" }}
        variant="page"
        renderedBody="Expanded body with inlined glossary."
      />,
    );
    expect(await screen.findByText(/Expanded body with inlined glossary/)).toBeInTheDocument();
    expect(screen.queryByText("Original body")).not.toBeInTheDocument();
  });

  it("does not show Format JSON for markdown raw body", async () => {
    const user = userEvent.setup();
    render(<MemoryDetail memory={memory} roomName="demo" />);
    await user.click(screen.getByRole("button", { name: "Raw" }));
    expect(screen.queryByRole("button", { name: /format json/i })).not.toBeInTheDocument();
  });

  it("pretty-prints JSON already in the raw body", async () => {
    const user = userEvent.setup();
    const jsonMemory: MemoryLike = {
      key: "data/config",
      value: { text: '{"enabled":true,"ports":[8080]}' },
      content_text: '{"enabled":true,"ports":[8080]}',
      version: 1,
      created_by: "alice",
    };
    render(<MemoryDetail memory={jsonMemory} roomName="demo" />);
    await user.click(screen.getByRole("button", { name: "Raw" }));
    await user.click(screen.getByRole("button", { name: /pretty-print json/i }));
    const pre = document.querySelector("pre");
    expect(pre?.textContent).toContain('"enabled": true');
    expect(pre?.textContent).toContain('"ports"');
    expect(pre?.textContent).not.toContain('"key":');
    expect(pre?.textContent).not.toContain('"version":');
  });
});
