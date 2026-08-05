# START HERE — Post-smoke hardening

You are picking up the **SLIM-native rewrite** after its first full-stack smoke test. The
10-step build is done and merged on `slim-native-rewrite`; a real `claude` agent now wakes over
SLIM and replies. But the first full-stack run surfaced real fragility. **Your job: work the
post-smoke hardening queue so the system is reliable and *visibly* working** — not just
unit-green.

## Current status (2026-08-05) — H1–H4 DONE + pushed; only H5 left

Baseline fixes + **H1, H2, H3, H4 are complete, validated live, and pushed** to
`slim-native-rewrite` (10 commits, `1b36a79a`..`2e222d54`; backend + CLI gates green, 285
backend tests). Bible Part VII marks each done with what shipped.

- **Baseline** `1b36a79a` — the 6 smoke fixes (keepalive, benign receive-timeout, causal
  delivery, compose `SLIM_NODE_ENDPOINT`); node `log_level` reverted to `info`.
- **H1 obs** `f26ab6b3` — `/health.coordination` surface; silent failures → WARNING/ERROR.
- **H2 store** `2486a223`+`beff837a` — agent replies show in the UI; one-store/source-
  partitioned design (full single-writer migration explicitly ruled out — see bible H2).
- **H3 lifecycle** `698a991b`+`d4972ac1` — startup re-provision + idempotent create; presence
  tracking; supervised persister. Survives backend restart AND a 40s node outage.
- **H4 footguns** `e8fee00a`+`9768b4ec`+`2e222d54` — **clean single-shot invoke→wake→reply**
  (§E+§G), daemon singleton lock (§H), §I resolved-by-composition.

**The headline to build on:** one `mycelium agent invoke` of a user's own agent now
auto-joins it (no consent), wakes it on the first mention, and its reply lands in the room —
end to end, reliably.

**Remaining: H5 only** — prove Rung 4 (`aligner → commit:converged → plan/tasks.md compiles →
memory syncs`) with real agents. Unstarted. Recommended first step: scout
`app/services/aligner.py`, `plan_compiler.py`, `plan_sync.py` and lay out the multi-agent test
before running (it uses real LLM tokens). The single-shot flow above is the foundation to drive it.

## Read first, in order
1. **`docs/SLIM_SMOKE_TEST_FINDINGS.md`** — what broke, what was fixed, what's still open, with
   repro. This is the ground truth of where things actually stand.
2. **`docs/slim-native-rebuild-bible.md` → Part VII (Post-smoke hardening)** — the prioritized
   plan (H1–H5) with the decisions already made. Part IV = debt register (D1–D12); Part III =
   repo map; Part VI = SLIM quickstart.

## Ground rules
- **Branch:** `slim-native-rewrite` (`git checkout slim-native-rewrite`) — NOT `main`.
- **The smoke test left uncommitted fixes in the working tree** (~8 files: `main.py`,
  `l9_slim.py`, `persister.py`, `slim_client.py`, `connector.py`, `slim/client.py`, both compose
  files). Confirm with `git status`. **Commit those first** — they're the 6 real bug fixes,
  tests green — **except revert the node `tracing.log_level: debug` → `info` in `compose.yml`**
  (diagnostic only; see Findings Part 4). The `SLIM_NODE_ENDPOINT` addition in that same file is
  a real fix — keep it.
- **Work H1 → H5 in order.** H1 (observability) is first on purpose: every smoke bug was silent
  (DEBUG/swallowed), so loud failures + a health surface turn every later bug from a 3-hour hunt
  into a 20-minute fix.
- **Decisions are already made — don't relitigate:** §A = **option (b)** (persister is the
  single writer of a room's messages); §G = fix the consent **model** (a user's own registered
  agents skip consent; consent is for foreign/cross-host invites only) — **not** a new CLI
  command.
- **Validate, don't just code.** This whole phase exists because unit-green ≠ works. Bring the
  real stack up and drive the flow after each item — especially **H2** (confirm agent replies
  now show in the UI) and **H5** (the aligner→converge→plan payoff, still unproven).
- Keep it green each item (backend + CLI gates). The live-node integration slices need a running
  `ghcr.io/agntcy/slim:1.4.0` node — quickstart in the bible Part VI / `docs/cross-machine.md`.
  (Version pin: node `1.4.0` ↔ `slim-bindings 1.4.x`.)
- Land work as PRs into `slim-native-rewrite`; note anything you defer against the bible debt
  register (Part IV). Don't touch `openclaw`/`hermes` — known-broken post-rewrite (D11).

## Definition of done for this phase
The two-laptop hero demo runs clean; **agent replies show in the UI**; rooms survive
restarts/timeouts/disconnects; failures are **loud** (WARNING + health surface); and
**converge → plan → memory is proven with real agents (H5).** Then the rewrite is genuinely
ready for the `slim-native-rewrite → main` landing (see the bible's landing checklist + the
Part VII "must-do before merge").

## How to work with the human
Go item by item; after each, **show concrete evidence** (a loud log line, a health-endpoint
field, an agent reply appearing in the UI, a compiled `plan/tasks.md`). The deliverable is a
system that visibly and reliably works, not a passing test count.
