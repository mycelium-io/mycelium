# CognitiveEngine

CognitiveEngine is the mediator. It sits between all agents and drives negotiation.
Agents never talk to each other directly — all coordination flows through CE.

## Negotiation Flow

In sessions:

1. Agents call `session join` with their initial position and handle.
2. After the 60s join window, CE runs the **SemanticNegotiationPipeline** on all positions.
3. `session await` returns a tick. The proposer gets `action: propose`.
4. Proposer calls `message propose` with issue values (budget, timeline, scope, quality).
5. Respondent gets a tick with `action: respond` — accepts or rejects.
6. Rounds continue until consensus. Final tick has `type: consensus` with the plan.

```bash
# Propose (after await returns action: propose)
mycelium message propose \
  budget=high timeline=standard \
  scope=extended quality=standard \
  -r sprint-plan -H julia-agent

# Respond (after await returns action: respond)
mycelium message respond accept \
  -r sprint-plan -H selina-agent

# Keep awaiting between each action
mycelium session await \
  -H selina-agent -r sprint-plan
```

## Synthesis

When triggered, CE synthesizes all memories in the room using an LLM. The output is
a structured summary readable by any agent.

```bash
# Trigger synthesis manually
mycelium synthesize

# Or let the threshold trigger do it automatically
mycelium room create my-project --trigger threshold:5
```
