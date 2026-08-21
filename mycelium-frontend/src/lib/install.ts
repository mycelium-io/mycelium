// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * Content for the guided CLI install surface.
 *
 * This page is served by a hub that already exists, so the browser can't
 * stand one up and the flow never asks it to. It's the client-only path from
 * `docs/agents.md`: get the CLI, point it at this hub, sign in if the hub
 * asks for it. Keeping the copy here (rather than inline in the panel) keeps
 * the strings testable and single-sourced with the README.
 */

export const DOCS_URL = "https://mycelium-io.github.io/mycelium";

/** Step 1: fetch the CLI, the same one-liner the README and docs site carry. */
export const CLI_INSTALL_COMMAND = `curl -fsSL ${DOCS_URL}/install.sh | bash`;

/** Alternative to Step 1 for a coding agent instead of a human at a terminal:
 *  the same one-liner the landing page's "prompt" tab hands over. The agent
 *  reads `agents.md` and does the setup itself, interactive branching (Step 2)
 *  included, so nothing else here needs a prompt-specific version. */
export const PROMPT_COMMAND = `Use curl to read ${DOCS_URL}/agents.md and perform the setup to install Mycelium`;

/** Step 2: point the CLI at the hub this page is served from, and pick it up. */
export function configSetCommand(hubUrl: string): string {
  return `mycelium config set server.api_url ${hubUrl} && mycelium config apply`;
}

/** Step 3: OIDC sign-in, only needed if this hub's auth gate is on. Most
 *  hubs don't have one, and the CLI errors plainly ("no OIDC issuer
 *  configured") rather than hanging, so the panel says to skip it on that
 *  error instead of gating the step behind a client-side guess. */
export const LOGIN_COMMAND = "mycelium login";

export type Platform = "macos" | "linux" | "windows" | "unknown";

export interface PlatformInfo {
  id: Exclude<Platform, "unknown">;
  label: string;
  /** Extra shown under the commands when this platform is selected. */
  note?: string;
}

export const PLATFORMS: PlatformInfo[] = [
  { id: "macos", label: "macOS" },
  { id: "linux", label: "Linux" },
  {
    id: "windows",
    label: "Windows",
    note: "Run both commands inside WSL. The installer and the Docker stack are POSIX-only, and the hub then answers on localhost for the browser too.",
  },
];

/**
 * Best-effort OS from a user-agent string. Phones and tablets read as
 * `unknown`, since nothing installs there, and their UAs name a desktop
 * family ("like Mac OS X", "Linux; Android"), so they're matched first.
 */
export function detectPlatform(userAgent: string | null | undefined): Platform {
  const ua = (userAgent ?? "").toLowerCase();
  if (!ua) return "unknown";
  if (/android|iphone|ipad|ipod/.test(ua)) return "unknown";
  if (/windows|win32|win64/.test(ua)) return "windows";
  if (/mac os|macintosh/.test(ua)) return "macos";
  if (/linux|x11|cros/.test(ua)) return "linux";
  return "unknown";
}

export interface NextStep {
  title: string;
  body: string;
  command: string;
  /** Where the docs explain this step in full. */
  href: string;
}

/** What to do once the hub answers: the shape of a first session. */
export const NEXT_STEPS: NextStep[] = [
  {
    title: "Create a room",
    body: "A room is the shared space for agents, memory, and the plan.",
    command: "mycelium room create my-project && mycelium room use my-project",
    href: `${DOCS_URL}/index.html#rooms`,
  },
  {
    title: "Add an agent",
    body: "One per role. Each becomes a citizen of the room you can @mention.",
    command: 'mycelium agent create planner --description "Sprint planner"',
    href: `${DOCS_URL}/adapters.html`,
  },
  {
    title: "Keep the session resident",
    body: "The loop is the wake: await → reason → respond, keeping context between turns.",
    command: "mycelium await --loop",
    href: `${DOCS_URL}/reference.html`,
  },
];
