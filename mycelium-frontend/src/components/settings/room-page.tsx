// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";
import { useCurrentUser } from "@/components/current-user";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select } from "@/components/ui/select";
import {
  resetRoomSetting,
  setRoomPrivate,
  setRoomSetting,
  setRoomTitle,
  type RoomSetting,
} from "@/lib/api";
import { settingHref } from "@/lib/client-settings";
import { useRoom, useRoomSettings, useRooms } from "@/lib/room-data";
import { ROOM_SETTINGS, type RoomSettingCopy } from "@/lib/room-settings";
import { RoomConnection } from "./room-connection";
import { CheckChips, Confirm, Note, Row, Section, Segmented, SettingsPage, Toggle } from "./settings-ui";

function describeValue(copy: RoomSettingCopy, value: unknown): string {
  if (copy.kind === "bool") return value ? "on" : "off";
  if (copy.kind === "set" && Array.isArray(value)) {
    return value.map((v) => copy.optionLabels?.[v] ?? v).join(", ") || "none";
  }
  return String(value);
}

/** Who set a room setting, and when, from its memory. */
function provenance(s: RoomSetting): string | null {
  if (s.source !== "room") return null;
  const who = s.updated_by ? `@${s.updated_by.replace(/^@/, "")}` : "someone";
  const when = s.updated_at ? new Date(s.updated_at).toLocaleDateString() : null;
  return `Set by ${who}${when ? ` on ${when}` : ""}${s.version ? ` · version ${s.version}` : ""}`;
}

function SettingRow({
  room,
  copy,
  setting,
  onSaved,
}: {
  room: string;
  copy: RoomSettingCopy;
  setting: RoomSetting | undefined;
  onSaved: () => void;
}) {
  const { principal } = useCurrentUser();
  const [error, setError] = useState<string | null>(null);
  const [draft, setDraft] = useState<string | null>(null);
  if (!setting) return <Row id={copy.id} label={copy.label} help={copy.help} />;

  const write = async (value: unknown) => {
    setError(null);
    try {
      await setRoomSetting(room, copy.id, value, principal, setting.version);
      setDraft(null);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };
  const reset = async () => {
    setError(null);
    try {
      await resetRoomSetting(room, copy.id);
      setDraft(null);
      onSaved();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    }
  };

  const inherited = setting.source !== "room";
  const fromHub = setting.inherits !== null;
  const defaultLabel = fromHub
    ? `the hub's, ${describeValue(copy, setting.hub_value)}`
    : describeValue(copy, setting.hub_value);
  const memoryKey = `settings/${copy.id}`;
  const by = provenance(setting);

  return (
    <Row
      id={copy.id}
      label={copy.label}
      help={copy.help}
      changed={!inherited}
      onReset={reset}
      defaultLabel={defaultLabel}
      tag={fromHub && inherited ? "from the hub" : undefined}
      below={
        <>
          {by && (
            <p className="mt-1 text-micro text-faint">
              {by}
              {setting.reason ? ` · “${setting.reason}”` : ""} ·{" "}
              <Link
                href={`/room/${encodeURIComponent(room)}/memory/${memoryKey}`}
                className="text-accent hover:underline"
              >
                History and discussion
              </Link>
            </p>
          )}
          {error && <Note tone="error">{error}</Note>}
        </>
      }
    >
      {copy.kind === "bool" && (
        <Toggle label={copy.label} checked={Boolean(setting.value)} onChange={(v) => void write(v)} />
      )}
      {copy.kind === "set" && (
        <CheckChips
          label={copy.label}
          value={Array.isArray(setting.value) ? (setting.value as string[]) : []}
          options={(copy.options ?? []).map((o) => ({ value: o, label: copy.optionLabels?.[o] ?? o }))}
          onChange={(v) => void write(v)}
        />
      )}
      {copy.kind === "int" && (
        <>
          <Input
            type="number"
            aria-label={copy.label}
            min={setting.min ?? undefined}
            max={setting.max ?? undefined}
            value={draft ?? (inherited ? "" : String(setting.value))}
            placeholder={inherited ? `${String(setting.value)} · hub's value` : undefined}
            onChange={(e) => setDraft(e.target.value)}
            className="h-8 w-36 placeholder:italic"
          />
          <Button
            size="sm"
            variant="outline"
            disabled={draft === null || draft === "" || Number(draft) === setting.value}
            onClick={() => void write(Number(draft))}
          >
            {inherited ? "Set for this room" : "Save"}
          </Button>
        </>
      )}
    </Row>
  );
}

/** One room's own settings. The values live in the room as memories under
 *  `settings/`, so they are versioned, discussed and readable by agents; the
 *  hub checks every one against its table, here and from the CLI alike. */
export function RoomSettingsPage({ room: asked }: { room: string | null }) {
  const router = useRouter();
  const { principal } = useCurrentUser();
  const { rooms, refresh: refreshRooms } = useRooms();
  const room = asked ?? rooms[0]?.name ?? "";
  // Without a room named, open the first one so the address says which it is.
  useEffect(() => {
    if (!asked && room) router.replace(settingHref("room", undefined, room));
  }, [asked, room, router]);
  const { room: info, refresh: refreshRoom } = useRoom(room);
  const { settings, refresh } = useRoomSettings(room);
  const [title, setTitle] = useState<string | null>(null);
  const [titleError, setTitleError] = useState<string | null>(null);
  const [confirmPrivate, setConfirmPrivate] = useState(false);
  const [busy, setBusy] = useState(false);
  const [visibilityError, setVisibilityError] = useState<string | null>(null);

  if (!room) {
    return (
      <SettingsPage title="Room" scope="Shared with everyone in the room.">
        <Note>There are no rooms yet. Create one from the rooms list.</Note>
      </SettingsPage>
    );
  }

  const isPrivate = info ? !info.is_public : false;
  const shownTitle = title ?? info?.title ?? "";

  const saveTitle = async () => {
    setTitleError(null);
    try {
      await setRoomTitle(room, shownTitle.trim());
      setTitle(null);
      refreshRoom();
      refreshRooms();
    } catch (err) {
      setTitleError(err instanceof Error ? err.message : String(err));
    }
  };
  const changeVisibility = async (makePrivate: boolean) => {
    setBusy(true);
    setVisibilityError(null);
    try {
      await setRoomPrivate(room, makePrivate, principal);
      setConfirmPrivate(false);
      refreshRoom();
      refreshRooms();
    } catch (err) {
      setVisibilityError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(false);
    }
  };

  const sections = ["Chat", "Board", "Agents"] as const;

  return (
    <SettingsPage
      title={
        <span className="flex items-center gap-1.5">
          Room ·
          <Select
            aria-label="Which room"
            value={room}
            onChange={(e) => router.push(settingHref("room", undefined, e.target.value))}
            variant="ghost"
            selectClassName="font-medium text-[length:inherit] [field-sizing:content]"
          >
            {rooms.map((r) => (
              <option key={r.name} value={r.name}>
                {r.name}
              </option>
            ))}
            {!rooms.some((r) => r.name === room) && <option value={room}>{room}</option>}
          </Select>
        </span>
      }
      scope="Shared with everyone in this room, and kept in the room as memories under settings/."
      actions={
        <Link href={`/room/${encodeURIComponent(room)}`} className="text-micro text-accent hover:underline">
          Open the room
        </Link>
      }
    >
      <Section title="The room">
        <Row
          id="room.title"
          label="Name"
          help="Shown above the room instead of its address."
          below={titleError ? <Note tone="error">{titleError}</Note> : null}
        >
          <Input
            aria-label="Room name"
            value={shownTitle}
            placeholder={room}
            onChange={(e) => setTitle(e.target.value)}
            className="h-8 w-56"
          />
          <Button size="sm" variant="outline" disabled={title === null} onClick={() => void saveTitle()}>
            Save
          </Button>
        </Row>
        <Row
          id="room.visibility"
          label="Who can see it"
          help={
            isPrivate
              ? "Listed only for its owner and members."
              : "Listed for everyone on this hub."
          }
          below={
            <>
              {confirmPrivate && (
                <Confirm
                  title={`Make ${room} private?`}
                  confirmLabel="Make private"
                  busy={busy}
                  onConfirm={() => void changeVisibility(true)}
                  onCancel={() => setConfirmPrivate(false)}
                >
                  It disappears from everyone else&apos;s rooms list. Its members, and agents already in it, keep
                  working.
                </Confirm>
              )}
              {visibilityError && <Note tone="error">{visibilityError}</Note>}
            </>
          }
        >
          <Segmented
            label="Who can see it"
            value={isPrivate ? "private" : "shared"}
            options={[
              { value: "shared", label: "Shared" },
              { value: "private", label: "Private" },
            ]}
            onChange={(v) => {
              if (v === "private" && !isPrivate) {
                if (!principal) {
                  setVisibilityError("Pick who you are in Profile first: a private room is listed for its owner.");
                  return;
                }
                setConfirmPrivate(true);
              } else if (v === "shared" && isPrivate) {
                void changeVisibility(false);
              }
            }}
          />
        </Row>
      </Section>

      {sections.map((section) => (
        <Section key={section} title={section}>
          {ROOM_SETTINGS.filter((c) => c.section === section).map((copy) => (
            <SettingRow
              key={copy.id}
              room={room}
              copy={copy}
              setting={settings.find((s) => s.id === copy.id)}
              onSaved={refresh}
            />
          ))}
        </Section>
      ))}

      <RoomConnection room={room} />
    </SettingsPage>
  );
}
