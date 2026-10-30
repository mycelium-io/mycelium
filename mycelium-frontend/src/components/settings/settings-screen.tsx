// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useSearchParams } from "next/navigation";
import type { ReactNode } from "react";
import { cn } from "@/lib/utils";
import { CLIENT_DEFAULTS, settingHref, useClientSetting, type SettingsPage } from "@/lib/client-settings";
import { desktopMachine, useIsDesktop } from "@/lib/desktop";
import { useHasAppSettings } from "@/lib/desktop-app";
import { AppAgentsPage } from "./app-agents-page";
import { AppExperiencesPage } from "./app-experiences-page";
import { AppHealthPage } from "./app-health-page";
import { AppModelPage } from "./app-model-page";
import { AppVersionPage } from "./app-version-page";
import { AppPrivacyPage, AppVoicePage } from "./app-voice-privacy";
import { ProfilePage } from "./profile-page";
import { GeneralPage } from "./general-page";
import { NotificationsPage } from "./notifications-page";
import { ReadAloudPage } from "./read-aloud-page";
import { KeysPage } from "./keys-page";
import { ConnectionPage } from "./connection-page";
import { RoomSettingsPage } from "./room-page";
import { HubPage } from "./hub-page";

interface RailItem {
  page: SettingsPage;
  label: string;
  /** How many settings on it differ from their defaults, when that's known here. */
  changed?: number;
}

/** The desktop app's own pages, in the app only: what its separate settings
 *  window used to hold, beside everything else. */
const APP_PAGES: RailItem[] = [
  { page: "connection", label: "Hub and Connection" },
  { page: "model", label: "Engines' model" },
  { page: "agents", label: "Agents" },
  { page: "voice", label: "Voice" },
  { page: "experiences", label: "Experiences" },
  { page: "privacy", label: "Privacy" },
  { page: "version", label: "Version" },
  { page: "health", label: "Health check" },
];

function RailGroup({ title, children }: { title: string; children: ReactNode }) {
  return (
    <div className="mb-4">
      <div className="mb-1 px-2 text-[11px] font-semibold uppercase tracking-wide text-faint">{title}</div>
      <ul className="space-y-0.5">{children}</ul>
    </div>
  );
}

function RailLink({ item, active, room }: { item: RailItem; active: boolean; room: string | null }) {
  return (
    <li>
      <Link
        href={settingHref(item.page, undefined, item.page === "room" ? (room ?? undefined) : undefined)}
        aria-current={active ? "page" : undefined}
        className={cn(
          "flex items-center gap-2 rounded-md px-2 py-1.5 text-label transition-colors",
          active ? "bg-surface text-text" : "text-muted-foreground hover:bg-hairline hover:text-text",
        )}
      >
        {item.label}
        {item.changed ? <span className="ml-auto text-micro text-faint">{item.changed} changed</span> : null}
      </Link>
    </li>
  );
}

/** Settings, one page at a time, each at its own address (`/settings/<page>`)
 *  so anywhere in the app can link to it, or to one setting on it. */
export function SettingsScreen({ page }: { page: SettingsPage }) {
  const room = useSearchParams().get("room");
  const desktop = useIsDesktop();
  const [send] = useClientSetting("general.send");
  const [zone] = useClientSetting("general.time-zone");
  const [keys] = useClientSetting("keys.overrides");
  const generalChanged =
    (send !== CLIENT_DEFAULTS["general.send"] ? 1 : 0) + (zone !== CLIENT_DEFAULTS["general.time-zone"] ? 1 : 0);
  const keysChanged = Object.keys(keys).length;
  const here = desktop ? "This app" : "This browser";
  const app = useHasAppSettings();

  return (
    <div className="flex h-full min-h-0 flex-col md:flex-row">
      <nav
        aria-label="Settings"
        className="flex-shrink-0 overflow-x-auto border-b border-border px-3 py-4 md:w-56 md:overflow-y-auto md:border-b-0 md:border-r"
      >
        <RailGroup title="You">
          <RailLink item={{ page: "profile", label: "Profile" }} active={page === "profile"} room={room} />
        </RailGroup>
        <RailGroup title={here}>
          <RailLink
            item={{ page: "general", label: "General", changed: generalChanged }}
            active={page === "general"}
            room={room}
          />
          <RailLink item={{ page: "notifications", label: "Notifications" }} active={page === "notifications"} room={room} />
          <RailLink item={{ page: "read-aloud", label: "Read aloud" }} active={page === "read-aloud"} room={room} />
          <RailLink
            item={{ page: "keys", label: "Keyboard shortcuts", changed: keysChanged }}
            active={page === "keys"}
            room={room}
          />
          {!app && <RailLink item={{ page: "connection", label: "Connection" }} active={page === "connection"} room={room} />}
        </RailGroup>
        {app && (
          <RailGroup title={`This ${desktopMachine()}`}>
            {APP_PAGES.map((item) => (
              <RailLink key={item.page} item={item} active={page === item.page} room={room} />
            ))}
          </RailGroup>
        )}
        <RailGroup title="This room">
          <RailLink item={{ page: "room", label: "Room" }} active={page === "room"} room={room} />
        </RailGroup>
        <RailGroup title="This hub">
          <RailLink item={{ page: "hub", label: "Hub" }} active={page === "hub"} room={room} />
        </RailGroup>
      </nav>
      <div className="min-h-0 flex-1 overflow-y-auto">
        {page === "profile" && <ProfilePage />}
        {page === "general" && <GeneralPage />}
        {page === "notifications" && <NotificationsPage />}
        {page === "read-aloud" && <ReadAloudPage />}
        {page === "keys" && <KeysPage />}
        {page === "connection" && <ConnectionPage />}
        {page === "room" && <RoomSettingsPage room={room} />}
        {page === "hub" && <HubPage />}
        {app && page === "model" && <AppModelPage />}
        {app && page === "agents" && <AppAgentsPage />}
        {app && page === "voice" && <AppVoicePage />}
        {app && page === "experiences" && <AppExperiencesPage />}
        {app && page === "privacy" && <AppPrivacyPage />}
        {app && page === "version" && <AppVersionPage />}
        {app && page === "health" && <AppHealthPage />}
      </div>
    </div>
  );
}
