# Evaluation Results — Mycelium v1.0.13z

## What We Tested

- We ran a controlled A/B study across 14 decision scenarios: the same agents, the same personas, the same goals — first without Mycelium, then with it — measuring consensus rate, outcome quality, and token cost against a withheld ground-truth benchmark.
- Scenarios ranged from routine coordination (scheduling, expense approval, travel planning) to high-stakes decisions (AI deployment policy, data architecture, security trade-offs), testing whether the protocol holds across both everyday and adversarial conditions.

## Results

- **Agreement rate:** 93% of sessions ended in consensus with Mycelium mediation (13/14), compared to 36% without (5/14). The clearest result came from the high-stakes scenarios: five contested organizational policy decisions where unstructured agent chat produced zero decisions, and Mycelium produced five — each scored against a ground-truth benchmark the agents never saw.
- **Quality of outcome:** Mycelium-mediated sessions surfaced 92% of the canonical decision dimensions versus 75% in unstructured chat. On the high-stakes scenarios, outcome quality scored 4.6/5 against the withheld benchmark, compared to 1/5 without the protocol.
- **Derailment rate:** 22% of unmediated sessions were derailed by agents hallucinating protocol behavior they couldn't actually execute. 0% of Mycelium-mediated sessions produced off-protocol behavior. *(Measured at session level across the standard scenarios; turn-level analysis not yet run.)*
- **Token cost:** ~32,300 tokens per session on average with Mycelium mediation, compared to ~19,700 without — a 64% overhead per session, offset by the elimination of inconclusive runs that require human re-intervention. *(High-stakes scenarios only; per-session before/after token splits are not available for the standard scenarios.)*

## Methodology

Each scenario was run twice under identical conditions — same agents, same personas, same goals — once without Mycelium (unstructured multi-turn chat) and once with Mycelium's CognitiveEngine mediating structured proposal/response/accept rounds. Outcomes were compared against a set of canonical issues and policy options defined per scenario before the experiments ran, withheld from agents during negotiation and used for post-hoc scoring only.

**Model:** Claude Haiku (Bedrock)

**Scenario breakdown:**

| Series | Scenarios | Domain |
|---|---|---|
| Standard | Email automation, inbox workflow, personal planning, travel planning, healthcare treatment (NSCLC), expense submission, investment portfolio, supply chain stockout, CI/CD release | Operations, finance, healthcare |
| High-stakes | AI model deployment policy, data platform architecture, open source vs. enterprise tooling, remote work and talent strategy, security vs. developer experience | Organizational policy |

**Agents:** Standard scenarios used domain-specific personas; high-stakes scenarios used generic default-profile agents (cost-conscious, quality-focused, pragmatic) to test whether the protocol could produce quality outcomes independent of specialist persona knowledge.

**Total data:** ~383,000 input tokens of negotiation data across 14 scenarios.

## Notes and Caveats

- **The CI/CD release scenario** ended in structured impasse rather than consensus — intentionally. The Mycelium protocol correctly identified an undecidable conflict (the deploy agent rejected consensus three times, seeking deployment regardless of error-rate conditions) and escalated for human judgment rather than forcing false agreement. This is counted as a non-consensus outcome in the agreement rate above, but is considered a correct protocol result.
- **Issue coverage** shows a structural tradeoff worth understanding. "Issues" here means the distinct dimensions agents need to agree on — in a travel planning scenario, for example: flight class, hotel standard, daily pace, budget. Unstructured chat tends to identify the right issues at a high level but collapses related ones together. Mycelium breaks each issue into its component positions, which is why coverage rises to 92% — but also why it generates more issues than the benchmark expects. The extra issues are real negotiation positions, not noise.
- **High-stakes scenario token counts** vary significantly: one scenario reached consensus in a single round (producing far fewer tokens than the unmediated run), while another cycled over 16 rounds due to genuine value conflicts between agents. The per-session average reflects this variance.
