// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Julia Valenti

/**
 * Return the subset of `agents` that are @-mentioned in `content`.
 *
 * Matches `@agent-id` as a word (case-insensitive). `@julia-agent` matches;
 * bare `julia-agent` does not — must use the `@` prefix.
 *
 * Word-boundary check: the character after the handle must not be alphanumeric
 * or `-`/`_`, so `@julia-agent-bot` won't match `@julia-agent`.
 */
export function resolveMentions(content: string, agents: string[]): string[] {
  const lower = content.toLowerCase();
  return agents.filter((agentId) => {
    const needle = `@${agentId.toLowerCase()}`;
    const idx = lower.indexOf(needle);
    if (idx === -1) return false;
    const nextChar = lower[idx + needle.length];
    return !nextChar || !/[a-z0-9_-]/.test(nextChar);
  });
}
