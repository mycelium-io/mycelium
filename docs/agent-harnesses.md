# Agent harnesses: the candidate set, and the adapter shape they imply

Mycelium's resident model asks one thing of an agent runtime: hold a reasoning
turn. `mycelium await --loop --exec <cmd>` loops await → reason → respond, and
`<cmd>` is the harness. Everything else an integration does — dropping
coordination instructions, building a manifest, reporting health — is in service
of that one call.

This note surveys the harnesses that clear that bar, and argues that the six
real candidates converge hard enough that the answer is one parameterized family,
not six hand-written adapters.

The survey is data, not prose:
[`mycelium/integrations/harness_specs.py`](../mycelium-cli/src/mycelium/integrations/harness_specs.py)
holds the table, and [`scripts/harness_conformance.py`](../scripts/harness_conformance.py)
grades real binaries against it.

## The candidates

| Harness | Binary | Headless turn | Instruction surface | Unattended auth | Grade |
| --- | --- | --- | --- | --- | --- |
| Claude Code | `claude` | `claude -p "…"` | `~/.claude/skills/`, `AGENTS.md` | `ANTHROPIC_API_KEY` | **proven** |
| Cursor CLI | `cursor-agent` | `cursor-agent -p "…"` | `.cursor/rules/*.mdc`, `AGENTS.md` | `CURSOR_API_KEY` | **untested** |
| OpenAI Codex | `codex` | `codex exec "…"` | `AGENTS.md` | `OPENAI_API_KEY` | candidate |
| GitHub Copilot | `copilot` | `copilot -p "…" -s --no-ask-user` | `AGENTS.md`, `.github/copilot-instructions.md` | `COPILOT_GITHUB_TOKEN` | candidate |
| Kiro | `kiro-cli` | `kiro-cli chat --no-interactive "…"` | `.kiro/steering/*.md`, `AGENTS.md` | `KIRO_API_KEY` | candidate |
| Antigravity | `agy` | `agy -p "…"` | `AGENTS.md` | **none** | candidate |
| Perplexity | `pplx` | — | — | `PPLX_API_KEY` | **not a harness** |

### Perplexity is not a harness

`pplx` is a single-binary client for the Perplexity Search API: `pplx search web`
and `pplx content fetch`, both returning JSON. It answers questions about the
world. It does not hold a reasoning turn, call tools, or edit files, so there is
nothing for the resident loop to drive and no adapter to write.

It is still useful, on the other side of the boundary: a *tool a harness calls*.
The natural home is MCP, where the aligner's Pi brain and resident agents can
reach it for grounded search. That is a different piece of work from an adapter,
and putting it behind one would have been a category error.

The table records this as `adapter_status="unsupported"` so the finding does not
have to be rediscovered by the next person who reads the candidate list.

### Antigravity authenticates, but not in CI

Google's successor to Gemini CLI has the richest headless surface of the set —
`--output-format json|stream-json`, `--json-schema` for structured output,
`--print-timeout`, `--effort`. On a developer machine it is an excellent fit.

But headless mode reuses credentials cached by a prior interactive session, and
there is no documented API-key environment variable. A cold CI runner cannot
authenticate it at all. That is a property of the harness, not of our test setup,
so the conformance runner reports it as an auth wall rather than as a failure, and
the scheduled workflow will keep grading its `binary` rung until the story changes.

### Copilot is the easiest to run unattended, and the most likely to move

Token auth (`COPILOT_GITHUB_TOKEN`, or a workflow's own `GITHUB_TOKEN`) makes
Copilot the only candidate that authenticates in CI with no extra secret. Against
that: its CLI surface churns. `--headless --stdio` was removed with no deprecation
period, breaking every downstream integration that depended on it
(github/copilot-cli#1606). Pin a version, and let the conformance run be what
tells us when the next one lands.

## What the survey actually shows

Five of the six real harnesses read **`AGENTS.md`**, and every one of them takes a
prompt as `-p`-or-equivalent and prints an answer on stdout. The differences that
remain are small and enumerable:

- the argv that starts a headless turn (`-p` vs `exec` vs `chat --no-interactive`);
- one optional harness-native rules file *in addition to* `AGENTS.md`
  (`.cursor/rules/mycelium.mdc`, `.kiro/steering/mycelium.md`,
  `.github/copilot-instructions.md`);
- the auth probe;
- whether instructions install per-workspace or per-host.

That is a table, not five programs. Claude Code is the genuine outlier — its
instructions install per-host as a skill under `~/.claude/`, not per-workspace —
and it already has its own integration.

### The proposal: one AGENTS.md family, parameterized

Add a single `Integration` subclass driven by a `HarnessSpec`, rather than one
subclass per vendor:

- **`build_manifest`** — identical across families today; the only variable is the
  `adapter` literal.
- **`register`** — drop the harness's context files into the agent's cwd, taking
  paths and merge modes from `spec.context_files`. Mycelium owns its own rules
  file outright and marker-merges its `AGENTS.md` section, exactly as the cursor
  integration already does. That merge logic is the reusable part; lifting it out
  of `cursor/install.py` is the first refactor.
- **`status_check`** — `spec.binary` on PATH, plus the auth probe from `spec.auth`.
  Honest by construction, with no per-family prose to keep in sync.
- **the exec handler** — turn in, harness argv rendered, stdout back via
  `mycelium respond`. The conformance runner already ships this handler and is
  deliberately harness-agnostic; an adapter would ship the same script and vary
  only `HARNESS_ARGV`.

The instruction content is one document with per-harness framing, not six. The
cursor rule and the Claude skill are already ~90% the same text: the protocol
(post a position → await → respond → consensus → plan → work), the memory layers,
and the identity rules. Only the container format differs.

Adding a family then means an entry in `HARNESS_SPECS`, the family id in
`AGENT_ADAPTERS` and the `AgentManifest.adapter` literal, and a conformance run
proving the round-trip. `test_harness_specs.py` fails if a family is graded
`proven`/`untested` without an integration behind it, or `candidate` once one
lands.

### What to build first

**Codex.** It is the closest fit after Claude Code: `AGENTS.md` is its native
instruction surface, so it needs no harness-specific rules file at all; `codex exec
--json` emits a JSONL event stream if the handler ever wants more than stdout; and
`codex exec resume` maps onto a durable per-agent session, which is the shape
`await --loop` wants and which most of the field lacks.

**Then Kiro**, because `.kiro/steering/**/*.md` is a near-exact analogue of
Cursor's project rules — the cursor integration is the template, with the caveat
that Kiro's headless output is plain text with no JSON envelope, so the handler
must treat stdout as the answer.

**Then Copilot**, gated on pinning a version.

**Antigravity** waits on an unattended-auth story.

## The conformance harness

Claiming a harness works is only worth doing about a binary someone has run. The
runner grades each family on a ladder and stops at the first rung it cannot climb:

| Rung | What it proves | What it needs |
| --- | --- | --- |
| `binary` | on PATH, version probe exits 0 | the binary |
| `auth` | a credential is detectable (**advisory**) | — |
| `oneshot` | one headless turn echoes a nonce back | binary + credentials |
| `participate` | a resident loop answers an `@`-mention in a live room | hub + SLIM node + an adapter |

```bash
# Grade everything the machine happens to have:
uv run --project mycelium-cli python scripts/harness_conformance.py

# Just one family, no hub needed:
uv run --project mycelium-cli python scripts/harness_conformance.py \
    --family codex --max-level oneshot
```

Three properties are worth calling out, because each was a design decision:

**A SKIP is never a FAIL.** A runner with no Kiro binary has learned nothing about
Kiro. Reporting that as red would train everyone to ignore the report.

**`auth` is advisory and does not gate `oneshot`.** Harnesses authenticate in ways
no probe can enumerate — a managed host may inject a token over a file descriptor,
which is exactly what happened on the machine this was written on: `claude` was
fully authenticated with no `ANTHROPIC_API_KEY` and no `~/.claude/.credentials.json`.
An undetected credential must not be reported as a broken harness, so the turn is
attempted anyway and a failure is annotated as probably-unauthenticated.

**`participate` needs an adapter, and says so.** For a family with no integration
it reports `needs-adapter` — precisely the gap an adapter closes. `oneshot` still
grades, so a candidate is de-risked before a line of adapter code is written. That
is the whole point of building the runner before the adapters.

### CI

[`.github/workflows/harness-conformance.yml`](../.github/workflows/harness-conformance.yml)
runs it weekly, on manual dispatch, and on PRs that touch the harness surface.
Two jobs:

- **`oneshot`** — matrix over every family, installs each vendor CLI, no hub. This
  is where candidate families get graded.
- **`participate`** — restricted to adapter-backed families, and stands up a SLIM
  node and a hub first. A room *is* a SLIM group channel, so with no node the hub
  cannot provision one and `await` never serves a turn — a silent seven-minute
  timeout until the runner learned to check for the node up front.

Nothing gates a PR. Vendors ship breaking CLI changes on their own schedule, so a
red run means "a harness moved", which is news, not a broken pull request.

## Sources

- [Kiro headless mode](https://kiro.dev/docs/cli/headless/) · [Kiro steering](https://kiro.dev/docs/steering/)
- [Codex non-interactive mode](https://developers.openai.com/codex/noninteractive) · [Codex AGENTS.md](https://developers.openai.com/codex/guides/agents-md)
- [Copilot CLI programmatic use](https://docs.github.com/en/copilot/how-tos/copilot-cli/automate-copilot-cli/run-cli-programmatically) · [github/copilot-cli#1606](https://github.com/github/copilot-cli/issues/1606)
- [Antigravity CLI headless mode](https://antigravity.google/docs/cli/headless/)
- [Perplexity CLI](https://docs.perplexity.ai/docs/cli/overview)
- [Cursor CLI](https://cursor.com/cli) · [Claude Code headless](https://docs.claude.com/en/docs/claude-code/sdk/sdk-headless)
