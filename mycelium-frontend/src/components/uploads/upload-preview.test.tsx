// SPDX-License-Identifier: Apache-2.0
// Copyright 2026 Mycelium Contributors

// The preview steps through the files it was opened among, a message's
// attachments, with its arrows or the arrow keys, wrapping at the ends.

import { useState } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import { stepThrough, UploadPreviewDialog } from "@/components/uploads/upload-preview";
import type { Upload } from "@/lib/api";

function image(n: number): Upload {
  return {
    name: `shot-${n}.png`,
    key: `uploads/shot-${n}.png`,
    filename: `shot-${n}.png`,
    kind: "image",
    content_type: "image/png",
    size: 1024,
    sha256: `h${n}`,
    created_by: "julia",
    created_at: "2026-10-09T12:00:00Z",
    url: `/api/rooms/r/uploads/shot-${n}.png`,
  };
}

const SET = [image(1), image(2), image(3)];

describe("stepThrough", () => {
  it("steps forward and back, wrapping at the ends", () => {
    expect(stepThrough(SET, SET[0], 1)?.key).toBe(SET[1].key);
    expect(stepThrough(SET, SET[2], 1)?.key).toBe(SET[0].key);
    expect(stepThrough(SET, SET[0], -1)?.key).toBe(SET[2].key);
  });

  it("has nowhere to go with one file, or one not in the set", () => {
    expect(stepThrough([SET[0]], SET[0], 1)).toBeNull();
    expect(stepThrough(SET, image(9), 1)).toBeNull();
    expect(stepThrough(SET, null, 1)).toBeNull();
  });
});

function Opened({ set, first }: { set: Upload[]; first: Upload }) {
  const [shown, setShown] = useState<Upload | null>(first);
  return <UploadPreviewDialog upload={shown} onClose={() => setShown(null)} set={set} onShow={setShown} />;
}

describe("<UploadPreviewDialog /> in a set", () => {
  it("says where it is and steps with its arrows", async () => {
    const user = userEvent.setup();
    render(<Opened set={SET} first={SET[0]} />);
    expect(screen.getByText("1 of 3")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: "Next file" }));
    expect(screen.getByText("2 of 3")).toBeInTheDocument();
    expect(screen.getByRole("img")).toHaveAttribute("alt", "shot-2.png");

    await user.click(screen.getByRole("button", { name: "Previous file" }));
    await user.click(screen.getByRole("button", { name: "Previous file" }));
    expect(screen.getByText("3 of 3")).toBeInTheDocument();
  });

  it("steps with the arrow keys", () => {
    render(<Opened set={SET} first={SET[1]} />);
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowRight" });
    expect(screen.getByText("3 of 3")).toBeInTheDocument();
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowLeft" });
    fireEvent.keyDown(screen.getByRole("dialog"), { key: "ArrowLeft" });
    expect(screen.getByText("1 of 3")).toBeInTheDocument();
  });

  it("shows no arrows for a single file", () => {
    render(<Opened set={[SET[0]]} first={SET[0]} />);
    expect(screen.queryByRole("button", { name: "Next file" })).toBeNull();
    expect(screen.queryByText(/of 1/)).toBeNull();
  });
});
