# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""What every agent-harness family looks like from the outside, as data.

An *agent harness* is a runtime that can hold a reasoning turn: give it a prompt
non-interactively and it thinks, uses tools, and prints an answer. That is the only
capability Mycelium's resident model needs — ``mycelium await --loop --exec <cmd>``
loops await → reason → respond, and the harness is what runs in the middle.

Two consumers read the same table, which is why it is data and not prose:

- an **integration** (``integrations/<family>/``) needs the context-file
  conventions to know where to drop its coordination instructions, and the auth
  story to write an honest ``status_check``;
- the **conformance runner** (``scripts/harness_conformance.py``) needs the binary
  name, the headless argv, and the auth probes to point a real binary at a real
  room and report what happened.

Keeping one table means a harness cannot be "supported" by an integration that the
runner has never exercised, and cannot be exercised by a runner reading a stale
copy of the flags.

``adapter_status`` is the honest grading, mirroring the repo's rule about claiming
capability (``claude_code`` is proven, ``cursor`` is untested):

``proven``
    An integration exists and an end-to-end round-trip has been observed.
``untested``
    An integration exists; no end-to-end round-trip has been observed.
``candidate``
    No integration. The harness clears the bar on paper (headless prompt in,
    answer out) and the conformance runner can grade it up to ``oneshot``; the
    participation level needs a manifest, which is what the integration provides.
``unsupported``
    Not an agent harness. Recorded here so the finding does not have to be
    rediscovered.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

#: Placeholder substituted with the turn prompt when rendering ``headless_argv``.
PROMPT_SLOT = "{prompt}"

AdapterStatus = Literal["proven", "untested", "candidate", "unsupported"]

#: Where a context file lives. ``workspace`` is relative to the agent's cwd (drops
#: at ``mycelium agent create``); ``home`` is relative to ``~`` (drops once per
#: host at ``mycelium adapter add``).
ContextScope = Literal["workspace", "home"]

#: How Mycelium writes a context file. ``own`` means the file is wholly Mycelium's
#: and is overwritten on refresh; ``section`` means the file belongs to the user
#: and only a marker-delimited block inside it is ours.
ContextMerge = Literal["own", "section"]


@dataclass(frozen=True)
class ContextFile:
    """One place a harness reads standing instructions from."""

    path: str
    scope: ContextScope
    merge: ContextMerge
    note: str = ""


@dataclass(frozen=True)
class AuthSpec:
    """How a harness proves who it is without a human at the keyboard.

    ``env_vars`` is the CI-viable path: any one of them being set means the binary
    can run unattended. ``credential_paths`` (``~``-relative) are the cached-login
    artifacts a developer machine has after an interactive ``login_command``. A
    harness with no ``env_vars`` cannot be driven by a scheduled workflow at all,
    which the conformance runner reports rather than papers over.
    """

    env_vars: tuple[str, ...] = ()
    credential_paths: tuple[str, ...] = ()
    login_command: str | None = None

    @property
    def unattended(self) -> bool:
        """True if some env var alone is enough to authenticate."""
        return bool(self.env_vars)


@dataclass(frozen=True)
class HarnessSpec:
    """One agent-harness family, described the way both consumers need it."""

    family: str
    label: str
    binary: str
    docs_url: str
    adapter_status: AdapterStatus
    #: Argv (after ``binary``) that prints a version and exits 0. Empty means the
    #: harness has no version probe and the binary's presence is all we check.
    version_argv: tuple[str, ...] = ()
    #: Argv (after ``binary``) for one non-interactive turn. Exactly one element
    #: must be :data:`PROMPT_SLOT`. Empty means the harness has no headless turn
    #: at all, i.e. it is not a harness.
    headless_argv: tuple[str, ...] = ()
    auth: AuthSpec = field(default_factory=AuthSpec)
    context_files: tuple[ContextFile, ...] = ()
    install_hint: str = ""
    note: str = ""

    @property
    def is_harness(self) -> bool:
        """True if this runtime can hold a reasoning turn non-interactively."""
        return bool(self.headless_argv)

    def render_argv(self, prompt: str) -> list[str]:
        """Full argv for one headless turn carrying *prompt*.

        Returns a real argv list (never a shell string), so a prompt containing
        quotes, newlines or ``$`` is passed through as one argument.
        """
        if not self.headless_argv:
            raise ValueError(f"{self.family!r} has no headless turn; it is not an agent harness")
        return [self.binary, *(prompt if arg == PROMPT_SLOT else arg for arg in self.headless_argv)]


#: The AGENTS.md block every AGENTS.md-reading harness shares. Mycelium owns only
#: the marker-delimited section; the surrounding file is the user's.
_AGENTS_MD = ContextFile(
    path="AGENTS.md",
    scope="workspace",
    merge="section",
    note="shared convention; marker-delimited section, rest of the file is the user's",
)


HARNESS_SPECS: tuple[HarnessSpec, ...] = (
    HarnessSpec(
        family="claude_code",
        label="Claude Code",
        binary="claude",
        docs_url="https://docs.claude.com/en/docs/claude-code/sdk/sdk-headless",
        adapter_status="proven",
        version_argv=("--version",),
        headless_argv=("-p", PROMPT_SLOT),
        auth=AuthSpec(
            env_vars=("ANTHROPIC_API_KEY",),
            credential_paths=(".claude/.credentials.json",),
            login_command="claude login",
        ),
        context_files=(
            ContextFile(
                path=".claude/skills/mycelium/SKILL.md",
                scope="home",
                merge="own",
                note="host-level skill; the only family whose instructions install per-host",
            ),
            _AGENTS_MD,
        ),
        install_hint="https://docs.claude.com/en/docs/claude-code/setup",
        note="The reference implementation: proven end-to-end through the resident loop.",
    ),
    HarnessSpec(
        family="cursor",
        label="Cursor CLI",
        binary="cursor-agent",
        docs_url="https://cursor.com/cli",
        adapter_status="untested",
        version_argv=("--version",),
        headless_argv=("-p", PROMPT_SLOT),
        auth=AuthSpec(
            env_vars=("CURSOR_API_KEY",),
            credential_paths=(".config/cursor/auth.json",),
            login_command="cursor-agent login",
        ),
        context_files=(
            ContextFile(
                path=".cursor/rules/mycelium.mdc",
                scope="workspace",
                merge="own",
                note="Cursor project rule with alwaysApply: true",
            ),
            _AGENTS_MD,
        ),
        install_hint="curl https://cursor.com/install -fsS | bash",
        note="Integration ships; no observed round-trip. The conformance runner is how that changes.",
    ),
    HarnessSpec(
        family="codex",
        label="OpenAI Codex CLI",
        binary="codex",
        docs_url="https://developers.openai.com/codex/noninteractive",
        adapter_status="candidate",
        version_argv=("--version",),
        # `exec` is the headless mode. `--skip-git-repo-check` because an agent cwd
        # is a workspace, not necessarily a repo, and codex exec otherwise refuses.
        headless_argv=("exec", "--skip-git-repo-check", PROMPT_SLOT),
        auth=AuthSpec(
            env_vars=("OPENAI_API_KEY",),
            credential_paths=(".codex/auth.json",),
            login_command="codex login",
        ),
        context_files=(_AGENTS_MD,),
        install_hint="npm install -g @openai/codex",
        note=(
            "Closest fit after claude_code: AGENTS.md is its native instruction surface, "
            "`--json` gives a JSONL event stream, and `exec resume` maps onto a durable session."
        ),
    ),
    HarnessSpec(
        family="copilot",
        label="GitHub Copilot CLI",
        binary="copilot",
        docs_url=(
            "https://docs.github.com/en/copilot/how-tos/copilot-cli/"
            "automate-copilot-cli/run-cli-programmatically"
        ),
        adapter_status="candidate",
        version_argv=("--version",),
        # `-s` drops session metadata so stdout is the answer; `--no-ask-user`
        # stops it pausing for clarification when nobody is at the keyboard.
        headless_argv=("-p", PROMPT_SLOT, "-s", "--no-ask-user"),
        auth=AuthSpec(
            env_vars=("COPILOT_GITHUB_TOKEN", "GH_TOKEN", "GITHUB_TOKEN"),
            credential_paths=(".config/github-copilot/",),
            login_command="copilot  # then /login",
        ),
        context_files=(
            _AGENTS_MD,
            ContextFile(
                path=".github/copilot-instructions.md",
                scope="workspace",
                merge="section",
                note="Copilot-specific repo instructions; read alongside AGENTS.md",
            ),
        ),
        install_hint="npm install -g @github/copilot",
        note=(
            "Token auth makes it the easiest to run unattended. Weigh its CLI surface "
            "churn: `--headless --stdio` was removed without deprecation (github/copilot-cli#1606), "
            "so pin a version and let the conformance runner catch the next break."
        ),
    ),
    HarnessSpec(
        family="kiro",
        label="Kiro CLI",
        binary="kiro-cli",
        docs_url="https://kiro.dev/docs/cli/headless/",
        adapter_status="candidate",
        version_argv=("--version",),
        headless_argv=("chat", "--no-interactive", PROMPT_SLOT),
        auth=AuthSpec(
            env_vars=("KIRO_API_KEY",),
            credential_paths=(".kiro/",),
            login_command="kiro-cli login",
        ),
        context_files=(
            ContextFile(
                path=".kiro/steering/mycelium.md",
                scope="workspace",
                merge="own",
                note="steering file; auto-loaded from .kiro/steering/**/*.md",
            ),
            _AGENTS_MD,
        ),
        install_hint="curl -fsSL https://cli.kiro.dev/install | bash",
        note=(
            "Steering files are a near-exact analogue of Cursor's project rules, so the "
            "cursor integration is the template. Headless output is plain text only — no "
            "JSON envelope — so the exec handler must treat stdout as the answer. "
            "API-key auth is a paid-tier feature."
        ),
    ),
    HarnessSpec(
        family="antigravity",
        label="Antigravity CLI",
        binary="agy",
        docs_url="https://antigravity.google/docs/cli/headless/",
        adapter_status="candidate",
        version_argv=("--version",),
        headless_argv=("-p", PROMPT_SLOT),
        auth=AuthSpec(
            # No documented API-key env var: headless mode reuses credentials cached
            # by an interactive session, so a cold CI runner cannot authenticate.
            credential_paths=(".antigravity/", ".config/antigravity/"),
            login_command="agy  # interactive login, then headless reuses the cache",
        ),
        context_files=(_AGENTS_MD,),
        install_hint="https://antigravity.google/docs/cli/install/",
        note=(
            "Google's successor to Gemini CLI. Richest headless surface of the set "
            "(`--output-format json|stream-json`, `--json-schema`, `--print-timeout`), but "
            "it authenticates only from a cached interactive login, so it grades on a "
            "developer machine and skips on a cold runner until that changes."
        ),
    ),
    HarnessSpec(
        family="perplexity",
        label="Perplexity pplx",
        binary="pplx",
        docs_url="https://docs.perplexity.ai/docs/cli/overview",
        adapter_status="unsupported",
        version_argv=("--version",),
        # Deliberately empty: `pplx` exposes `search web` and `content fetch`. It
        # answers queries about the world, it does not hold a reasoning turn, use
        # tools, or edit files, so there is nothing for the resident loop to drive.
        headless_argv=(),
        auth=AuthSpec(env_vars=("PPLX_API_KEY", "PERPLEXITY_API_KEY")),
        install_hint="https://docs.perplexity.ai/docs/cli/overview",
        note=(
            "Not an agent harness: a single-binary client for the Search API "
            "(`pplx search web`, `pplx content fetch`) returning JSON. It is a tool a "
            "harness calls, so it belongs behind MCP for the aligner and residents to "
            "use — not in front of an adapter."
        ),
    ),
)


#: Family id → spec, for callers that already know the family.
SPECS_BY_FAMILY: dict[str, HarnessSpec] = {spec.family: spec for spec in HARNESS_SPECS}


def get_spec(family: str) -> HarnessSpec:
    """Return the spec for *family*, or raise ``KeyError`` with the known set."""
    try:
        return SPECS_BY_FAMILY[family]
    except KeyError:
        known = ", ".join(sorted(SPECS_BY_FAMILY))
        raise KeyError(f"unknown harness family {family!r}; known: {known}") from None
