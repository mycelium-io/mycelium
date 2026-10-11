// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

"use client";

import { RoomA2aView } from "@/components/room-a2a";
import { useNetworkStatus } from "@/lib/room-data";
import { Note, Row, Section, Value } from "./settings-ui";

/** How this room is connected: its encrypted channel on the hub's messaging
 *  node, who is on it, and anything waiting or failing. Read-only. The node
 *  itself (its address and how many rooms it carries) is on the Hub page. */
export function RoomConnection({ room }: { room: string }) {
  const { network, loading } = useNetworkStatus();
  const coord = network?.coordination ?? null;
  const channel = coord?.rooms.find((r) => r.room === room) ?? null;

  return (
    <>
    <Section
      title="Connection"
      note="Each room is an encrypted group channel on the hub's messaging node. Agents and people in the room are members of it."
    >
      {!loading && !network && <Row label="The hub isn't answering" />}
      {network && !coord?.slim_enabled && (
        <Row label="Channel" help="This hub runs without its messaging node, so the room has no channel.">
          <Value risk>off</Value>
        </Row>
      )}
      {coord?.slim_enabled && (
        <>
          <Row
            id="room.channel"
            label="Channel"
            help={
              channel?.provisioned
                ? "Set up on the messaging node, and carrying messages."
                : "Not set up yet. It's set up when someone first posts or joins."
            }
          >
            <Value risk={Boolean(channel) && !channel?.provisioned}>
              {channel ? (channel.provisioned ? "live" : "pending") : "not set up"}
            </Value>
          </Row>
          <Row
            id="room.channel-members"
            label="On the channel now"
            help={
              channel && channel.members.length > 0
                ? channel.members.map((m) => `@${m}`).join(", ")
                : "Nobody is connected to the channel. Agents waiting for their next turn are held by the hub instead."
            }
          >
            <Value>{channel?.members.length ?? 0}</Value>
          </Row>
          <Row
            label="Coordination running"
            help="Whether a negotiation or a flow is going on in the room right now."
          >
            <Value>{channel?.episode_active ? "yes" : "no"}</Value>
          </Row>
          {(channel?.deferred_invites ?? 0) > 0 && (
            <Row label="Invites waiting" help="Members invited to the channel who haven't joined it yet.">
              <Value risk>{channel?.deferred_invites}</Value>
            </Row>
          )}
          {(channel?.receive_errors ?? 0) > 0 && (
            <Row label="Messages that failed to arrive" help="Messages the hub couldn't read off the channel.">
              <Value risk>{channel?.receive_errors}</Value>
            </Row>
          )}
        </>
      )}
      <div className="empty:hidden [&>*]:border-b-0">
        <RoomA2aView roomName={room} />
      </div>
    </Section>
    <Note>
      To see a message as the hub sent it, right-click it in the chat and choose View raw message, or add the
      Raw messages tab from the + beside the room&apos;s tabs.
    </Note>
    </>
  );
}
