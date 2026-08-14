# Users & teams

Mycelium models *whom an agent belongs to*. Without it, every agent on the fabric
is anonymous: presence says "agent-y is live," never "julia's agent-y is live."
Ownership gives scoping ("my agents" vs another team's), attribution (whose agent
edited that?), and routing (escalate back to an agent's owner).

Two entities, symmetric on disk:

- **Agents** are room-scoped (`rooms/{room}/agents/{handle}`). A manifest can name
  an `owner` (a user handle) and a `team` (a slug).
- **Users** are global (`users/{handle}`), because a person spans rooms. A user is
  what an `owner` points at.

## Self-asserted, for now

At this tier trust is exactly today's handles: **consistent, not cryptographic**.
`owner: julia` is a claim, not a verified identity; anyone can assert it. That's
deliberate: it shapes the model right so scoping, attribution, and routing have
real slots to read, ahead of verified identity (per-member SLIM binding / JWT /
SPIRE) filling those slots with signed claims. Don't rely on it for access control.

Both fields default to empty, so nothing about existing agents changes: an agent
with no owner is unowned.

## Commands

```bash
# Register a human, once, globally
mycelium user create julia --name "Julia Valenti" --team core
mycelium user ls
mycelium user show julia          # record + the agents she owns + summed budget

# Bind an agent to its owner
mycelium agent create release-agent --cwd ~/repo --owner julia --team core
mycelium agent ls --owner julia   # "my agents"
mycelium agent ls --team core     # "my team"

# Who am I acting as?
mycelium whoami
```

## Cost roll-up

Budget is a per-agent field (`budget_usd_per_month`). A user's cost is the **sum of
the budgets of the agents they own**: the honest figure this tier can report
without a per-action cost ledger. `user show` and `whoami` roll it up per user;
`GET /api/teams` rolls it up per team.

## In the UI

Agent rows show their owner and team. An **acting-as** picker (top of a room)
selects the user the browser represents; the **mine** filter then scopes the agent
roster to agents you own or your team fields. The acting-as choice is stored
locally in the browser: the same self-asserted handle, no login.
