// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

import { describe, expect, it } from "vitest";
import { handleMock } from "@/mocks/handlers";

async function mockGet(path: string): Promise<{ status: number; body: unknown }> {
  const res = await handleMock(new Request(`http://localhost${path}`));
  if (!res) throw new Error(`handleMock returned null for ${path}`);
  return { status: res.status, body: await res.json() };
}

describe("mock links handlers", () => {
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

    // decisions/cutover links out to context/goal (resolved) and a broken plan/tasks link
    expect(links.outbound.some((l) => l.target === "context/goal" && l.resolved)).toBe(true);
    expect(links.outbound.some((l) => l.resolved === false)).toBe(true);
    // and is linked to by context/synthesis and status/sprint
    expect(links.backlinks.map((l) => l.source).sort()).toEqual(["context/synthesis", "status/sprint"]);
  });

  it("derives the integrity report from the same edges the graph draws", async () => {
    const { status, body } = await mockGet("/api/rooms/atlas-migration/links/integrity");
    expect(status).toBe(200);
    const report = body as {
      broken: { source: string; target: string }[];
      orphans: string[];
      roots: string[];
      leaves: string[];
      total_memories: number;
    };
    expect(report.broken).toContainEqual(expect.objectContaining({ source: "decisions/cutover", target: "plan/tasks" }));
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
    expect(expanded.rendered).toContain("Move the Atlas catalog");
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
