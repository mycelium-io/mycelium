import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api", () => ({
  deleteRoom: vi.fn(),
  fetchRooms: vi.fn().mockResolvedValue([]),
  setRoomPrivate: vi.fn().mockResolvedValue({}),
}));

import { RoomMenu } from "./room-menu";
import { setRoomPrivate } from "@/lib/api";

describe("RoomMenu", () => {
  it("keeps the room's id and deleting it behind the menu", async () => {
    render(<RoomMenu roomName="atlas" masId="mas_7c1e9a2b" />);
    expect(screen.queryByText("mas_7c1e9a2b")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "atlas options" }));
    expect(await screen.findByText("mas_7c1e9a2b")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Delete room…"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("copies a link to what's open, which the Mac app has no address bar for", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined);
    Object.assign(navigator, { clipboard: { writeText } });
    window.history.pushState({}, "", "/room/atlas?task=work%2Fship-it");
    render(<RoomMenu roomName="atlas" masId={null} />);
    fireEvent.click(screen.getByRole("button", { name: "atlas options" }));

    fireEvent.click(await screen.findByText("Copy link"));
    await waitFor(() =>
      expect(writeText).toHaveBeenCalledWith(`${window.location.origin}/room/atlas?task=work%2Fship-it`),
    );
    expect(await screen.findByText("Copied")).toBeInTheDocument();
  });

  it("offers no id to copy for a room without one", async () => {
    render(<RoomMenu roomName="atlas" masId={null} />);
    fireEvent.click(screen.getByRole("button", { name: "atlas options" }));
    expect(await screen.findByText("Delete room…")).toBeInTheDocument();
    expect(screen.queryByText("Copy room id")).not.toBeInTheDocument();
  });

  it("can't make a room private for nobody", async () => {
    render(<RoomMenu roomName="atlas" masId={null} />);
    fireEvent.click(screen.getByRole("button", { name: "atlas options" }));
    await screen.findByText("Delete room…");
    expect(screen.queryByText("Make private")).not.toBeInTheDocument();
  });

  it("shares a private room again", async () => {
    const onChanged = vi.fn();
    render(<RoomMenu roomName="atlas" masId={null} isPrivate onChanged={onChanged} />);
    fireEvent.click(screen.getByRole("button", { name: "atlas options" }));
    fireEvent.click(await screen.findByText("Share with everyone"));

    await waitFor(() => expect(onChanged).toHaveBeenCalled());
    expect(setRoomPrivate).toHaveBeenCalledWith("atlas", false, "");
  });
});
