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

/** Point the CLI at the hub this page is served from. */
export function configSetCommand(hubUrl: string): string {
  return `mycelium config set server.api_url ${hubUrl} && mycelium config apply`;
}

export const LOGIN_COMMAND = "mycelium login";

export interface HubSetupOptions {
  hubUrl: string;
  authRequired: boolean | null;
  principal?: string;
}

/** A complete, copyable terminal setup. Login is only included when the hub
 * reports its auth requirement; a browser-picked identity never overrides it. */
export function hubSetupCommand({ hubUrl, authRequired, principal }: HubSetupOptions): string {
  const lines = [CLI_INSTALL_COMMAND, configSetCommand(hubUrl)];
  if (authRequired) {
    lines.push(LOGIN_COMMAND, "mycelium whoami");
  } else if (authRequired === false && principal) {
    lines.push(`mycelium iam ${principal}`);
  }
  lines.push("mycelium room ls");
  return lines.join("\n");
}

/** Give a coding agent the concrete hub it must join rather than asking it to
 * discover a generic public guide. */
export function hubSetupPrompt(options: HubSetupOptions): string {
  const auth = options.authRequired
    ? `This hub requires sign-in: run \`${LOGIN_COMMAND}\`, then confirm the signed-in identity with \`mycelium whoami\`.`
    : options.authRequired === false && options.principal
      ? `This open hub is currently acting as @${options.principal}; after configuring the CLI, run \`mycelium iam ${options.principal}\`.`
      : options.authRequired === false
        ? "This hub is open. Choose a local identity with `mycelium iam <your-handle>` if you need attribution."
        : `If the hub asks you to authenticate, run \`${LOGIN_COMMAND}\` and use the identity it confirms.`;
  return [
    `Set up Mycelium to use the already-running hub at ${options.hubUrl}.`,
    `Install the CLI if needed with \`${CLI_INSTALL_COMMAND}\`, then run \`${configSetCommand(options.hubUrl)}\`.`,
    auth,
    "Verify the connection with `mycelium room ls`, then return control to me.",
  ].join("\n\n");
}

export interface AgentHandoffOptions extends HubSetupOptions {
  roomName: string;
}

/** The handoff a human pastes into an agent that is already running locally.
 * Mycelium configures and registers it; it never starts another agent process. */
export function agentHandoffPrompt(options: AgentHandoffOptions): string {
  const owner = options.authRequired === false && options.principal ? ` --owner ${options.principal}` : "";
  const auth = options.authRequired
    ? `Sign in with \`${LOGIN_COMMAND}\` first and use the identity it confirms; do not invent or override an identity.`
    : options.authRequired === false && options.principal
      ? `The room's human owner is @${options.principal}.`
      : "If the hub asks you to sign in, use the identity it confirms. Otherwise ask the human for an owner if you need one.";
  return [
    `You are joining the Mycelium room \`${options.roomName}\` on the already-running hub at ${options.hubUrl} as a coding-agent collaborator.`,
    `Install the CLI if needed with \`${CLI_INSTALL_COMMAND}\`, then run \`${configSetCommand(options.hubUrl)}\`.`,
    auth,
    `Choose a short handle and register yourself with \`mycelium agent create <handle> --room ${options.roomName}${owner}\`.`,
    `Read \`mycelium room messages --room ${options.roomName} --limit 20\` and \`mycelium board --room ${options.roomName}\`. Claim a suitable task or ask me which task to take.`,
    `When you are waiting for collaboration, use \`mycelium await --room ${options.roomName} --handle <handle> --timeout 30\`; do not start a separate daemon or replace this session.`,
  ].join("\n\n");
}

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
