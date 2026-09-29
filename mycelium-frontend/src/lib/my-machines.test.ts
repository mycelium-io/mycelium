import { beforeEach, describe, expect, it } from "vitest";
import { act, renderHook } from "@testing-library/react";
import { addMachine, forgetMachine, takeMachineFromUrl, useMyMachines } from "./my-machines";

describe("my machines", () => {
  beforeEach(() => {
    window.localStorage.clear();
    window.history.replaceState(null, "", "/");
  });

  it("remembers the machine the app names in the URL, and takes it out of the address", () => {
    window.history.replaceState(null, "", "/room/atlas?tab=board&machine=julias-mbp-3f2a");
    const { result } = renderHook(() => useMyMachines());
    act(() => takeMachineFromUrl());
    expect(result.current).toEqual(["julias-mbp-3f2a"]);
    expect(window.location.pathname + window.location.search).toBe("/room/atlas?tab=board");
  });

  it("adds a machine once by its code, and forgets it", () => {
    const { result } = renderHook(() => useMyMachines());
    act(() => {
      addMachine("  julias-mbp-3f2a ");
      addMachine("julias-mbp-3f2a");
      addMachine("");
    });
    expect(result.current).toEqual(["julias-mbp-3f2a"]);
    act(() => forgetMachine("julias-mbp-3f2a"));
    expect(result.current).toEqual([]);
  });

  it("reads storage it can't parse as no machines", () => {
    window.localStorage.setItem("mycelium.machines", "{not json");
    const { result } = renderHook(() => useMyMachines());
    expect(result.current).toEqual([]);
  });
});
