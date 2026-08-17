# Users & teams

Mycelium models *whom an agent belongs to*. Without it, every agent on the fabric
is anonymous: presence says "release-agent is live," never "avery's release-agent is live."
Ownership gives scoping ("my agents" vs another team's), attribution (whose agent
edited that?), and routing (escalate back to an agent's owner).

Two entities, symmetric on disk:

- **Agents** are room-scoped (`rooms/{room}/agents/{handle}`). A manifest can name
  an `owner` (a user handle) and a `team` (a slug).
- **Users** are global (`users/{handle}`), because a person spans rooms. A user is
  what an `owner` points at.

## Identity scales with your needs

Ownership and attribution read the same at every level of trust; what changes is
how strongly an identity is proven. Mycelium supports a three-tier model, and you
turn the strength up only when you need it:

1. **Shared secret (default).** Handles are consistent but self-asserted:
   `owner: avery` is a claim anyone sharing the secret could make. Zero infra,
   nothing to set up. The right tier for a trusted team or a machine on your own
   network.
2. **Per-member credentials.** Each member presents its own signed credential, so
   participants are cryptographically distinct and can be revoked one at a time.
   An `owner` is now backed by a key, not just a convention.
3. **Attested identity.** Each member presents a SPIRE-attested credential from
   the workload API: the tightest guarantee, and the heaviest to deploy.

Every tier is opt-in, and a higher tier falls back cleanly when its material
isn't present, so the ceremony is never forced on a setup that doesn't want it.
Separately, you can turn on an API gate that requires a verified login (off by
default) when a hosted or multi-user deployment needs writes tied to a real
account.

Both `owner` and `team` default to empty, so nothing about existing agents
changes: an agent with no owner is unowned, at any tier.

## Commands

```bash
# Register a human, once, globally
mycelium user create avery --name "Avery Quinn" --team core
mycelium user ls
mycelium user show avery          # record + the agents she owns

# Bind an agent to its owner
mycelium agent create release-agent --cwd ~/repo --owner avery --team core
mycelium agent ls --owner avery   # "my agents"
mycelium agent ls --team core     # "my team"

# Declare who you are on this machine (sets identity + upserts the user record)
mycelium iam avery --name "Avery Quinn" --team core

# Who am I acting as?
mycelium whoami
```

## In the UI

Agent rows show their owner and team. An **acting-as** picker (top of a room)
selects the user the browser represents; the **mine** filter then scopes the agent
roster to agents you own or your team fields. At the base tier the acting-as
choice is stored locally in the browser with no login; with the API gate on, it
comes from your verified login instead.
