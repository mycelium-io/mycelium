import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";

const pairRunner = vi.fn();
const fetchRunnerJob = vi.fn();
const expectPairing = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  pairRunner: (...args: unknown[]) => pairRunner(...args),
  fetchRunnerJob: (...args: unknown[]) => fetchRunnerJob(...args),
  expectPairing: (...args: unknown[]) => expectPairing(...args),
}));
const desktop = { on: false, mode: "hub" };
vi.mock("@/lib/desktop", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/desktop")>()),
  useIsDesktop: () => desktop.on,
}));
// What the app itself says it runs, over its own bridge.
vi.mock("@/lib/desktop-app", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/desktop-app")>()),
  appCall: async (command: string) => (command === "get_state" ? { settings: { mode: desktop.mode } } : null),
}));
const pairRequest = vi.fn();
vi.mock("@/lib/device-key", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/device-key")>()),
  pairRequest: (...args: unknown[]) => pairRequest(...args),
}));

import { ApiError, type RunnerJob } from "@/lib/api";
import { AddMachineDialog } from "./add-machine-dialog";

function job(over: Partial<RunnerJob> = {}): RunnerJob {
  return {
    id: "job-0042",
    runner: "studio-mini",
    kind: "pair",
    spec: {},
    status: "queued",
    result: null,
    error: null,
    created_by: null,
    created_at: "2026-10-01T12:00:00Z",
    updated_at: "2026-10-01T12:00:00Z",
    ...over,
  };
}

const body = { code_id: "K7QM", name: "work laptop", key: { x: "x", y: "y" }, proof: "p" };

function fill(code: string, name = "work laptop") {
  fireEvent.change(screen.getByPlaceholderText("K7QM-4XHD-9RWA"), { target: { value: code } });
  fireEvent.change(screen.getByPlaceholderText("work laptop"), { target: { value: name } });
}

describe("AddMachineDialog", () => {
  beforeEach(() => {
    desktop.on = false;
    pairRunner.mockReset();
    fetchRunnerJob.mockReset();
    desktop.mode = "hub";
    expectPairing.mockReset().mockResolvedValue({ offer: "K7QM", until: "2026-10-01T12:10:00Z" });
    pairRequest.mockReset().mockResolvedValue({ body, keyId: "59802479f5b1936d" });
  });

  it("in the app, lets a machine that isn't connected yet join with the code, then pairs", async () => {
    desktop.on = true;
    const nobody = new ApiError("No machine is waiting to pair with that code.", 404);
    pairRunner.mockRejectedValueOnce(nobody).mockResolvedValue(job());
    fetchRunnerJob.mockResolvedValue(
      job({ status: "done", result: { label: "box", name: "work laptop", key: "59802479f5b1936d" } }),
    );
    renderWithSWR(<AddMachineDialog open onClose={() => {}} />);
    expect(screen.getByText(/--hub http/)).toBeInTheDocument();
    fireEvent.change(screen.getByPlaceholderText("K7QM-4XHD-9RWA"), { target: { value: "K7QM-4XHD-9RWA" } });
    fireEvent.click(screen.getByRole("button", { name: "Pair" }));

    await waitFor(() => expect(expectPairing).toHaveBeenCalledWith("K7QM4XHD9RWA"));
    expect(await screen.findByText("Waiting for the machine to connect…")).toBeInTheDocument();
    expect(await screen.findByText(/Paired with box/, {}, { timeout: 5000 })).toBeInTheDocument();
    expect(pairRunner).toHaveBeenCalledTimes(2);
  });

  it("never sends the code to a hub that isn't the app's own (client mode)", async () => {
    desktop.on = true;
    desktop.mode = "client";
    pairRunner.mockRejectedValue(new ApiError("No machine is waiting to pair with that code.", 404));
    renderWithSWR(<AddMachineDialog open onClose={() => {}} />);
    fireEvent.change(screen.getByPlaceholderText("K7QM-4XHD-9RWA"), { target: { value: "K7QM-4XHD-9RWA" } });
    fireEvent.click(screen.getByRole("button", { name: "Pair" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No machine is waiting");
    expect(expectPairing).not.toHaveBeenCalled();
  });

  it("outside the app, a code no machine is waiting on is just refused", async () => {
    pairRunner.mockRejectedValue(new ApiError("No machine is waiting to pair with that code.", 404));
    renderWithSWR(<AddMachineDialog open onClose={() => {}} />);
    fill("K7QM-4XHD-9RWA");
    fireEvent.click(screen.getByRole("button", { name: "Pair" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("No machine is waiting");
    expect(expectPairing).not.toHaveBeenCalled();
  });

  it("pairs with the code the machine printed and shows the key to compare", async () => {
    pairRunner.mockResolvedValue(job());
    fetchRunnerJob.mockResolvedValue(
      job({ status: "done", result: { label: "studio-mini", name: "work laptop", key: "59802479f5b1936d" } }),
    );
    renderWithSWR(<AddMachineDialog open onClose={() => {}} />);
    expect(screen.getByDisplayValue("mycelium runner pair")).toBeInTheDocument();
    fill("k7qm-4xhd-9rwa");
    fireEvent.click(screen.getByRole("button", { name: "Pair" }));

    await waitFor(() => expect(pairRunner).toHaveBeenCalledWith(body));
    expect(pairRequest).toHaveBeenCalledWith("K7QM4XHD9RWA", "work laptop");
    expect(await screen.findByText(/Paired with studio-mini/)).toBeInTheDocument();
    expect(screen.getByText("5980 2479 f5b1 936d")).toBeInTheDocument();
  });

  it("won't send something that isn't a code", () => {
    renderWithSWR(<AddMachineDialog open onClose={() => {}} />);
    fill("ABCD-EFGH");
    expect(screen.getByRole("button", { name: "Pair" })).toBeDisabled();
  });

  it("says why the machine refused", async () => {
    pairRunner.mockResolvedValue(job());
    fetchRunnerJob.mockResolvedValue(
      job({ status: "failed", error: "That code is wrong. Check it on the machine and try again." }),
    );
    renderWithSWR(<AddMachineDialog open onClose={() => {}} />);
    fill("K7QM-4XHD-9RWA");
    fireEvent.click(screen.getByRole("button", { name: "Pair" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("That code is wrong");
  });

  it("adds a machine you use by its id instead", () => {
    renderWithSWR(<AddMachineDialog open onClose={() => {}} />);
    fireEvent.click(screen.getByRole("tab", { name: /Add a machine/ }));
    expect(screen.getByDisplayValue("mycelium runner")).toBeInTheDocument();
    expect(screen.getByPlaceholderText("morgans-mbp-3f2a")).toBeInTheDocument();
  });
});
