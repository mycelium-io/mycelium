// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { handleMock } from "@/mocks/handlers";

async function mockGet(path: string): Promise<{ status: number; body: unknown }> {
  const res = await handleMock(new Request(`http://localhost${path}`));
  if (!res) throw new Error(`handleMock returned null for ${path}`);
  return { status: res.status, body: await res.json() };
}

describe("mock links handlers (#599)", () => {
  it("serves the atlas-migration room's whole link graph", async () => {
    const { status, body } = await mockGet("/api/rooms/atlas-migration/links/graph");
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
      `/api/rooms/atlas-migration/links?key=${encodeURIComponent("decisions/cutover")}`,
    );
    expect(status).toBe(200);
    const links = body as { outbound: { target: string; resolved: boolean }[]; backlinks: { source?: string | null }[] };

    // decisions/cutover links out to context/goal (resolved) and a broken work/ link
    expect(links.outbound.some((l) => l.target === "context/goal" && l.resolved)).toBe(true);
    expect(links.outbound.some((l) => l.resolved === false)).toBe(true);
    // and is linked to by context/synthesis and status/sprint
    expect(links.backlinks.map((l) => l.source).sort()).toEqual(["context/synthesis", "status/sprint"]);
  });

  it("derives the integrity report from the same edges the graph draws", async () => {
    // Hand-written integrity would let a fixture claim a clean room while its
    // graph plainly shows a break.
    const { status, body } = await mockGet("/api/rooms/atlas-migration/links/integrity");
    expect(status).toBe(200);
    const report = body as {
      broken: { source: string; target: string }[];
      orphans: string[];
      roots: string[];
      leaves: string[];
      total_memories: number;
    };
    expect(report.broken).toContainEqual(expect.objectContaining({ source: "decisions/cutover", target: "work/cutover-runbook" }));
    expect(report.total_memories).toBeGreaterThan(0);

    // Orphans must have no inbound AND no outbound edges.
    const { body: graphBody } = await mockGet("/api/rooms/atlas-migration/links/graph");
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
      "/api/rooms/atlas-migration/links/expand?key=" + encodeURIComponent("context/synthesis"),
    );
    expect(status).toBe(200);
    const expanded = body as { rendered: string; found: boolean; expansions: { target: string; resolved: boolean }[] };
    expect(expanded.found).toBe(true);
    expect(expanded.rendered).not.toContain("![[context/goal]]");
    expect(expanded.rendered).toContain("Move the catalog off the old store");
    expect(expanded.expansions).toContainEqual({ raw: "![[context/goal]]", target: "context/goal", resolved: true });
  });

  it("reports a memory it doesn't have as not found rather than empty-but-fine", async () => {
    const { body } = await mockGet("/api/rooms/atlas-migration/links/expand?key=nope");
    expect((body as { found: boolean }).found).toBe(false);
  });

  it("404s a key-scoped lookup with no key", async () => {
    const { status } = await mockGet("/api/rooms/atlas-migration/links");
    expect(status).toBe(404);
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
    const before = await mockGet("/api/rooms/atlas-migration/memory");
    const first = (before.body as { key: string; version: number }[])[0];

    const { status, body } = await post("atlas-migration", [
      { key: first.key, value: "rewritten", created_by: "alice" },
    ]);
    expect(status).toBe(201);
    expect((body as { version: number }[])[0].version).toBe(first.version + 1);
  });

  it("rejects a stale base_version with 409", async () => {
    const { body } = await mockGet("/api/rooms/atlas-migration/memory");
    const target = (body as { key: string; version: number }[])[0];

    const res = await post("atlas-migration", [
      { key: target.key, value: "x", created_by: "alice", base_version: target.version + 99 },
    ]);
    expect(res.status).toBe(409);
    expect((res.body as { error: string }).error).toBe("stale_base");
  });

  it("round-trips tags and the expandable flag", async () => {
    await post("atlas-migration", [{
      key: "context/mock-write-probe",
      value: "body text",
      created_by: "alice",
      tags: ["alpha", "beta"],
      meta: { expandable: true },
    }]);

    const { body } = await mockGet("/api/rooms/atlas-migration/memory/context/mock-write-probe");
    const mem = body as { tags?: string[]; expandable?: boolean };
    expect(mem.tags).toEqual(["alpha", "beta"]);
    expect(mem.expandable).toBe(true);
  });

  it("clears the expandable flag when the write says false", async () => {
    await post("atlas-migration", [{
      key: "context/mock-clear-probe", value: "b", created_by: "alice",
      meta: { expandable: true },
    }]);
    await post("atlas-migration", [{
      key: "context/mock-clear-probe", value: "b", created_by: "alice",
      meta: { expandable: false },
    }]);

    const { body } = await mockGet("/api/rooms/atlas-migration/memory/context/mock-clear-probe");
    expect((body as { expandable?: boolean }).expandable).toBe(false);
  });
});
