// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// Contract drift guard for the thread/ping wire constants (frontend side).
//
// The backend produces a ping (`room_channels.raise_ping`), the CLI reads one
// (`mycelium.slim.l9.ping_of`), and this is the third reader. All three carry
// their own copy — the frontend's Docker build context is mycelium-frontend/
// only, so it cannot import the repo root at runtime — and each asserts its copy
// against contracts/slim-l9-wire.json here. Rename the payload type on one side
// alone and the room silently stops hearing that its threads have moved.

import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import {
  LIVE_SESSION,
  NOTICE_PAYLOAD_TYPE,
  NOTICE_SUBKINDS,
  PING_PAYLOAD_FIELDS,
  PING_PAYLOAD_TYPE,
  liveEpisodeUrn,
} from "@/lib/threads";

const CONTRACT_PATH = path.resolve(__dirname, "../../../contracts/slim-l9-wire.json");

function contract(): {
  ping: { payload_type: string; payload_fields: string[] };
  notice: { payload_type: string; subkinds: string[] };
  urn: { room: string; session: string; expected_episode: string };
} {
  return JSON.parse(readFileSync(CONTRACT_PATH, "utf-8"));
}

describe("thread wire constants contract", () => {
  it("mints the room's live-episode URN the way the backend and CLI do", () => {
    const { urn } = contract();
    expect(LIVE_SESSION).toBe(urn.session);
    expect(liveEpisodeUrn(urn.room)).toBe(urn.expected_episode);
  });

  it("reads the contracted ping payload type and fields", () => {
    const { ping } = contract();
    expect(PING_PAYLOAD_TYPE).toBe(ping.payload_type);
    expect([...PING_PAYLOAD_FIELDS]).toEqual(ping.payload_fields);
  });

  it("reads the contracted notice payload type and subkinds", () => {
    const { notice } = contract();
    expect(NOTICE_PAYLOAD_TYPE).toBe(notice.payload_type);
    expect([...NOTICE_SUBKINDS]).toEqual(notice.subkinds);
  });
});
