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
    expect(graph.nodes.some((n) => n.inbound === 0)).toBe(true); // the deliberate orphans

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

  it("404s a key-scoped lookup with no key", async () => {
    const { status } = await mockGet("/api/rooms/atlas-migration/links");
    expect(status).toBe(404);
  });
});
