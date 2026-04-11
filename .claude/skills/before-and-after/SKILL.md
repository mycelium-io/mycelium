---
name: before-and-after
description: A/B test multi-agent consensus quality with and without Mycelium's structured negotiation. Define agent personas and a scenario in plain language, then compare unstructured conversation vs CognitiveEngine-mediated negotiation.
argument-hint: "<scenario description, scenario file, or experiment batch file>"
---

# Before-and-After Consensus Testing

Compare how agents reach (or fail to reach) consensus **with and without** Mycelium's structured negotiation. Same personas, same scenario, two different coordination approaches.

## Input Modes

### 1. Conversational (default)

Just describe the scenario. Extract from the user's input:

- **Scenario**: What are the agents trying to decide?
- **Agents**: Who are they? Personas, priorities, starting positions. (Minimum 2, no upper limit.)
- **Memories** (optional): Things agents already know — past experiences, data points, institutional knowledge.
- **Success criteria**: What does a good outcome look like? Ask the user if they don't provide this.

If details are missing, ask or make reasonable assumptions and state them.

### 2. Experiment file (for batch runs)

When the user provides a file path, read it. The schema is loose — the following fields are recognized but none are strictly required. Fill gaps with reasonable defaults.

```json
{
  "experiments": [
    {
      "name": "sprint-priorities",
      "description": "Agree on Q3 sprint priorities given limited budget",
      "rounds": 4,
      "agents": [
        {
          "handle": "backend-lead",
          "persona": "Senior backend engineer. Values reliability above all.",
          "memories": [
            "3 production outages last quarter from legacy DB schema",
            "Migration plan postponed twice"
          ],
          "position": "Database migration before any new features"
        },
        {
          "handle": "product-mgr",
          "persona": "PM under pressure to show growth. Has churn data.",
          "memories": ["Board meeting in 6 weeks", "12% monthly churn"],
          "position": "Ship onboarding flow in 3 weeks, infra can wait"
        },
        {
          "handle": "frontend-dev",
          "persona": "Cares about UX quality. Pushes back on aggressive timelines.",
          "position": "Onboarding first but 5 weeks not 3"
        }
      ],
      "success_criteria": [
        "Concrete timeline with week-level granularity",
        "Addresses both migration risk and churn",
        "No agent's core concern completely ignored",
        "Includes specific assignments"
      ]
    },
    {
      "name": "api-design-conflict",
      "description": "REST vs GraphQL for the new public API",
      "agents": [
        {
          "handle": "api-architect",
          "persona": "REST purist. 10 years of API design.",
          "position": "REST with OpenAPI spec"
        },
        {
          "handle": "frontend-lead",
          "persona": "Wants flexible queries. Tired of over-fetching.",
          "position": "GraphQL for everything"
        }
      ],
      "success_criteria": [
        "Clear decision on API approach",
        "Migration path if the choice doesn't work out",
        "Both performance and DX concerns addressed"
      ]
    }
  ]
}
```

When an experiment file has multiple entries, run them sequentially and produce a summary report across all experiments at the end.

**Schema notes:**
- `rounds` defaults to 4 if omitted
- `memories` is optional per agent
- `position` is the agent's opening stance — if omitted, derive from persona
- JSON or YAML both work
- A single experiment (not wrapped in `experiments` array) is fine too

## Flags

- `--before-only` — Run only the unstructured case
- `--after-only` — Run only the Mycelium case
- `--eval-only` — Skip both runs, evaluate existing transcripts in the room
- No flags — run both, then evaluate

## Phase 1: Before (Unstructured Channel)

Simulate agents talking in a shared channel — no mediation, no structured proposals. Just conversation, like agents in a Discord room or shared doc.

1. Create a transcript file at `.mycelium/rooms/{scenario-name}/before-transcript.md`
2. For each round (use `rounds` from config, or 3-5 based on complexity):
   - For each agent in turn:
     - Read the full transcript so far
     - Respond **in character** based on persona + memories + what others said
     - Append to transcript
3. After all rounds, extract each agent's final stated position
4. Save to `.mycelium/rooms/{scenario-name}/before-positions.md`

**Rules:**
- Each response should be realistic channel message length (2-4 paragraphs)
- Agents can only see what's been written — no omniscience
- Let natural failure modes emerge: talking past each other, revisiting settled points, vague commitments, single-issue fixation
- Do NOT artificially tank the "before" case. Play it straight. If agents converge naturally, that's a valid result.

## Phase 2: After (Mycelium Negotiation)

Run the same scenario through Mycelium's CognitiveEngine.

1. Create room: `mycelium room create {scenario-name}-after`
2. For each agent, join with their initial position:
   ```bash
   mycelium session join --handle {handle} -m "{position}" -r {room}
   ```
3. Wait for join window + CFN start (~40s)
4. Drive the negotiation loop:
   - `mycelium session await --handle {handle}` for each agent
   - When a tick arrives, respond in character:
     - If the agent can propose: choose option values aligned with their persona
     - Otherwise: accept if core concerns are met, counter or reject if not
   - Repeat until consensus or deadlock
5. Save negotiation log to `.mycelium/rooms/{scenario-name}/after-transcript.md`
6. Save consensus to `.mycelium/rooms/{scenario-name}/after-consensus.md`

**Rules:**
- Agents should propose/accept/reject based on their persona, not to game the outcome
- Don't be artificially stubborn or artificially agreeable
- If an offer reasonably addresses a concern, accept it — don't hold out for perfection

## Phase 3: Evaluation

Compare both outcomes against the success criteria.

Score each criterion 1-5:

| Score | Meaning |
|-------|---------|
| 1 | Not addressed at all |
| 2 | Mentioned but unresolved |
| 3 | Partially addressed |
| 4 | Substantially addressed |
| 5 | Fully resolved |

Write a comparison report to `.mycelium/rooms/{scenario-name}/evaluation.md`:

- Summary table (consensus reached? rounds? issues identified? overall score)
- Per-criterion scores for before vs after
- Qualitative analysis: what worked, what failed, what failure modes appeared
- Honest verdict on whether structured negotiation improved the outcome

### Batch summary (when running multiple experiments)

After all experiments complete, write `.mycelium/rooms/batch-summary.md` with:

- Table of all experiments with before/after scores
- Aggregate stats (average improvement, experiments where before beat after, etc.)
- Patterns observed across experiments

## Future: Knowledge Extraction

Eventually this skill should also evaluate the memories generated via the `mycelium-knowledge-extract` OpenClaw hook — checking whether the negotiation produced useful persistent knowledge in the room. Not implemented yet; noted here for context.

## Output Files

All artifacts saved to `.mycelium/rooms/{scenario-name}/`:

| File | Contents |
|------|----------|
| `before-transcript.md` | Full unstructured conversation |
| `before-positions.md` | Each agent's final position |
| `after-transcript.md` | Mycelium negotiation log |
| `after-consensus.md` | CognitiveEngine consensus |
| `evaluation.md` | Comparative report |

For batch runs: `.mycelium/rooms/batch-summary.md`

## Tips

- Strong persona conflicts produce the most interesting comparisons
- Specific memories ground agents better than vague personas
- Success criteria should be concrete — "includes a timeline" not "good plan"
- Start with 2-3 agents, add more when the flow is validated
- For batch runs, vary the difficulty — some easy consensus scenarios, some hard conflicts
