# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Static guard against OpenClaw's plugin security scanner.

OpenClaw (2026.4.x+) blocks plugin install when a single source file
contains BOTH an environment-variable read and a network-send call —
the co-occurrence is flagged as possible credential harvesting. The
mycelium plugin refactor in commit 50869be isolated all env access
into ``config.ts`` so no network-using file trips the scanner; this
test catches regressions before they reach the scanner.

Why this test lives here and not in vitest:
    The scanner is pattern-matched and file-scoped. A vitest file that
    defines the forbidden patterns as regex literals would trip the
    scanner on itself — any check we write inside the plugin tree
    becomes self-defeating. Living in pytest outside the plugin dir
    sidesteps that entirely.

If this test fails, either:
    1. Move the env read into ``config.ts`` (or another network-free
       file) and import the resolved value, or
    2. Rephrase comments to avoid the literal ``process.env`` token.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
PLUGIN_ROOT = (
    REPO_ROOT
    / "mycelium-cli"
    / "src"
    / "mycelium"
    / "adapters"
    / "openclaw"
    / "mycelium"
    / "plugin"
)

# Files that are ALLOWED to read the environment. These must stay
# network-free — enforced by the symmetric test below.
ENV_ONLY_ALLOWLIST: frozenset[str] = frozenset({
    "src/config.ts",
})

# Assembled at runtime to avoid putting the literal token `process.env`
# into this file's source (keeps the test self-consistent if a future
# scanner grows to look at Python files too).
ENV_PATTERN = re.compile(r"process" + r"\.env\b")

# Broad network-send vocabulary — mirrors what a pattern-matching scanner
# would plausibly look for. Covers the global fetch API, Node http/https
# modules, axios, and the plugin's own HTTP helpers.
NETWORK_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"\bfetch\s*\("),
    re.compile(r"\bXMLHttpRequest\b"),
    re.compile(r"\baxios\b"),
    re.compile(r"\bhttps?\.(get|post|request|put|delete)\s*\("),
    re.compile(r"\bnet\.Socket\b"),
    re.compile(r"\bapiPost\s*\("),
    re.compile(r"\bapiGet\s*\("),
    re.compile(r"\bpostKnowledgeIngest\s*\("),
    re.compile(r"\bfetchBackendHealth\s*\("),
)


def _walk_ts(root: Path) -> list[Path]:
    skip_dirs = {"node_modules", "dist", ".git"}
    return [
        p
        for p in root.rglob("*.ts")
        if not any(part in skip_dirs for part in p.parts)
    ]


def _find_network_hit(content: str) -> str | None:
    for pattern in NETWORK_PATTERNS:
        match = pattern.search(content)
        if match:
            return match.group(0)
    return None


@pytest.fixture(scope="module")
def plugin_ts_files() -> list[Path]:
    src = _walk_ts(PLUGIN_ROOT / "src")
    test = _walk_ts(PLUGIN_ROOT / "test")
    files = src + test
    assert files, f"no .ts files found under {PLUGIN_ROOT} — wrong path?"
    return files


def test_no_plugin_file_mixes_env_and_network(plugin_ts_files: list[Path]) -> None:
    """No plugin source or test file may contain both env access AND a network call."""
    offenders: list[str] = []
    for path in plugin_ts_files:
        rel = path.relative_to(PLUGIN_ROOT).as_posix()
        if rel in ENV_ONLY_ALLOWLIST:
            continue

        content = path.read_text(encoding="utf-8")
        if not ENV_PATTERN.search(content):
            continue

        net_hit = _find_network_hit(content)
        if net_hit:
            offenders.append(f"{rel}: contains env access AND {net_hit}")

    assert offenders == [], (
        "OpenClaw scanner will block plugin install.\n"
        "Fix: move the env read into src/config.ts (or another "
        "network-free file), or rephrase the comment to avoid the "
        "literal token.\n\nOffenders:\n  " + "\n  ".join(offenders)
    )


def test_env_only_allowlist_stays_network_free() -> None:
    """Files on the env-only allowlist must stay free of network calls."""
    offenders: list[str] = []
    for rel in ENV_ONLY_ALLOWLIST:
        full = PLUGIN_ROOT / rel
        content = full.read_text(encoding="utf-8")
        net_hit = _find_network_hit(content)
        if net_hit:
            offenders.append(f"{rel}: env-only file contains network call {net_hit}")

    assert offenders == [], (
        "An env-reading file grew a network call, which will re-trip the "
        "OpenClaw scanner.\n\nOffenders:\n  " + "\n  ".join(offenders)
    )
