// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { useAuthSession } from "@/components/auth-session";
import { useCurrentUser } from "@/components/current-user";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Monogram } from "@/components/ui/monogram";
import { createUser, logFetchError } from "@/lib/api";
import { useRefreshUsers, useUsers } from "@/lib/people";
import { Note, Row, Section, SettingsPage } from "./settings-ui";

const HANDLE = /^[a-z0-9][a-z0-9._-]*$/;

/** Who you are here: the name everyone sees on your messages (kept on the hub,
 *  in its user store) and which handle this browser acts as (kept here). */
export function ProfilePage() {
  const { principal, setPrincipal } = useCurrentUser();
  const { signedIn, handle: sessionHandle } = useAuthSession();
  const me = signedIn ? (sessionHandle ?? principal) : principal;
  const { users } = useUsers();
  const refresh = useRefreshUsers();
  const record = users.find((u) => u.handle === me);

  const [name, setName] = useState("");
  const [nameState, setNameState] = useState<"idle" | "saving" | "saved">("idle");
  const [error, setError] = useState<string | null>(null);
  const [handle, setHandle] = useState("");
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- seeded once the hub's record arrives
    if (record) setName((n) => n || record.display_name);
  }, [record]);
  useEffect(() => {
    // eslint-disable-next-line react-hooks/set-state-in-effect -- follows the identity this browser acts as
    setHandle(me);
  }, [me]);

  const saveName = async () => {
    if (!me) return;
    setNameState("saving");
    setError(null);
    try {
      await createUser({
        handle: me,
        display_name: name.trim(),
        teams: record?.teams ?? [],
        notify: record?.notify ?? null,
      });
      refresh();
      setNameState("saved");
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
      setNameState("idle");
    }
  };

  const nextHandle = handle.trim().replace(/^@/, "").toLowerCase();
  const switchHandle = async () => {
    if (!HANDLE.test(nextHandle)) {
      setError("A handle is lowercase letters, digits, dots, dashes and underscores.");
      return;
    }
    setError(null);
    if (!users.some((u) => u.handle === nextHandle)) {
      try {
        await createUser({ handle: nextHandle });
      } catch (err) {
        // The handle still works in this browser; the hub record can follow.
        logFetchError("createUser")(err);
      }
      refresh();
    }
    setPrincipal(nextHandle);
  };

  return (
    <SettingsPage title="Profile" scope="Your name is kept on the hub, so everyone sees it. Which handle is you is kept in this browser.">
      <Section title="You">
        <Row
          id="profile.name"
          label="Name"
          help="Shown beside your messages, in place of your handle."
          below={error ? <Note tone="error">{error}</Note> : nameState === "saved" ? <Note>Saved.</Note> : null}
        >
          {me && <Monogram handle={me} />}
          <Input
            aria-label="Name"
            value={name}
            placeholder="e.g. Avery Quinn"
            onChange={(e) => {
              setName(e.target.value);
              setNameState("idle");
            }}
            className="h-8 w-48"
            disabled={!me}
          />
          <Button
            size="sm"
            variant="outline"
            onClick={saveName}
            disabled={!me || nameState === "saving" || name.trim() === (record?.display_name ?? "")}
          >
            Save
          </Button>
        </Row>
        <Row
          id="profile.handle"
          label="This browser is you as"
          help={
            signedIn
              ? "You're signed in, so your handle comes from your sign-in."
              : "Anyone can pick a handle while the hub has sign-in off. Messages you send here are from this handle."
          }
        >
          <Input
            aria-label="Handle"
            value={handle}
            onChange={(e) => setHandle(e.target.value)}
            placeholder="your-handle"
            className="h-8 w-40 font-mono text-micro"
            disabled={signedIn}
          />
          {!signedIn && (
            <Button size="sm" variant="outline" onClick={switchHandle} disabled={!nextHandle || nextHandle === me}>
              Switch
            </Button>
          )}
        </Row>
      </Section>

      <Section title="Agents you own">
        {!record || record.owns.length === 0 ? (
          <Row
            label="None yet"
            help="An agent you start from a room's Add member, or one created with you as its owner, is listed here."
          />
        ) : (
          record.owns.map((a) => (
            <Row
              key={`${a.room}/${a.handle}`}
              label={<span className="font-mono text-micro">@{a.handle}</span>}
              help={`${a.adapter}${a.team ? ` · ${a.team}` : ""}`}
            >
              <Link href={`/room/${encodeURIComponent(a.room)}`} className="text-micro text-accent hover:underline">
                {a.room}
              </Link>
            </Row>
          ))
        )}
      </Section>
    </SettingsPage>
  );
}
