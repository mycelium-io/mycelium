// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

/**
 * The team around the workshop's replay (`workshop.ts`): a hub with a team's
 * rooms on it, two weeks of work in `release-planning`, and more people and
 * agents than the three the run had. The run's words are the only agent lines
 * here; everything this file adds is a person's (a task they filed, a line
 * they wrote, a note they keep) or the board's own bookkeeping.
 */

import type { MockMemory, MockMessage, RoomFixture } from "./fixtures";
import { noticeFrame, pingFrame } from "./live";

const BOOT = Date.now();
const HOUR = 3_600_000;
const DAY = 24 * HOUR;
/** A time `days` (and `hours`) before the server started. */
const ago = (days: number, hours = 0): string => new Date(BOOT - days * DAY - hours * HOUR).toISOString();

/** The team's hub, as the title bar names a hub that isn't this computer. */
export const WORKSHOP_HUB_URL = "https://hub.northwind.team";

/** Teammates beyond the three people the videos follow. */
export const WORKSHOP_TEAMMATES = [
  { handle: "priya", name: "Priya Raman" },
  { handle: "sam", name: "Sam Okafor" },
  { handle: "lena", name: "Lena Brandt" },
] as const;

/** The team's agents beyond the run's three. */
const MORE_AGENTS = [
  { handle: "reviewer", owner: "sam", about: "Reviews pull requests against the team's checklist before a person does." },
  { handle: "builder", owner: "priya", about: "Takes a scoped task, builds it in its own branch and opens the pull request." },
];

/** The hub's other rooms, by folder. `release-planning` is the workshop's. */
export const WORKSHOP_FOLDERS: { name: string; rooms: string[] }[] = [
  { name: "product", rooms: ["release-planning", "roadmap", "pricing-and-plans"] },
  { name: "eng", rooms: ["mobile-app", "sync-service", "ci-and-builds"] },
  { name: "customers", rooms: ["field-service-pilot", "support-escalations", "enterprise-onboarding"] },
];

/** The folder layout every person in the team sees. */
export function workshopFolders(): { folders: { id: string; name: string; rooms: string[] }[] } {
  return { folders: WORKSHOP_FOLDERS.map((f) => ({ id: `folder-${f.name}`, name: f.name, rooms: f.rooms })) };
}

/** The other rooms: listed, foldered, and quiet, since no take opens one. */
export function workshopOtherRooms(owner: string, members: string[]): Record<string, RoomFixture> {
  const names = WORKSHOP_FOLDERS.flatMap((f) => f.rooms).filter((r) => r !== "release-planning");
  return Object.fromEntries(
    names.map((name, i) => [
      name,
      {
        room: {
          id: 9200 + i,
          name,
          is_public: false,
          is_persistent: true,
          owner,
          members,
          created_at: ago(40 + i),
        },
        memories: [],
        messages: [],
        episodes: [],
        episodeDetails: {},
      } satisfies RoomFixture,
    ]),
  );
}

/** A board row: a task someone filed, where it stands, and who has it. */
interface Row {
  slug: string;
  title: string;
  by: string;
  filed: number;
  /** Who it's for, when someone named them. */
  for?: string;
  /** Who holds it now (claimed). */
  holder?: string;
  blocked?: string;
  resolved?: number;
  body?: string;
}

/** The release-planning board, two weeks in. */
const ROWS: Row[] = [
  { slug: "calendar-feed-all-day-events", title: "Calendar feed: tasks with a due date as all-day events", by: "julia", filed: 12, holder: "eng" },
  { slug: "csv-export-any-task-list", title: "CSV export of any task list", by: "priya", filed: 11, holder: "builder" },
  { slug: "dark-mode-android-contrast", title: "Dark mode: fix contrast on Android", by: "marc", filed: 10, for: "design" },
  { slug: "two-factor-recovery-codes", title: "Two-factor login: recovery codes screen", by: "sam", filed: 10 },
  { slug: "keep-both-edits-on-conflict", title: "Keep both edits when two people change the same task offline", by: "julia", filed: 3, for: "eng" },
  { slug: "pilot-forced-update-plan", title: "Forced update plan with the pilot's IT team", by: "jodee", filed: 2, for: "product" },
  { slug: "stage-copy-available-in-december", title: "Stage copy for the Nov 10 announcement", by: "jodee", filed: 2, holder: "jodee" },
  { slug: "technician-usability-sessions", title: "Usability sessions with five field technicians", by: "marc", filed: 4, holder: "marc" },
  { slug: "offline-indicator-states", title: "Offline indicator: offline, syncing and failed states", by: "marc", filed: 4, for: "design" },
  { slug: "queue-retry-backoff", title: "Retry queued changes with backoff on flaky connections", by: "priya", filed: 6, holder: "builder" },
  { slug: "android-12-empty-queue-crash", title: "Crash on Android 12 when the sync queue is empty", by: "lena", filed: 5, blocked: "a device to reproduce on" },
  { slug: "support-macro-lost-changes", title: "Support reply for \"my changes disappeared\"", by: "lena", filed: 5, holder: "lena" },
  { slug: "app-store-review-notes", title: "App-store review notes for the December build", by: "jodee", filed: 1, for: "product" },
  { slug: "ios-widgets-spike", title: "Spike: home-screen widgets on iOS", by: "sam", filed: 9 },
  { slug: "workspace-onboarding-checklist", title: "Onboarding checklist for new workspaces", by: "jodee", filed: 8 },
  { slug: "release-notes-4-12", title: "Release notes for 4.12", by: "jodee", filed: 1 },
  { slug: "flaky-sync-test-ci", title: "Flaky sync test on CI", by: "sam", filed: 3, holder: "reviewer" },
  { slug: "task-editor-accessibility", title: "Accessibility pass on the task editor", by: "marc", filed: 7 },
  { slug: "android-cold-start", title: "Cut Android cold start under two seconds", by: "priya", filed: 6 },
  { slug: "bulk-move-tasks", title: "Move tasks between projects in bulk", by: "jodee", filed: 9 },
  { slug: "due-date-email-reminders", title: "Due-date reminders by email", by: "jodee", filed: 8 },
  { slug: "admin-audit-log-export", title: "Audit log export for admins", by: "sam", filed: 7, blocked: "the enterprise contract's retention terms" },
  { slug: "sync-service-load-test", title: "Load test the sync service at 300 devices", by: "priya", filed: 2, for: "eng" },
  // Done.
  { slug: "ship-4-11-to-the-stores", title: "Ship 4.11 to the stores", by: "julia", filed: 13, holder: "julia", resolved: 9 },
  { slug: "duplicate-notifications-ios", title: "Duplicate push notifications on iOS", by: "lena", filed: 12, holder: "builder", resolved: 6 },
  { slug: "rotate-push-keys", title: "Rotate the push service keys", by: "sam", filed: 11, holder: "sam", resolved: 5 },
  { slug: "holiday-support-rota", title: "Holiday support rota", by: "lena", filed: 6, holder: "lena", resolved: 2 },
];

/** Notes the team keeps, by folder: decisions, how-tos, skills, releases. */
const NOTES: { key: string; by: string; days: number; text: string }[] = [
  { key: "decisions/4-11-scope", by: "julia", days: 13, text: "4.11 scope\n\nShip CSV import fixes and the new share sheet; hold widgets." },
  { key: "decisions/support-hours", by: "lena", days: 10, text: "Support hours over the holidays\n\nWeekdays 8 to 6 Central, one person on call." },
  { key: "decisions/android-min-version", by: "priya", days: 8, text: "Minimum Android version\n\nAndroid 10 and up from 4.12." },
  { key: "decisions/pilot-success-criteria", by: "jodee", days: 6, text: "Pilot success criteria\n\nTechnicians close their day's tasks with no lost changes for two weeks." },
  { key: "procedures/release-checklist", by: "julia", days: 30, text: "Release checklist\n\nCut the branch, run the device matrix, submit both stores, post the notes." },
  { key: "procedures/hotfix", by: "sam", days: 28, text: "Hotfix\n\nBranch from the release tag, one reviewer, expedited review on iOS." },
  { key: "procedures/app-store-submission", by: "julia", days: 25, text: "App-store submission\n\nAllow three days for review; submit on a Monday." },
  { key: "procedures/incident-response", by: "sam", days: 20, text: "Incident response\n\nOpen a thread in support-escalations, name an owner, post every hour." },
  { key: "skills/write-release-notes", by: "jodee", days: 18, text: "Write release notes\n\nLead with what a person can do now. One line per change." },
  { key: "skills/triage-a-crash", by: "priya", days: 16, text: "Triage a crash\n\nFind the build, the device and the last sync before the crash." },
  { key: "skills/review-a-pull-request", by: "sam", days: 15, text: "Review a pull request\n\nTests first, then the migration, then the copy." },
  { key: "releases/4-10", by: "julia", days: 27, text: "4.10\n\nRecurring tasks; faster search." },
  { key: "releases/4-11", by: "julia", days: 9, text: "4.11\n\nShare sheet; CSV import fixes; fewer duplicate notifications." },
  { key: "releases/4-12", by: "jodee", days: 1, text: "4.12 (planned)\n\nOffline mode on the pilot first, then everyone." },
  { key: "context/team", by: "julia", days: 30, text: "The team\n\nJulia leads engineering, Jodee product, Marc design. Priya and Sam build; Lena runs support." },
  { key: "context/pilot-customer", by: "jodee", days: 14, text: "The pilot customer\n\nA field-service company with 300 technicians, rolling out by their IT team." },
  { key: "context/customers-asking-for-offline", by: "lena", days: 11, text: "Who asked for offline\n\nA third of last quarter's tickets were about losing work when the connection dropped." },
  { key: "work/notes/offline-mode-research", by: "marc", days: 5, text: "Offline mode research\n\nTechnicians lose signal in basements and on rooftops; they keep working on paper." },
];

/** What people said in the channel: a line each, between the board's moves. */
const SAID: { by: string; days: number; hours?: number; text: string }[] = [
  { by: "julia", days: 13, text: "4.11 is cut. Device matrix runs tonight." },
  { by: "sam", days: 12, hours: 20, text: "Matrix is green apart from one Pixel 6 timeout; rerunning." },
  { by: "lena", days: 12, text: "Seeing duplicate pushes on iOS from three customers this morning." },
  { by: "priya", days: 11, text: "CSV export is mine. I'll hand the formatting to the builder agent." },
  { by: "jodee", days: 10, text: "Pilot kickoff went well. They asked about offline twice." },
  { by: "marc", days: 9, hours: 4, text: "Dark mode screens are ready for review." },
  { by: "julia", days: 9, text: "4.11 is live on both stores." },
  { by: "lena", days: 6, text: "Duplicate pushes are gone since the fix. Thanks, Priya." },
  { by: "sam", days: 5, text: "Push keys rotated. Nothing to do on your side." },
  { by: "marc", days: 4, text: "Booked five technicians for usability sessions next week." },
  { by: "jodee", days: 2, hours: 3, text: "Sales told the pilot offline comes \"this fall\". We need a date before Nov 10." },
  { by: "julia", days: 2, text: "Agreed. I'll file it and ask the agents." },
  { by: "priya", days: 1, hours: 6, text: "Retry backoff PR is up." },
  { by: "lena", days: 1, hours: 2, text: "Holiday rota is posted in support-escalations." },
];

/** Pull requests that moved, as their row's thread hears it. */
const PULLS: { slug: string; change: "opened" | "merged"; n: number; days: number; who: string }[] = [
  { slug: "duplicate-notifications-ios", change: "merged", n: 471, days: 6, who: "builder,sam" },
  { slug: "rotate-push-keys", change: "merged", n: 476, days: 5, who: "sam" },
  { slug: "csv-export-any-task-list", change: "opened", n: 482, days: 3, who: "builder" },
  { slug: "queue-retry-backoff", change: "opened", n: 488, days: 1, who: "builder" },
  { slug: "calendar-feed-all-day-events", change: "merged", n: 479, days: 4, who: "eng,reviewer" },
];

/** The run's own agent lines the channel hears about: the earlier release
 *  decision's positions and picks, quoted by their pings. */
const PINGED = /^(@~?\w+ )?(Engineering's position|Product's pick)|^calendar sync: A one-way, read-only calendar feed, one URL per user|^Ship the one-way calendar feed as the headline, plus CSV export/;

function memory(key: string, value: string, by: string, at: string, meta: Record<string, unknown> | null = null, episode?: string): MockMemory {
  return { key, value, content_text: value, meta, created_by: by, updated_by: by, version: 1, updated_at: at, ...(episode ? { episode } : {}) };
}

function manifest(handle: string, owner: string, about: string): MockMemory {
  return memory(`agents/${handle}`, `adapter: claude_code\ndescription: "${about}"\nowner: ${owner}\n`, owner, ago(20));
}

function at(frame: Record<string, unknown>, when: string): Record<string, unknown> {
  return { ...frame, created_at: when };
}

/** The room's two weeks, around the run: rows, notes, notices, people's lines,
 *  the earlier decision's pings, the team's agents, and who's at work. */
export function liveIn(fx: RoomFixture, active: { handle: string; status: string }[]): void {
  const room = fx.room.name;
  const ep = (slug: string) => `urn:ioc:mycelium:episode:${room}:${slug}`;
  const wire: Record<string, unknown>[] = [];
  const rows: MockMemory[] = [];

  for (const [i, r] of ROWS.entries()) {
    const key = `work/${r.slug}`;
    const holder = r.holder ? `@${r.holder}` : undefined;
    const meta: Record<string, unknown> = {
      kind: "action",
      status: r.resolved ? "resolved" : "open",
      ...(r.for ? { assignee: `@${r.for}` } : {}),
      ...(holder ? { assignment: r.resolved ? "resolved" : "held", owner: holder, claimed_at: ago(r.filed - 1) } : {}),
      ...(r.blocked ? { blocked_by: [r.blocked] } : {}),
    };
    // Work someone holds was touched within the hour; the rest last moved when it did.
    const last = r.resolved ? ago(r.resolved) : r.holder || r.for ? ago(0, 0.1 + (i % 6) * 0.15) : ago(r.filed);
    rows.push(memory(key, `${r.title}\n\n${r.body ?? ""}`.trim(), r.by, last, meta, ep(r.slug)));
    const base = { key, title: r.title, episode: ep(r.slug) };
    wire.push(at(noticeFrame(room, { ...base, subkind: "filed", by: r.by, kind: "action", for: r.for ? `@${r.for}` : undefined }), ago(r.filed)));
    if (r.holder) wire.push(at(noticeFrame(room, { ...base, subkind: "claimed", by: r.holder }), ago(r.filed - 1, -2)));
    if (r.blocked) wire.push(at(noticeFrame(room, { ...base, subkind: "blocked", by: r.holder ?? r.by }), ago(r.filed - 2)));
    if (r.resolved) wire.push(at(noticeFrame(room, { ...base, subkind: "resolved", by: r.holder ?? r.by }), ago(r.resolved)));
  }

  for (const p of PULLS) {
    const r = ROWS.find((x) => x.slug === p.slug)!;
    wire.push(
      at(
        noticeFrame(room, {
          subkind: "upstream",
          key: `work/${r.slug}`,
          title: r.title,
          episode: ep(r.slug),
          change: p.change,
          ref: `tasks-app#${p.n}`,
          url: `https://git.northwind.team/tasks-app/pull/${p.n}`,
          who: p.who,
        }),
        ago(p.days),
      ),
    );
  }

  const said: MockMessage[] = SAID.map((s, i) => ({
    id: `${room}-said-${i}`,
    sender_handle: s.by,
    message_type: "broadcast",
    content: s.text,
    created_at: ago(s.days, s.hours ?? 0),
    episode: null,
  }));

  // The earlier decision's own agent lines, as the channel hears them.
  for (const m of fx.messages) {
    if (m.message_type === "broadcast" && m.episode && PINGED.test(m.content)) {
      wire.push(at(pingFrame(room, { episode: m.episode, sender: m.sender_handle, message: m.id }), m.created_at));
    }
  }

  // The earlier decision's task is done; so is everything it settled.
  const plan = fx.messages.find((m) => /^@conductor concord/.test(m.content) && m.episode);
  if (plan?.episode) {
    const key = "work/plan-the-next-release";
    const row = fx.memories.find((m) => m.key === key);
    if (row) row.meta = { ...(row.meta ?? {}), status: "resolved", assignment: "resolved", owner: "@julia" };
    const done = new Date(Date.parse(plan.created_at) + 20 * 60_000).toISOString();
    wire.push(at(noticeFrame(room, { subkind: "resolved", key, title: "Plan the next release", episode: plan.episode, by: "julia" }), done));
  }

  const notes = NOTES.map((n) => memory(n.key, n.text, n.by, ago(n.days)));
  const agents = MORE_AGENTS.map((a) => manifest(a.handle, a.owner, a.about));
  fx.memories = [...fx.memories, ...rows, ...notes, ...agents];
  fx.messages = [...said, ...fx.messages].sort((a, b) => a.created_at.localeCompare(b.created_at));
  fx.wire = [...(fx.wire ?? []), ...wire].sort((a, b) => String(a.created_at).localeCompare(String(b.created_at)));
  fx.presence = [...MORE_AGENTS.map((a) => ({ handle: a.handle, status: "working" })), ...active].map((p) => ({
    handle: p.handle,
    kind: "herdr" as const,
    last_seen: null,
    status: p.status,
  }));
}
