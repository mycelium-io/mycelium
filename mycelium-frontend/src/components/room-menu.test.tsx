import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";

vi.mock("next/navigation", () => ({ useRouter: () => ({ push: vi.fn() }) }));
vi.mock("@/lib/api", () => ({ deleteRoom: vi.fn() }));

import { RoomMenu } from "./room-menu";

describe("RoomMenu", () => {
  it("keeps the room's id and deleting it behind the menu", async () => {
    render(<RoomMenu roomName="atlas" masId="mas_7c1e9a2b" />);
    expect(screen.queryByText("mas_7c1e9a2b")).not.toBeInTheDocument();

    fireEvent.click(screen.getByRole("button", { name: "atlas options" }));
    expect(await screen.findByText("mas_7c1e9a2b")).toBeInTheDocument();

    fireEvent.click(screen.getByText("Delete room…"));
    expect(await screen.findByRole("dialog")).toBeInTheDocument();
  });

  it("offers no id to copy for a room without one", async () => {
    render(<RoomMenu roomName="atlas" masId={null} />);
    fireEvent.click(screen.getByRole("button", { name: "atlas options" }));
    expect(await screen.findByText("Delete room…")).toBeInTheDocument();
    expect(screen.queryByText("Copy room id")).not.toBeInTheDocument();
  });
});
