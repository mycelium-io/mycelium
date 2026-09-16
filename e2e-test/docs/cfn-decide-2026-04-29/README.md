# CFN `/decide` latency investigation — snapshot 2026-04-29

This directory is a **point-in-time snapshot** of the CFN `/decide` latency
investigation as of 2026-04-29. It is intentionally date-stamped: the
underlying `ioc-cognition-fabric-node-svc` repository is being rewritten
from Python to Go (`ioc-cfn-svc`), and many of the call sites named
below — `litellm.acompletion`, `IngestionService`, the FastAPI
`BackgroundTask` ingest path, the AgensGraph save loop — will not exist
in the same shape (or at all) in the Go service.

Treat this as historical context for *why* the current Python service
behaves the way it does, not as a live design document for the
replacement.

## Contents

| File | Phase | What it is |
|---|---|---|
| `cfn_decide_investigation_history.md` | All (1–18) | Chronological narrative — start here |
| `cfn_decide_instrumentation_plan.md` | 2–6 | Final instrumentation shape (Sites 1–6) and PR plan |
| `cfn_decide_findings_report.md` | 11 | Top-level findings summary |
| `cfn_decide_tracing_payoff.md` | 7 | What the timing envelope bought us |
| `cfn_decide_pr_e_v2_results.md` | 12 | Sync embedding `to_thread` wrap |
| `cfn_decide_pr_e_v3_analysis.md` | 13 | Diagnosis of the BackgroundTask wedger |
| `cfn_decide_pr_e_v3_results.md` | 13 | Result of off-loading the BackgroundTask |
| `cfn_decide_pr_e_v4a_results.md` | 14 | The `litellm.acompletion` regression |
| `cfn_decide_pr_e_v4b_results.md` | 15 | Batched ONNX embeddings — partial relief |
| `cfn_decide_kxp_profile_results.md` | 16 | The AgensGraph red-herring kill |

## What's still useful past the Go rewrite

1. **The methodology** — outside-in instrumentation, hypothesis discipline,
   "always instrument the suspect before refactoring it" (the AgensGraph
   red-herring section in particular).
2. **The wedge-pattern taxonomy** (A loop-wedge / B accept-queue /
   C pool-starvation / D real-work). Independent of language; applies to
   any single-event-loop async service. Implemented in
   `tests/analyze_round_traces.py --wedges`.
3. **The trace plumbing on the Mycelium side** (`_RoundTrace`, the
   conftest hook, the analyzer). All of this works against any CFN that
   emits the `_timing` envelope, including a Go reimplementation.

## What will go stale

- Every named code path in `ioc-cognition-fabric-node-svc` (Python).
- The PR E v1 fix (`CFN_DEFAULT_EXECUTOR_WORKERS` bump) — Go has no
  GIL and no asyncio default executor.
- The `litellm.acompletion`-against-Bedrock counter-example in Phase 14.
- The `EmbeddingManager` / `fastembed` per-request instantiation
  problem.

When the Go CFN replacement lands, drop a sibling
`docs/cfn-decide-<yyyy-mm-dd>/` next to this one rather than editing
this snapshot. That keeps the historical reasoning verifiable.
