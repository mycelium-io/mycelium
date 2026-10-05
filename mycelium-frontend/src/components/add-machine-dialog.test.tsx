import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, screen, waitFor } from "@testing-library/react";
import { renderWithSWR } from "@/test/swr";

const pairRunner = vi.fn();
const fetchRunnerJob = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  pairRunner: (...args: unknown[]) => pairRunner(...args),
  fetchRunnerJob: (...args: unknown[]) => fetchRunnerJob(...args),
}));
const pairRequest = vi.fn();
vi.mock("@/lib/device-key", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/device-key")>()),
  pairRequest: (...args: unknown[]) => pairRequest(...args),
}));

import type { RunnerJob } from "@/lib/api";
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
    pairRunner.mockReset();
    fetchRunnerJob.mockReset();
    pairRequest.mockReset().mockResolvedValue({ body, keyId: "59802479f5b1936d" });
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
