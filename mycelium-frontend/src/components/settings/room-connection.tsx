// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { RoomA2aView } from "@/components/room-a2a";
import { useNetworkStatus } from "@/lib/room-data";
import { Note, Row, Section } from "./settings-ui";

/** How this room is connected: whether the hub that keeps it answers, and
 *  any agents it bridges over A2A. Read-only. */
export function RoomConnection({ room }: { room: string }) {
  const { network, loading } = useNetworkStatus();

  return (
    <>
    <Section
      title="Connection"
      note="The hub keeps the room's messages. Agents and people in the room read and write them through the hub."
    >
      {!loading && !network && <Row label="The hub isn't answering" />}
      <div className="empty:hidden [&>*]:border-b-0">
        <RoomA2aView roomName={room} />
      </div>
    </Section>
    <Note>
      To see a message as the hub sent it, right-click it in the chat and choose View raw message.
    </Note>
    </>
  );
}
