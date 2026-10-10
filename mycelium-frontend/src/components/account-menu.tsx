// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { useCallback, useEffect, useMemo, useState, useSyncExternalStore } from "react";
import {
  ChevronLeft,
  ChevronRight,
  ExternalLink,
  Info,
  LogIn,
  LogOut,
  Pencil,
  Terminal,
  UserRound,
  Users,
} from "lucide-react";
import { useNetworkStatus } from "@/lib/room-data";
import { desktopVersion } from "@/lib/desktop";
import { DOCS_URL } from "@/lib/install";
import { createUser, fetchTeams, fetchUsers, logFetchError, type Team, type User } from "@/lib/api";
import { useCurrentUser } from "@/components/current-user";
import { nameOf, useNames, useRefreshUsers } from "@/lib/people";
import { useCommands } from "@/components/keymap-provider";
import type { PaletteCommand } from "@/lib/commands";
import { useAuthSession } from "@/components/auth-session";
import { Monogram } from "@/components/ui/monogram";
import { Tooltip } from "@/components/ui/tooltip";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { TagInput } from "@/components/ui/tag-input";
import { CopyField } from "@/components/ui/copy-field";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

// A handle is an identity and can be minted by a real IdP, so it allows the `@`
// a corporate SSO `preferred_username` carries (e.g. `user@example.com`). Keep
// in sync with the backend (`app/schemas.py`) and CLI (`protocol.py`) copies.
const HANDLE = /^[a-z0-9][a-z0-9._@-]*$/;
const normHandle = (s: string) => s.trim().replace(/^@/, "").toLowerCase();

type View = "menu" | "switch" | "profile" | "terminal" | "about";

const REPO_URL = "https://github.com/mycelium-io/mycelium";
const FEEDBACK_URL = `${REPO_URL}/discussions/1040`;
/** What an unreleased build reports: the placeholder every package starts at,
 *  which the release workflow overwrites from the tag. */
const UNRELEASED = "0.1.0";

interface Profile {
  displayName: string;
  teams: string[];
  notify: string;
}

/** The `mycelium iam` command that names a machine's CLI the same way. Fully
 *  specified, so it reproduces the user record anywhere and is safe to re-run. */
export function iamCommand(handle: string, user?: Pick<User, "display_name" | "teams" | "notify">): string {
  const arg = (v: string) => (/[\s"']/.test(v) ? `"${v.replace(/"/g, '\\"')}"` : v);
  const parts = [`mycelium iam ${handle}`];
  if (user?.display_name) parts.push(`--name ${arg(user.display_name)}`);
  for (const t of user?.teams ?? []) parts.push(`--team ${t}`);
  if (user?.notify) parts.push(`--notify ${arg(user.notify)}`);
  return parts.join(" ");
}

/**
 * Who you are here, in the title bar's corner.
 *
 * Signed in, the hub knows you from your token and there is nothing to pick.
 * Otherwise the name is one this browser remembers and puts on what you post:
 * the menu says so plainly, asks for one when there is none, and lets you
 * switch. Either way it edits your profile and hands you the command that
 * names your terminal the same way.
 */
export function AccountMenu() {
  const { principal, setPrincipal } = useCurrentUser();
  const { signedIn, handle: sessionHandle, oidcConfigured, login, logout } = useAuthSession();
  const [open, setOpen] = useState(false);
  const [view, setView] = useState<View>("menu");
  const [users, setUsers] = useState<User[]>([]);
  const [teams, setTeams] = useState<Team[]>([]);

  const me = signedIn ? (sessionHandle ?? principal) : principal;
  const record = users.find(u => u.handle === me);
  const myName = nameOf(useNames(), me);
  // A name saved here is the one every message shows, so the shared copy is
  // re-read too, not only this menu's.
  const refreshShared = useRefreshUsers();

  const refresh = useCallback(() => {
    fetchUsers()
      .then(setUsers)
      .catch(err => {
        logFetchError("fetchUsers")(err);
        setUsers([]);
      });
    fetchTeams().then(setTeams).catch(logFetchError("fetchTeams"));
    refreshShared();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const show = (next: boolean, at: View = me ? "menu" : "switch") => {
    setOpen(next);
    if (next) {
      setView(at);
      refresh();
    }
  };

  const commands = useMemo<PaletteCommand[]>(
    () => [
      {
        id: "identity.switch",
        title: "Switch who you are",
        group: "Preferences",
        keywords: ["user", "identity", "principal", "handle", "acting as", "account", "profile"],
        run: () => show(true, signedIn ? "menu" : "switch"),
      },
      {
        id: "app.about",
        title: "About Mycelium",
        group: "Help",
        keywords: ["version", "release", "changelog", "update"],
        run: () => show(true, "about"),
      },
    ],
    // `show` only closes over state setters and `me`, which the view choice reads fresh.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [signedIn, me],
  );
  useCommands(commands);

  const label = me ? `You are ${myName ? `${myName} (@${me})` : `@${me}`}` : "Choose your name";

  return (
    <Popover open={open} onOpenChange={o => show(o)}>
      <Tooltip content={label} side="bottom">
        <PopoverTrigger
          aria-label={label}
          className="flex size-7 items-center justify-center rounded-md transition-colors hover:bg-hairline"
        >
          {me ? (
            <Monogram handle={me} color="var(--avatar-neutral)" className="size-5 text-[8px]" />
          ) : (
            <UserRound className="size-3.5 text-muted-foreground" />
          )}
        </PopoverTrigger>
      </Tooltip>

      <PopoverContent className="w-72 rounded-lg p-0">
        {view === "menu" && me && (
          <MenuView
            me={me}
            user={record}
            signedIn={signedIn}
            canSignIn={oidcConfigured}
            onGo={setView}
            onSignIn={login}
            onSignOut={async () => {
              setOpen(false);
              await logout();
            }}
          />
        )}
        {view === "switch" && !signedIn && (
          <SwitchView
            me={me}
            users={users}
            canSignIn={oidcConfigured}
            onSignIn={login}
            onBack={me ? () => setView("menu") : undefined}
            onPick={async (handle, isNew) => {
              if (isNew) {
                try {
                  await createUser({ handle });
                } catch (err) {
                  // The name still works in this browser; the hub record can follow.
                  logFetchError("createUser")(err);
                }
                refresh();
              }
              setPrincipal(handle);
              setView("menu");
            }}
            onClear={() => {
              setPrincipal("");
              setOpen(false);
            }}
          />
        )}
        {view === "profile" && me && (
          <ProfileView
            me={me}
            user={record}
            teamSuggestions={teams.map(t => t.team)}
            onBack={() => setView("menu")}
            onSaved={() => {
              refresh();
              setView("menu");
            }}
          />
        )}
        {view === "terminal" && me && (
          <TerminalView command={iamCommand(me, record)} onBack={() => setView("menu")} />
        )}
        {view === "about" && <AboutView onBack={me ? () => setView("menu") : undefined} />}
      </PopoverContent>
    </Popover>
  );
}

function MenuView({
  me,
  user,
  signedIn,
  canSignIn,
  onGo,
  onSignIn,
  onSignOut,
}: {
  me: string;
  user?: User;
  signedIn: boolean;
  canSignIn: boolean;
  onGo: (view: View) => void;
  onSignIn: () => void;
  onSignOut: () => void;
}) {
  return (
    <div className="py-1">
      <div className="flex items-center gap-2.5 px-3 pb-2.5 pt-2">
        <Monogram handle={me} color="var(--avatar-neutral)" className="size-8" />
        <div className="min-w-0">
          <div className="truncate text-label font-medium text-text">{user?.display_name || `@${me}`}</div>
          <div className="truncate text-micro text-muted-foreground">
            {user?.display_name && <span className="font-mono">@{me} · </span>}
            {signedIn ? "Signed in" : "Set in this browser"}
          </div>
        </div>
      </div>
      {!signedIn && (
        <p className="border-t border-border px-3 py-2 text-micro leading-relaxed text-faint">
          This name goes on what you post from this browser. Nobody has checked it
          {canSignIn ? "; sign in to prove it." : "."}
        </p>
      )}
      <div className="border-t border-border py-1">
        <Item icon={Pencil} onClick={() => onGo("profile")} more>
          Edit your name
        </Item>
        {!signedIn && (
          <Item icon={Users} onClick={() => onGo("switch")} more>
            Switch
          </Item>
        )}
        <Item icon={Terminal} onClick={() => onGo("terminal")} more>
          Use in a terminal
        </Item>
        <Item icon={Info} onClick={() => onGo("about")} more>
          About Mycelium
        </Item>
      </div>
      {(signedIn || canSignIn) && (
        <div className="border-t border-border py-1">
          {signedIn ? (
            <Item icon={LogOut} onClick={onSignOut}>
              Sign out
            </Item>
          ) : (
            <Item icon={LogIn} onClick={onSignIn}>
              Sign in
            </Item>
          )}
        </div>
      )}
    </div>
  );
}

function SwitchView({
  me,
  users,
  canSignIn,
  onSignIn,
  onBack,
  onPick,
  onClear,
}: {
  me: string;
  users: User[];
  canSignIn: boolean;
  onSignIn: () => void;
  onBack?: () => void;
  onPick: (handle: string, isNew: boolean) => void;
  onClear: () => void;
}) {
  const [query, setQuery] = useState("");
  const [error, setError] = useState<string | null>(null);
  const typed = normHandle(query);
  const shown = users.filter(u => !typed || u.handle.includes(typed) || u.display_name.toLowerCase().includes(typed));
  const isNew = typed.length > 0 && !users.some(u => u.handle === typed);

  const submit = () => {
    if (!typed) return;
    if (!HANDLE.test(typed)) {
      setError("Use lowercase letters, digits, and . _ - or @, with no spaces.");
      return;
    }
    onPick(typed, isNew);
  };

  return (
    <div>
      <Header title={me ? "Switch" : "Who are you?"} onBack={onBack} />
      <p className="px-3 pb-2 text-micro leading-relaxed text-muted-foreground">
        Your name on what you post from this browser. Pick yours, or type a new one.
      </p>
      <div className="px-3 pb-2">
        <Input
          autoFocus
          value={query}
          placeholder="Your handle, e.g. avery"
          onChange={e => {
            setQuery(e.target.value);
            setError(null);
          }}
          onKeyDown={e => {
            if (e.key === "Enter") {
              e.preventDefault();
              if (!isNew && shown[0]) onPick(shown[0].handle, false);
              else submit();
            }
          }}
        />
        {error && (
          <p role="alert" className="mt-1 text-micro text-red">
            {error}
          </p>
        )}
      </div>
      <ul className="max-h-56 overflow-y-auto border-t border-border py-1">
        {isNew && (
          <li>
            <button
              type="button"
              onClick={submit}
              className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-label text-text hover:bg-hairline"
            >
              <Monogram handle={typed} color="var(--avatar-neutral)" className="size-6" />
              <span className="min-w-0 flex-1 truncate">
                Continue as <span className="font-mono">@{typed}</span>
              </span>
              <span className="text-micro text-faint">new</span>
            </button>
          </li>
        )}
        {shown.map(u => (
          <li key={u.handle}>
            <button
              type="button"
              onClick={() => onPick(u.handle, false)}
              className="flex w-full items-center gap-2.5 px-3 py-1.5 text-left text-label hover:bg-hairline"
            >
              <Monogram handle={u.handle} color="var(--avatar-neutral)" className="size-6" />
              <span className="min-w-0 flex-1">
                <span className={`block truncate font-mono ${u.handle === me ? "text-accent" : "text-text"}`}>
                  @{u.handle}
                </span>
                {(u.display_name || u.teams.length > 0) && (
                  <span className="block truncate text-micro text-muted-foreground">
                    {[u.display_name, u.teams.join(", ")].filter(Boolean).join(" · ")}
                  </span>
                )}
              </span>
            </button>
          </li>
        ))}
        {!isNew && shown.length === 0 && (
          <li className="px-3 py-1.5 text-micro text-faint">Nobody has a name on this hub yet. Type yours above.</li>
        )}
      </ul>
      {(canSignIn || me) && (
        <div className="flex items-center justify-between border-t border-border px-3 py-2 text-micro">
          {canSignIn ? (
            <button type="button" onClick={onSignIn} className="text-accent hover:underline">
              Sign in instead
            </button>
          ) : (
            <span />
          )}
          {me && (
            <button type="button" onClick={onClear} className="text-muted-foreground hover:text-text">
              Post without a name
            </button>
          )}
        </div>
      )}
    </div>
  );
}

function ProfileView({
  me,
  user,
  teamSuggestions,
  onBack,
  onSaved,
}: {
  me: string;
  user?: User;
  teamSuggestions: string[];
  onBack: () => void;
  onSaved: () => void;
}) {
  const [form, setForm] = useState<Profile>({
    displayName: user?.display_name ?? "",
    teams: user?.teams ?? [],
    notify: user?.notify ?? "",
  });
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  // The record can arrive after the view opens; fill in what hasn't been typed.
  useEffect(() => {
    if (!user) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setForm(f => ({
      displayName: f.displayName || user.display_name,
      teams: f.teams.length ? f.teams : user.teams,
      notify: f.notify || (user.notify ?? ""),
    }));
  }, [user]);

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await createUser({
        handle: me,
        display_name: form.displayName.trim(),
        teams: form.teams,
        notify: form.notify.trim() || null,
      });
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setSaving(false);
    }
  };

  return (
    <div>
      <Header title="Your name" onBack={onBack} />
      <div className="space-y-3 px-3 pb-3">
        <Field label="Name">
          <Input
            autoFocus
            placeholder="e.g. Avery Quinn"
            value={form.displayName}
            onChange={e => setForm(f => ({ ...f, displayName: e.target.value }))}
          />
        </Field>
        <Field label="Teams">
          <TagInput
            value={form.teams}
            onChange={teams => setForm(f => ({ ...f, teams }))}
            suggestions={teamSuggestions}
            placeholder="Type a team, Enter to add"
            ariaLabel="Teams"
          />
        </Field>
        <Field label="Where to reach you" hint="for escalations">
          <Input
            placeholder="Email or webhook (optional)"
            value={form.notify}
            onChange={e => setForm(f => ({ ...f, notify: e.target.value }))}
          />
        </Field>
        {error && (
          <p role="alert" className="text-micro text-red">
            {error}
          </p>
        )}
        <div className="flex justify-end gap-2 pt-1">
          <Button variant="ghost" size="sm" onClick={onBack}>
            Cancel
          </Button>
          <Button size="sm" onClick={save} disabled={saving}>
            Save
          </Button>
        </div>
      </div>
    </div>
  );
}

function TerminalView({ command, onBack }: { command: string; onBack: () => void }) {
  return (
    <div>
      <Header title="Use in a terminal" onBack={onBack} />
      <div className="space-y-2 px-3 pb-3">
        <p className="text-micro leading-relaxed text-muted-foreground">
          Run this on a machine where your agents work, so what they do is credited to you.
        </p>
        <CopyField value={command} />
      </div>
    </div>
  );
}

/**
 * Which Mycelium this is: the hub's release (what the UI and every agent here
 * run against) and, inside the desktop app, the app's own, with where to read what
 * changed. An unreleased build says so rather than printing a placeholder.
 */
export function AboutView({ onBack }: { onBack?: () => void }) {
  const { network, loading } = useNetworkStatus();
  const hub = network?.version ?? null;
  const app = useSyncExternalStore(noSubscribe, () => desktopVersion(), () => null);
  const released = (v: string | null) => (v && v !== UNRELEASED ? v : null);
  const hubRelease = released(hub);

  const version = (v: string | null) =>
    released(v) ? `v${v}` : v ? "development build" : loading ? "…" : "unreachable";

  return (
    <div>
      <Header title="About Mycelium" onBack={onBack} />
      <dl className="grid grid-cols-[auto_1fr] gap-x-4 gap-y-1.5 px-3 pb-3 pt-1 text-label">
        <dt className="text-muted-foreground">Hub</dt>
        <dd className="font-mono text-text">{version(hub)}</dd>
        {app && (
          <>
            <dt className="text-muted-foreground">Desktop app</dt>
            <dd className="font-mono text-text">{version(app)}</dd>
          </>
        )}
      </dl>
      <div className="border-t border-border py-1">
        <LinkItem href={hubRelease ? `${REPO_URL}/releases/tag/v${hubRelease}` : `${REPO_URL}/releases`}>
          {hubRelease ? "Release notes" : "Releases"}
        </LinkItem>
        <LinkItem href={`${REPO_URL}/blob/main/CHANGELOG.md`}>Changelog</LinkItem>
        <LinkItem href={DOCS_URL}>Docs</LinkItem>
        <LinkItem href={FEEDBACK_URL}>Send feedback</LinkItem>
      </div>
    </div>
  );
}

const noSubscribe = () => () => {};

function LinkItem({ href, children }: { href: string; children: React.ReactNode }) {
  return (
    <a
      href={href}
      target="_blank"
      rel="noopener noreferrer"
      className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-label text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
    >
      <span className="flex-1">{children}</span>
      <ExternalLink className="size-3.5 text-faint" />
    </a>
  );
}

function Header({ title, onBack }: { title: string; onBack?: () => void }) {
  return (
    <div className="flex items-center gap-1 px-2 pb-1.5 pt-2">
      {onBack && (
        <button
          type="button"
          aria-label="Back"
          onClick={onBack}
          className="flex size-6 items-center justify-center rounded text-muted-foreground hover:bg-hairline hover:text-text"
        >
          <ChevronLeft className="size-3.5" />
        </button>
      )}
      <span className={`text-label font-medium text-text ${onBack ? "" : "px-1"}`}>{title}</span>
    </div>
  );
}

function Item({
  icon: Icon,
  onClick,
  more = false,
  children,
}: {
  icon: typeof Pencil;
  onClick: () => void;
  more?: boolean;
  children: React.ReactNode;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex h-8 w-full items-center gap-2.5 px-3 text-left text-label text-muted-foreground transition-colors hover:bg-hairline hover:text-text"
    >
      <Icon className="size-3.5" />
      <span className="flex-1">{children}</span>
      {more && <ChevronRight className="size-3.5 text-faint" />}
    </button>
  );
}

function Field({ label, hint, children }: { label: string; hint?: string; children: React.ReactNode }) {
  return (
    <label className="block">
      <span className="mb-1 block text-micro text-muted-foreground">
        {label} {hint && <span className="text-faint">({hint})</span>}
      </span>
      {children}
    </label>
  );
}
