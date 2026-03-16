/**
 * mycelium-bootstrap/handler.js
 *
 * Mycelium hook for OpenClaw.
 * Extracts the channel/conversation ID from event context and injects it as
 * MYCELIUM_CHANNEL_ID so all agents in the same Matrix channel share a coordination room.
 * Also forwards MYCELIUM_API_URL from gateway env into the agent session env.
 *
 * Instructions are injected via the mycelium-cfn plugin (prependSystemContext),
 * not here.
 *
 * Installed by: mycelium adapter add openclaw
 */

export default async function HookHandler(event) {
  if (event.type !== "agent" || event.action !== "bootstrap") return;

  const ctx = event.context;

  // Extract channel/conversation ID from event context (Matrix room, Slack channel, etc.)
  // Try multiple field names used by different platforms
  const channelId =
    ctx.channelId ??
    ctx.roomId ??
    ctx.conversationId ??
    ctx.sessionId ??
    null;

  if (channelId) {
    ctx.env = ctx.env ?? {};
    ctx.env.MYCELIUM_CHANNEL_ID = channelId;
  }

  if (process.env.MYCELIUM_API_URL) {
    ctx.env = ctx.env ?? {};
    ctx.env.MYCELIUM_API_URL = process.env.MYCELIUM_API_URL;
  }
}
