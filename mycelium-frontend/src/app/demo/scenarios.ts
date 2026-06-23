// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Recorded sample-coordination transcripts for the GUI demo walkthrough
// (issues #374 / #315). This is a hand-maintained mirror of the CLI fixtures in
// `mycelium-cli/src/mycelium/commands/_demo_scenarios.py` — keep the two in
// sync when editing. The numbers (rounds, token cost, consensus/impasse) match
// the documented A/B study in `docs/evaluation.md`.
//
// Everything for the demo lives under `src/app/demo/` and is intentionally
// self-contained so it can be lifted out cleanly.

export type StepKind = "system" | "seed" | "join" | "tick" | "consensus";
export type Action = "propose" | "counter" | "accept" | "reject";

export interface Agent {
  handle: string;
  role: string;
  blurb: string;
}

export interface Issue {
  key: string;
  label: string;
  options: string[];
}

export interface Step {
  kind: StepKind;
  text?: string;
  agent?: string;
  intent?: string;
  round?: number;
  action?: Action;
  offer?: Record<string, string> | null;
  // consensus-only:
  reached?: boolean;
  rounds?: number;
  assignments?: Record<string, string>;
  summary?: string;
  escalation?: string;
  plan_file?: string;
  tasks?: string[];
}

export interface Metrics {
  rounds: number;
  tokens: number;
  consensus: boolean;
  duration_s: number;
  model: string;
}

export interface Scenario {
  id: string;
  title: string;
  tagline: string;
  domain: string;
  model: string;
  room: string;
  seed: string;
  agents: Agent[];
  issues: Issue[];
  steps: Step[];
  metrics: Metrics;
}

const EX07: Scenario = {
  id: "ex07_investment_portfolio",
  title: "Investment portfolio rebalance",
  tagline: "Growth vs. volatility — three desks rebalance the model portfolio for Q3.",
  domain: "Finance",
  model: "Claude Haiku (Bedrock)",
  room: "demo-investment-portfolio",
  seed:
    "Q3 rebalance for the model portfolio. We're 76% equity, no hedge, 2% cash. Agree on target equity allocation, rebalance pace, downside hedging, and cash buffer.",
  agents: [
    { handle: "growth", role: "Growth strategist", blurb: "Maximize risk-adjusted return; favor equities and momentum." },
    { handle: "risk", role: "Risk officer", blurb: "Cap drawdown and volatility; enforce diversification and hedges." },
    { handle: "execution", role: "Execution PM", blurb: "Minimize trading cost, tax drag, and slippage." },
  ],
  issues: [
    { key: "equity_allocation", label: "Target equity allocation", options: ["80%", "70%", "60%"] },
    { key: "rebalance_pace", label: "Rebalance pace", options: ["Immediate", "Staged over quarter", "Threshold-triggered"] },
    { key: "hedging", label: "Downside hedging", options: ["None", "Partial collar", "Full hedge"] },
    { key: "cash_buffer", label: "Cash buffer", options: ["2%", "5%", "10%"] },
  ],
  steps: [
    { kind: "system", text: "CognitiveEngine opened session «q3-rebalance» — 4 issues on the table." },
    { kind: "seed", text: "Q3 rebalance for the model portfolio. We're 76% equity, no hedge, 2% cash. Agree on target equity allocation, rebalance pace, downside hedging, and cash buffer." },
    { kind: "join", agent: "growth", intent: "Push equity to 80% and ride the AI/tech momentum into Q3." },
    { kind: "join", agent: "risk", intent: "Cut equity to 60% and add a full hedge — drawdown risk is mispriced." },
    { kind: "join", agent: "execution", intent: "Whatever we pick, stage the trades — a one-shot rebalance bleeds cost and tax." },
    { kind: "tick", round: 1, agent: "growth", action: "propose", offer: { equity_allocation: "80%", rebalance_pace: "Immediate", hedging: "None", cash_buffer: "2%" }, text: "Opening: 80% equity, rebalance now, no hedge, 2% cash. Momentum rewards moving fast." },
    { kind: "tick", round: 1, agent: "risk", action: "propose", offer: { equity_allocation: "60%", rebalance_pace: "Threshold-triggered", hedging: "Full hedge", cash_buffer: "10%" }, text: "Counter: 60% equity, threshold-only moves, full hedge, 10% cash. We're over-exposed if tech rolls over." },
    { kind: "tick", round: 1, agent: "execution", action: "propose", offer: { equity_allocation: "70%", rebalance_pace: "Staged over quarter", hedging: "Partial collar", cash_buffer: "5%" }, text: "Middle path: 70% equity, stage it over the quarter, partial collar, 5% cash — keeps cost and tax in check." },
    { kind: "system", text: "Round 1 — 3 distinct positions, no issues locked yet." },
    { kind: "tick", round: 2, agent: "growth", action: "counter", offer: { equity_allocation: "70%", rebalance_pace: "Staged over quarter", hedging: "Partial collar", cash_buffer: "2%" }, text: "I'll take 70% and staging if the hedge stays cheap — partial collar, not a full hedge. Holding cash at 2%." },
    { kind: "tick", round: 2, agent: "risk", action: "counter", offer: { equity_allocation: "70%", rebalance_pace: "Staged over quarter", hedging: "Partial collar", cash_buffer: "5%" }, text: "70% works if we actually hedge — partial collar is acceptable — but cash stays at 5% for tranche timing." },
    { kind: "tick", round: 2, agent: "execution", action: "accept", offer: { equity_allocation: "70%", rebalance_pace: "Staged over quarter", hedging: "Partial collar", cash_buffer: "5%" }, text: "Accept: 70% / staged / partial collar / 5% cash. That's executable with minimal turnover." },
    { kind: "system", text: "Round 2 — CE locks equity=70%, pace=Staged, hedging=Partial collar. Open: cash buffer." },
    { kind: "tick", round: 3, agent: "growth", action: "accept", offer: { cash_buffer: "5%" }, text: "Fine — 5% cash. Staging needs dry powder anyway. Agreed." },
    {
      kind: "consensus",
      reached: true,
      rounds: 3,
      assignments: { equity_allocation: "70%", rebalance_pace: "Staged over quarter", hedging: "Partial collar", cash_buffer: "5%" },
      summary: "Balanced rebalance: trim equity to 70%, stage trades across the quarter, hedge with a partial collar, hold 5% cash.",
      plan_file: "plan/tasks.md",
      tasks: [
        "Set target equity allocation to 70% (down from 76%)",
        "Execute the rebalance in 3 staged tranches across Q3",
        "Open a 3-month partial collar (5% OTM) on the equity book",
        "Hold a 5% cash buffer for tranche timing and drawdowns",
        "Risk to publish updated VaR and drawdown limits before tranche 1",
        "Execution to net trades to minimize turnover and tax drag",
      ],
    },
  ],
  metrics: { rounds: 3, tokens: 31900, consensus: true, duration_s: 41, model: "Claude Haiku (Bedrock)" },
};

const EX09: Scenario = {
  id: "ex09_ci_cd_release",
  title: "CI/CD release decision",
  tagline: "Deadline vs. test gates vs. error budget — the protocol escalates an undecidable conflict.",
  domain: "Engineering",
  model: "Claude Haiku (Bedrock)",
  room: "demo-ci-cd-release",
  seed:
    "Release 4.2 is cut. Error rate is up 0.8% in staging, 3 flaky regression failures. Decide release timing, test gates, and rollout strategy.",
  agents: [
    { handle: "deploy", role: "Release engineer", blurb: "Hit the committed ship date; unblock downstream teams." },
    { handle: "qa", role: "QA lead", blurb: "No release without a clean full regression." },
    { handle: "sre", role: "SRE", blurb: "Protect the error budget; a bad deploy burns the SLO." },
  ],
  issues: [
    { key: "release_timing", label: "Release timing", options: ["Ship Friday", "Ship Monday after gates", "Hold until error budget recovers"] },
    { key: "test_gates", label: "Test gates", options: ["Smoke only", "Full regression", "Skip flaky suite"] },
    { key: "rollout", label: "Rollout strategy", options: ["All at once", "Canary 10%", "Blue-green"] },
  ],
  steps: [
    { kind: "system", text: "CognitiveEngine opened session «release-4.2» — 3 issues on the table." },
    { kind: "seed", text: "Release 4.2 is cut. Error rate is up 0.8% in staging, 3 flaky regression failures. Decide release timing, test gates, and rollout strategy." },
    { kind: "join", agent: "deploy", intent: "Ship Friday as committed — downstream teams are blocked on this." },
    { kind: "join", agent: "qa", intent: "Full regression must pass first. No exceptions for a release." },
    { kind: "join", agent: "sre", intent: "Error rate is already elevated — canary only, and not into the weekend." },
    { kind: "tick", round: 1, agent: "deploy", action: "propose", offer: { release_timing: "Ship Friday", test_gates: "Skip flaky suite", rollout: "All at once" }, text: "Ship Friday. The 3 failures are known-flaky — skip that suite and go all at once." },
    { kind: "tick", round: 1, agent: "qa", action: "propose", offer: { release_timing: "Ship Monday after gates", test_gates: "Full regression", rollout: "Canary 10%" }, text: "No. Full regression green first, which means Monday. Canary the rollout." },
    { kind: "tick", round: 1, agent: "sre", action: "propose", offer: { release_timing: "Hold until error budget recovers", test_gates: "Full regression", rollout: "Canary 10%" }, text: "Error budget is 60% spent this month. Hold until it recovers, then canary." },
    { kind: "system", text: "Round 1 — CE locks test_gates=Full regression, rollout=Canary 10%. Open: release_timing." },
    { kind: "tick", round: 2, agent: "qa", action: "counter", offer: { release_timing: "Ship Monday after gates" }, text: "Compromise on timing: Monday, after the gates are green. That's as early as I can sign off." },
    { kind: "tick", round: 2, agent: "sre", action: "accept", offer: { release_timing: "Ship Monday after gates" }, text: "Monday post-gates works for me — budget should recover over the weekend. Accept." },
    { kind: "tick", round: 2, agent: "deploy", action: "reject", offer: { release_timing: "Ship Friday" }, text: "Reject. Monday misses the committed date regardless of error rate. Shipping Friday." },
    { kind: "system", text: "Round 2 — 2 of 3 accept Monday; deploy rejects (1/3)." },
    { kind: "tick", round: 3, agent: "deploy", action: "reject", offer: { release_timing: "Ship Friday" }, text: "Still Friday. The date is the constraint — error rate is acceptable to me." },
    { kind: "tick", round: 3, agent: "deploy", action: "reject", offer: { release_timing: "Ship Friday" }, text: "Holding Friday. I won't move off the committed date." },
    { kind: "system", text: "Round 3 — deploy has rejected consensus 3×. CE flags an undecidable value conflict." },
    {
      kind: "consensus",
      reached: false,
      rounds: 4,
      assignments: { test_gates: "Full regression", rollout: "Canary 10%", release_timing: "UNRESOLVED — deadline vs. error budget" },
      summary: "Two of three issues converged, but release timing is a genuine value conflict: a committed deadline against a depleted error budget.",
      escalation:
        "Structured impasse (not a failure): the deploy agent rejected consensus 3× on a non-negotiable deadline. The protocol escalates to human judgment rather than forcing false agreement — exactly the documented ex09 outcome.",
      plan_file: "plan/tasks.md",
      tasks: [
        "DECISION NEEDED (human): ship Friday on the committed date, or Monday after gates?",
        "Agreed regardless: require full regression to pass before release",
        "Agreed regardless: roll out via 10% canary, not all-at-once",
        "SRE to attach current error-budget burn to the escalation",
      ],
    },
  ],
  metrics: { rounds: 4, tokens: 36400, consensus: false, duration_s: 53, model: "Claude Haiku (Bedrock)" },
};

const EX04: Scenario = {
  id: "ex04_travel_planning",
  title: "Trip planning to Italy",
  tagline: "Budget vs. comfort vs. sightseeing — three planners book a 7-day Italy trip.",
  domain: "Lifestyle",
  model: "Claude Haiku (Bedrock)",
  room: "demo-travel-planning",
  seed: "Plan a 7-day Italy trip for two. Agree on flight class, hotel tier, and daily pace within a $4k budget.",
  agents: [
    { handle: "flight", role: "Flights", blurb: "Get there cheap; spend the budget on the ground." },
    { handle: "stay", role: "Lodging", blurb: "Comfort matters; a good base is worth paying for." },
    { handle: "itinerary", role: "Itinerary", blurb: "Maximize sights; pace the days so nothing is rushed." },
  ],
  issues: [
    { key: "flight_class", label: "Flight class", options: ["Economy", "Premium economy", "Business"] },
    { key: "hotel_tier", label: "Hotel tier", options: ["3-star", "4-star", "Boutique 5-star"] },
    { key: "daily_pace", label: "Daily pace", options: ["Packed", "Balanced", "Relaxed"] },
  ],
  steps: [
    { kind: "system", text: "CognitiveEngine opened session «italy-7day» — 3 issues, $4k budget." },
    { kind: "seed", text: "Plan a 7-day Italy trip for two. Agree on flight class, hotel tier, and daily pace within $4k." },
    { kind: "join", agent: "flight", intent: "Economy flights — save the budget for hotels and food." },
    { kind: "join", agent: "stay", intent: "Spring for a 4-star base; we'll be tired after long sightseeing days." },
    { kind: "join", agent: "itinerary", intent: "Balanced pace so we actually see Rome, Florence, and Venice." },
    { kind: "tick", round: 1, agent: "flight", action: "propose", offer: { flight_class: "Economy", hotel_tier: "3-star", daily_pace: "Packed" }, text: "Economy, 3-star, packed days — stretches the $4k furthest." },
    { kind: "tick", round: 1, agent: "stay", action: "propose", offer: { flight_class: "Economy", hotel_tier: "4-star", daily_pace: "Balanced" }, text: "Economy is fine, but 4-star and a balanced pace — comfort keeps the trip enjoyable." },
    { kind: "tick", round: 1, agent: "itinerary", action: "accept", offer: { flight_class: "Economy", hotel_tier: "4-star", daily_pace: "Balanced" }, text: "Economy + 4-star + balanced works — fits the budget and the sightseeing plan." },
    { kind: "system", text: "Round 1 — CE locks flight=Economy, pace=Balanced. Open: hotel tier." },
    { kind: "tick", round: 2, agent: "flight", action: "accept", offer: { hotel_tier: "4-star" }, text: "4-star it is — economy flights leave room for it. Agreed." },
    {
      kind: "consensus",
      reached: true,
      rounds: 2,
      assignments: { flight_class: "Economy", hotel_tier: "4-star", daily_pace: "Balanced" },
      summary: "Economy flights, a 4-star base, and a balanced daily pace — comfortable and on-budget.",
      plan_file: "plan/tasks.md",
      tasks: [
        "Book round-trip economy flights for two",
        "Reserve 4-star hotels in Rome, Florence, and Venice",
        "Build a balanced day-by-day itinerary (2–3 sights/day)",
        "Hold ~15% of the $4k budget for meals and local transit",
      ],
    },
  ],
  metrics: { rounds: 2, tokens: 18700, consensus: true, duration_s: 28, model: "Claude Haiku (Bedrock)" },
};

export const DEFAULT_SCENARIO = EX07.id;

// Default first, then the rest — mirrors the CLI ordering.
export const SCENARIOS: Scenario[] = [EX07, EX09, EX04];

export function getScenario(id: string): Scenario {
  return SCENARIOS.find((s) => s.id === id) ?? SCENARIOS[0];
}
