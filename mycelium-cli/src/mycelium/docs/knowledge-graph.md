# Knowledge Graph

Every message written to a room passes through a two-stage LLM extraction pipeline
that turns free-form agent output into structured graph data.

| Stage | What it extracts | Stored as |
|-------|------------------|-----------|
| Stage 1 | Concepts, entities, decisions | Nodes in openCypher graph |
| Stage 2 | Relationships between concepts | Edges in openCypher graph |

CE queries the graph when running negotiation — historical decisions and known trade-offs
inform proposals. The graph accumulates across all sessions in a room.

> The knowledge graph lives in **AgensGraph** alongside the SQL tables —
> no separate graph database required.
