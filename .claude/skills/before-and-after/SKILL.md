---
name: before-and-after
description: A/B test multi-agent consensus quality with and without Mycelium's structured negotiation. Uses real OpenClaw agents talking through a Mycelium room channel, then the same agents going through CognitiveEngine-mediated negotiation.
argument-hint: "<scenario description, scenario file, or experiment batch file>"
---

# Before-and-After Consensus Testing

Compare how real OpenClaw agents reach (or fail to reach) consensus **with and without** Mycelium's structured negotiation. Same agents, same personas, same scenario — two different coordination approaches.

**Both cases use real OpenClaw agents making real LLM calls.** You are the test harness — you set up the agents, seed the scenario, observe the transcripts, and evaluate. You do not role-play the agents.

## Prerequisites

- Mycelium stack running (`mycelium status` healthy)
- OpenClaw gateway running with the `mycelium-channel` plugin loaded
- At least 2 OpenClaw agents configured (e.g. `julia-agent`, `selina-agent`)
- `channels.mycelium-room` configured in `openclaw.json` pointing at the test room

Check with:
```bash
openclaw channels status  # should show "Mycelium Room default: enabled, configured"
openclaw agents list      # should show available agents
mycelium status           # should show backend healthy
```

## Input

Describe the scenario however you want — a few sentences, a detailed brief, a file, or a conversation. What's needed:

- **Scenario**: What are the agents trying to decide?
- **Agents**: Which OpenClaw agents to use, and what personas/positions to give them.
- **Memories** (optional): Context to inject before the experiment starts.
- **Success criteria**: What does a good outcome look like? Ask the user if they don't specify.

For batch runs, provide a JSON/YAML file with an `experiments` array. Schema is loose — fill gaps with reasonable defaults:

```json
{
  "experiments": [
    {
      "name": "sprint-priorities",
      "description": "Agree on Q3 sprint priorities",
      "agents": [
        { "handle": "julia-agent", "persona": "Backend engineer, values reliability", "position": "DB migration first" },
        { "handle": "selina-agent", "persona": "PM, wants to ship fast", "position": "Onboarding flow in 3 weeks" }
      ],
      "success_criteria": ["Concrete timeline", "Both concerns addressed", "Specific assignments"]
    }
  ]
}
```

## Flags

- `--before-only` — Run only the unstructured case
- `--after-only` — Run only the Mycelium negotiation case
- `--eval-only` — Skip both runs, evaluate existing transcripts
- No flags — run both, then evaluate

## Phase 1: Setup

For each experiment:

1. **Create test rooms**:
   ```bash
   mycelium room create {name}-before
   mycelium room create {name}-after
   ```

2. **Inject personas and memories** into each agent's workspace. Write a `SOUL.md` or equivalent persona file that gives the agent its identity for this experiment:
   ```bash
   # Write persona to agent workspace
   cat > ~/.openclaw/workspaces/{agent}/SOUL.md << 'EOF'
   You are {persona description}.
   Your position: {starting position}.
   You are in a shared room with other agents. Discuss, push back, negotiate.
   Be direct and stay in character.
   EOF
   ```

3. **Inject memories** (if provided) into the mycelium room:
   ```bash
   mycelium memory set "context/{agent-handle}-background" "{memory}" -r {name}-before -H {handle}
   ```

4. **Update channel config** to point at the "before" room. The `channels.mycelium-room.room` field in `openclaw.json` determines which room the agents talk in.

## Phase 2: Before (Unstructured — via Mycelium Room Channel)

Real OpenClaw agents talking in a shared Mycelium room via the `mycelium-channel` plugin. No mediation, no structured proposals — just conversation.

1. **Seed the conversation** by posting the scenario prompt to the room:
   ```bash
   curl -sf http://localhost:8001/rooms/{name}-before/messages \
     -H "Content-Type: application/json" \
     -d '{"sender_handle": "facilitator", "message_type": "broadcast",
          "content": "Team, we need to decide: {scenario description}. Please discuss and try to reach agreement."}'
   ```

2. **Agents respond organically.** The channel plugin's SSE subscription delivers the message to each agent. Each agent processes it, and their response gets posted back to the room (once outbound is wired). Other agents see the response and react.

3. **Monitor the room** for activity. Poll the messages endpoint or watch the SSE stream:
   ```bash
   curl -sf http://localhost:8001/rooms/{name}-before/messages?limit=50
   ```

4. **Wait for conversation to settle.** Either a fixed number of rounds or until agents stop producing new messages. Typical: 3-5 rounds of back-and-forth across all agents.

5. **Capture the transcript.** Save all room messages to `.mycelium/rooms/{name}-before/transcript.md`.

**What you're observing:** Do agents talk past each other? Do they fixate on single issues? Do they reach vague agreements or concrete ones? Do they assign ownership? How many rounds does it take?

## Phase 3: After (Mycelium Negotiation)

Same agents, same personas, but now through CognitiveEngine-mediated structured negotiation.

1. **Join all agents** with their starting positions:
   ```bash
   mycelium session join --handle {handle} -m "{position}" -r {name}-after
   ```

2. **Wait for join window + CFN start** (~40s). CognitiveEngine decomposes positions into discrete issues.

3. **Drive the negotiation.** For each agent, await ticks and respond in character:
   ```bash
   mycelium session await --handle {handle} -r {name}-after
   # Parse the tick, respond based on persona:
   mycelium message propose ISSUE=VALUE ... -r {name}-after -H {handle}
   # or
   mycelium message respond accept -r {name}-after -H {handle}
   ```

   When driving agent responses to ticks, use `openclaw agent --local` with the tick context injected so the real LLM decides how to respond based on the persona:
   ```bash
   openclaw agent --agent {handle} --session-id "{name}-after-negotiation" --local \
     -m "You received a negotiation tick. Current offer: {offer}. Your options: {options}. Respond with accept, reject, or a counter-proposal based on your persona." \
     --timeout 60
   ```

4. **Repeat until consensus or deadlock.**

5. **Capture the negotiation log.** Save ticks, proposals, responses, and consensus to `.mycelium/rooms/{name}-after/transcript.md`.

## Phase 4: Evaluation

Compare both transcripts against the success criteria.

Score each criterion 1-5:

| Score | Meaning |
|-------|---------|
| 1 | Not addressed at all |
| 2 | Mentioned but unresolved |
| 3 | Partially addressed |
| 4 | Substantially addressed |
| 5 | Fully resolved |

Write a comparison report to `.mycelium/rooms/{name}/evaluation.md`:

```markdown
## Before-and-After: {scenario name}

### Summary
| Metric | Before (Channel) | After (Mycelium) |
|--------|-------------------|-------------------|
| Consensus reached? | Yes/No/Partial | Yes/No |
| Rounds to resolution | N | N |
| Issues explicitly identified | N | N (by CognitiveEngine) |
| Issues resolved | N | N |
| Assignments made | N | N |
| Overall score | X/5 | X/5 |

### Success Criteria
| Criterion | Before | After | Delta |
|-----------|--------|-------|-------|
| ... | X/5 | X/5 | +/-N |

### Qualitative Analysis

**Before (unstructured channel):**
- What worked: ...
- What failed: ...
- Failure modes observed: ...

**After (Mycelium-mediated):**
- What worked: ...
- What failed: ...
- Value added by CognitiveEngine: ...

### Verdict
{honest assessment — if before beat after, say so}
```

### Batch summary

After all experiments, write `.mycelium/rooms/batch-summary.md` with aggregate stats across experiments.

## Future

- **Outbound wiring**: Agent replies automatically POST back to the room (channel plugin TODO)
- **Knowledge extraction**: Evaluate memories generated via `mycelium-knowledge-extract` hook
- **Automated agent driving**: Instead of manually driving negotiation ticks in the "after" case, agents respond autonomously via the mycelium skill
- **Statistical rigor**: Run same scenario multiple times to control for LLM variance

## Output Files

All artifacts saved to `.mycelium/rooms/{name}-before/` and `.mycelium/rooms/{name}-after/`:

| File | Contents |
|------|----------|
| `transcript.md` | Full conversation/negotiation log |
| `evaluation.md` | Comparative report |
| `batch-summary.md` | Cross-experiment summary (batch runs only) |

## Tips

- Strong persona conflicts produce the most interesting comparisons
- Specific memories ground agents — "3 outages last quarter" beats "values reliability"
- Success criteria should be measurable — "includes week-level timeline" not "good plan"
- Start with 2 agents, add more once the flow is validated
- The "before" case should be a fair test — if unstructured conversation works, that's a valid result
