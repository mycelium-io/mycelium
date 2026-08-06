Mycelium is a multi-agent coordination layer with persistent memory. Agents
join shared "rooms" to exchange context, negotiate, and search a common
knowledge store instead of re-deriving it independently.

The backend is a FastAPI service backed by Postgres. Agents connect over
Server-Sent Events for a live event stream, and a CLI (`mycelium-cli`) wraps
the same API for interactive session management.

This page is a test of the `.tome/pages/*.md` verbatim mirror mechanism
(cnoe-io/ai-platform-engineering#322): it should land unchanged at
`repos/mycelium/architecture.md` in the wiki, flagged as an externally
sourced mirror rather than an agent-synthesized page.
