// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { handleMock } from "@/mocks/handlers";
import { subscribe } from "@/mocks/live";

async function mockGet(path: string): Promise<{ status: number; body: unknown }> {
  const res = await handleMock(new Request(`http://localhost${path}`));
  if (!res) throw new Error(`handleMock returned null for ${path}`);
  return { status: res.status, body: await res.json() };
}

describe("mock links handlers", () => {
  it("serves the checkout room's whole link graph", async () => {
    const { status, body } = await mockGet("/api/rooms/checkout/links/graph");
    expect(status).toBe(200);
    const graph = body as { nodes: { key: string; inbound: number; outbound: number }[]; edges: { resolved: boolean }[] };

    expect(graph.nodes.length).toBeGreaterThan(0);
    expect(graph.edges.some((e) => !e.resolved)).toBe(true); // the deliberate broken link
    expect(graph.nodes.some((n) => n.inbound === 0)).toBe(true); // roots or orphans (no inbound)

    // node/edge counts must be internally consistent: every edge endpoint is a real node
    const keys = new Set(graph.nodes.map((n) => n.key));
    const edges = body as { edges: { source: string; target: string }[] };
    for (const e of edges.edges) expect(keys.has(e.source)).toBe(true);
  });

  it("degrades to an empty graph for a room with no link index (scratch)", async () => {
    const { status, body } = await mockGet("/api/rooms/scratch/links/graph");
    expect(status).toBe(200);
    expect(body).toEqual({ nodes: [], edges: [] });
  });

  it("serves one memory's outbound links and backlinks by key", async () => {
    const { status, body } = await mockGet(
      `/api/rooms/checkout/links?key=${encodeURIComponent("decisions/apple-pay-launch")}`,
    );
    expect(status).toBe(200);
    const links = body as { outbound: { target: string; resolved: boolean }[]; backlinks: { source?: string | null }[] };

    // the launch decision links out to context/goal (resolved) and a broken work/ link
    expect(links.outbound.some((l) => l.target === "context/goal" && l.resolved)).toBe(true);
    expect(links.outbound.some((l) => l.resolved === false)).toBe(true);
    // and is linked to by the briefing and the week's status
    expect(links.backlinks.map((l) => l.source).sort()).toEqual(["context/briefing", "status/this-week"]);
  });

  it("derives the integrity report from the same edges the graph draws", async () => {
    // Hand-written integrity would let a fixture claim a clean room while its
    // graph plainly shows a break.
    const { status, body } = await mockGet("/api/rooms/checkout/links/integrity");
    expect(status).toBe(200);
    const report = body as {
      broken: { source: string; target: string }[];
      orphans: string[];
      roots: string[];
      leaves: string[];
      total_memories: number;
    };
    expect(report.broken).toContainEqual(expect.objectContaining({ source: "decisions/apple-pay-launch", target: "work/launch-checklist" }));
    expect(report.total_memories).toBeGreaterThan(0);

    // Orphans must have no inbound AND no outbound edges.
    const { body: graphBody } = await mockGet("/api/rooms/checkout/links/graph");
    const graph = graphBody as { nodes: { key: string; inbound: number; outbound: number }[]; edges: { source: string; target: string; resolved: boolean }[] };
    const nodeMap = new Map(graph.nodes.map((n) => [n.key, n]));
    for (const key of report.orphans) {
      expect(graph.edges.some((e) => e.resolved && e.target === key)).toBe(false);
      expect(nodeMap.get(key)?.outbound ?? 0).toBe(0);
    }
    // Roots must have no inbound but have outbound.
    for (const key of report.roots) {
      expect(graph.edges.some((e) => e.resolved && e.target === key)).toBe(false);
      expect(nodeMap.get(key)?.outbound ?? 0).toBeGreaterThan(0);
    }
    // Leaves must have inbound but no outbound.
    for (const key of report.leaves) {
      expect(graph.edges.some((e) => e.resolved && e.target === key)).toBe(true);
      expect(nodeMap.get(key)?.outbound ?? 0).toBe(0);
    }
  });

  it("expands a transclusion into the embedded memory's text", async () => {
    const { status, body } = await mockGet(
      "/api/rooms/checkout/links/expand?key=" + encodeURIComponent("context/briefing"),
    );
    expect(status).toBe(200);
    const expanded = body as { rendered: string; found: boolean; expansions: { target: string; resolved: boolean }[] };
    expect(expanded.found).toBe(true);
    expect(expanded.rendered).not.toContain("![[context/goal]]");
    expect(expanded.rendered).toContain("stop double charges before the spring sale");
    expect(expanded.expansions).toContainEqual({ raw: "![[context/goal]]", target: "context/goal", resolved: true });
  });

  it("reports a memory it doesn't have as not found rather than empty-but-fine", async () => {
    const { body } = await mockGet("/api/rooms/checkout/links/expand?key=nope");
    expect((body as { found: boolean }).found).toBe(false);
  });

  it("404s a key-scoped lookup with no key", async () => {
    const { status } = await mockGet("/api/rooms/checkout/links");
    expect(status).toBe(404);
  });
});

describe("mock skills handler", () => {
  it("projects the room's skills/ memories into the skills list shape", async () => {
    // `useRoomSkills` runs on every room page; without this route the request
    // fell through to a real backend and 502'd under `pnpm dev:mock`.
    const { status, body } = await mockGet("/api/rooms/storefront/skills");
    expect(status).toBe(200);
    const { skills, total } = body as {
      skills: { name: string; description: string; body: string; created_by: string; version: number }[];
      total: number;
    };
    expect(total).toBe(skills.length);
    expect(skills.length).toBeGreaterThan(0);
    const take = skills.find((s) => s.name === "take-a-task");
    expect(take).toBeDefined();
    // The description is the frontmatter line, the body is the prose after it,
    // and neither carries the `---` fence into the composer's popover.
    expect(take?.description).toBe("Take a task off the board, work it in its own thread, resolve it.");
    expect(take?.body.startsWith("Claim an open")).toBe(true);
    expect(take?.body).not.toContain("---");
    expect(take?.created_by).toBe("operator");
    expect(take?.version).toBe(2);
  });

  it("answers an empty list for a room with no skills rather than proxying", async () => {
    const { status, body } = await mockGet("/api/rooms/scratch/skills");
    expect(status).toBe(200);
    expect(body).toEqual({ skills: [], total: 0 });
  });
});

describe("mock memory write handler", () => {
  async function post(room: string, items: unknown[]) {
    const res = await handleMock(new Request(`http://localhost/api/rooms/${room}/memory`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ items }),
    }));
    if (!res) throw new Error("handleMock returned null for the memory write");
    return { status: res.status, body: await res.json() };
  }

  it("upserts a memory and bumps its version", async () => {
    const before = await mockGet("/api/rooms/checkout/memory");
    const first = (before.body as { key: string; version: number }[])[0];

    const { status, body } = await post("checkout", [
      { key: first.key, value: "rewritten", created_by: "alice" },
    ]);
    expect(status).toBe(201);
    expect((body as { version: number }[])[0].version).toBe(first.version + 1);
  });

  it("rejects a stale base_version with 409", async () => {
    const { body } = await mockGet("/api/rooms/checkout/memory");
    const target = (body as { key: string; version: number }[])[0];

    const res = await post("checkout", [
      { key: target.key, value: "x", created_by: "alice", base_version: target.version + 99 },
    ]);
    expect(res.status).toBe(409);
    expect((res.body as { error: string }).error).toBe("stale_base");
  });

  it("round-trips tags and the expandable flag", async () => {
    await post("checkout", [{
      key: "context/mock-write-probe",
      value: "body text",
      created_by: "alice",
      tags: ["alpha", "beta"],
      meta: { expandable: true },
    }]);

    const { body } = await mockGet("/api/rooms/checkout/memory/context/mock-write-probe");
    const mem = body as { tags?: string[]; expandable?: boolean };
    expect(mem.tags).toEqual(["alpha", "beta"]);
    expect(mem.expandable).toBe(true);
  });

  it("clears the expandable flag when the write says false", async () => {
    await post("checkout", [{
      key: "context/mock-clear-probe", value: "b", created_by: "alice",
      meta: { expandable: true },
    }]);
    await post("checkout", [{
      key: "context/mock-clear-probe", value: "b", created_by: "alice",
      meta: { expandable: false },
    }]);

    const { body } = await mockGet("/api/rooms/checkout/memory/context/mock-clear-probe");
    expect((body as { expandable?: boolean }).expandable).toBe(false);
  });
});

describe("mock live writes", () => {
  const postJson = async (path: string, body: unknown) => {
    const res = await handleMock(
      new Request(`http://localhost${path}`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      }),
    );
    if (!res) throw new Error(`handleMock returned null for ${path}`);
    return { status: res.status, body: (await res.json()) as Record<string, unknown> };
  };

  it("stores a posted message and puts it on the room's stream", async () => {
    const heard: Record<string, unknown>[] = [];
    const stop = subscribe("scratch", (f) => heard.push(f));
    const { status, body } = await postJson("/api/rooms/scratch/messages", {
      sender_handle: "alice",
      message_type: "broadcast",
      content: "hello, room",
      episode: null,
    });
    stop();
    expect(status).toBe(201);
    expect(heard.some((f) => f.content === "hello, room")).toBe(true);
    const { body: read } = await mockGet("/api/rooms/scratch/messages?limit=5");
    const messages = (read as { messages: { id: string }[] }).messages;
    expect(messages.some((m) => m.id === body.id)).toBe(true);
  });

  it("files a task as a work/ row with a thread of its own, and raises a filed notice", async () => {
    const heard: Record<string, unknown>[] = [];
    const stop = subscribe("scratch", (f) => heard.push(f));
    const { status, body } = await postJson("/api/rooms/scratch/tasks", {
      title: "Write the release notes",
      handle: "alice",
      assignee: "bob",
    });
    stop();
    expect(status).toBe(201);
    expect(body.key).toBe("work/write-the-release-notes");
    expect(String(body.episode)).toMatch(/^urn:ioc:mycelium:episode:scratch:[0-9a-f]{8}$/);
    expect(body.meta).toMatchObject({ kind: "action", status: "open", assignee: "bob" });
    const notice = heard.find((f) => JSON.stringify(f).includes('"subkind":"filed"'));
    expect(notice).toBeDefined();

    const again = await postJson("/api/rooms/scratch/tasks", { title: "Write the release notes", handle: "alice" });
    expect(again.status).toBe(409);
  });

  it("claims and resolves a row through the assignment routes", async () => {
    await postJson("/api/rooms/scratch/tasks", { title: "Tidy the backlog", handle: "alice" });
    const claimed = await postJson("/api/rooms/scratch/assignments/claim", { key: "work/tidy-the-backlog", handle: "bob" });
    expect(claimed.body).toMatchObject({ assignment: "held", owner: "@bob" });
    const resolved = await postJson("/api/rooms/scratch/assignments/resolve", { key: "work/tidy-the-backlog", handle: "bob" });
    expect(resolved.body).toMatchObject({ assignment: "resolved" });
    const { body } = await mockGet("/api/rooms/scratch/memory/work/tidy-the-backlog");
    expect((body as { meta: Record<string, unknown> }).meta.status).toBe("resolved");
  });
});
