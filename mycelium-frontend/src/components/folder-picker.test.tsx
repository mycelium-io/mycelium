import { beforeEach, describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen, waitFor } from "@testing-library/react";

const listRunnerFolders = vi.fn();
vi.mock("@/lib/api", async (importOriginal) => ({
  ...(await importOriginal<typeof import("@/lib/api")>()),
  listRunnerFolders: (...args: unknown[]) => listRunnerFolders(...args),
}));

import type { Runner, RunnerFolders } from "@/lib/api";
import { FolderPicker, crumbs } from "./folder-picker";

const ROOT = "/Users/morgan/code";
const runner = { id: "mbp", label: "morgans-mbp", roots: [ROOT] } as unknown as Runner;

function listing(path: string, folders: string[]): RunnerFolders {
  return { path, root: ROOT, folders, truncated: false };
}

describe("crumbs", () => {
  it("runs from the root, shown with ~, down to the folder", () => {
    expect(crumbs(ROOT, `${ROOT}/shop/api`)).toEqual([
      { name: "~/code", path: ROOT },
      { name: "shop", path: `${ROOT}/shop` },
      { name: "api", path: `${ROOT}/shop/api` },
    ]);
    expect(crumbs(ROOT, ROOT)).toEqual([{ name: "~/code", path: ROOT }]);
  });
});

describe("FolderPicker", () => {
  beforeEach(() => {
    listRunnerFolders.mockReset();
  });

  it("opens at the root, goes into a folder, and picks it", async () => {
    listRunnerFolders.mockImplementation(async (_id: string, path?: string) =>
      path === `${ROOT}/shop` ? listing(`${ROOT}/shop`, ["api", "web"]) : listing(ROOT, ["shop", "tools"]),
    );
    const onPick = vi.fn();
    render(<FolderPicker runner={runner} value="" onPick={onPick} />);

    fireEvent.click(screen.getByRole("button", { name: "Browse folders" }));
    // Nothing typed inside a root: the machine's first root.
    await screen.findByRole("button", { name: "tools" });
    expect(listRunnerFolders).toHaveBeenLastCalledWith("mbp", undefined);

    fireEvent.click(screen.getByRole("button", { name: "shop" }));
    await screen.findByRole("button", { name: "web" });
    expect(listRunnerFolders).toHaveBeenLastCalledWith("mbp", `${ROOT}/shop`);

    fireEvent.click(screen.getByRole("button", { name: "Use this folder" }));
    expect(onPick).toHaveBeenCalledWith(`${ROOT}/shop`);
  });

  it("opens at the folder already typed", async () => {
    listRunnerFolders.mockResolvedValue(listing(`${ROOT}/shop`, []));
    render(<FolderPicker runner={runner} value={`${ROOT}/shop`} onPick={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Browse folders" }));
    await screen.findByText("No folders in here.");
    expect(listRunnerFolders).toHaveBeenCalledWith("mbp", `${ROOT}/shop`);
    // The breadcrumb goes back up to the root.
    expect(screen.getByRole("button", { name: "~/code" })).toBeInTheDocument();
  });

  it("says to update a machine whose runner can't list folders yet", async () => {
    listRunnerFolders.mockImplementation(async () => {
      throw new Error("this runner doesn't know how to do 'folders'; update mycelium here.");
    });
    render(<FolderPicker runner={runner} value="" onPick={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Browse folders" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        "Update Mycelium on morgans-mbp to browse its folders. You can still type a path.",
      ),
    );
    expect(screen.getByRole("button", { name: "Use this folder" })).toBeDisabled();
  });
});
