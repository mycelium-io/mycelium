# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""herdr's tabs and pane sizes, as ``HerdrBridge.place_pane`` reads them.

Each pane is a rectangle of cells; a split halves the pane it splits, as herdr
does at its default ratio. A test's own herdr stand-in hands the calls about
tabs and layout to :meth:`HerdrLayout.answer` and tells it which panes it opened.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable


class HerdrLayout:
    def __init__(
        self,
        new_pane: Callable[[str], str] | None = None,
        *,
        width: int = 200,
        height: int = 50,
    ) -> None:
        self.size = (width, height)
        self.tabs: dict[str, dict] = {}
        self.panes: dict[str, dict] = {}
        self._new_pane = new_pane or self._numbered
        self._count = 0

    def _numbered(self, workspace: str) -> str:
        self._count += 1
        return f"{workspace}:p{self._count}"

    def open_tab(self, workspace: str, pane: str, label: str | None = None) -> str:
        """A new tab in ``workspace`` holding ``pane``, the whole window."""
        number = sum(t["workspace"] == workspace for t in self.tabs.values()) + 1
        tab = f"{workspace}:t{number}"
        self.tabs[tab] = {"workspace": workspace, "number": number, "label": label or str(number)}
        width, height = self.size
        self.panes[pane] = {"tab": tab, "rect": {"x": 0, "y": 0, "width": width, "height": height}}
        return tab

    def split(self, parent: str, pane: str, direction: str) -> None:
        """Halve ``parent``, the new ``pane`` to its right or below it."""
        rect = self.panes[parent]["rect"]
        new = dict(rect)
        if direction == "right":
            rect["width"], new["width"] = rect["width"] - rect["width"] // 2, rect["width"] // 2
            new["x"] = rect["x"] + rect["width"]
        else:
            rect["height"], new["height"] = (
                rect["height"] - rect["height"] // 2,
                rect["height"] // 2,
            )
            new["y"] = rect["y"] + rect["height"]
        self.panes[pane] = {"tab": self.panes[parent]["tab"], "rect": new}

    def tab_of(self, pane: str) -> str:
        """``pane``'s tab; one herdr opened before this layout knew of it is in its first."""
        known = self.panes.get(pane)
        return known["tab"] if known else f"{pane.split(':')[0]}:t1"

    def in_tab(self, tab: str) -> list[str]:
        return [p for p, v in self.panes.items() if v["tab"] == tab]

    def answer(self, args: list[str]) -> dict | None:
        """herdr's ``result`` for a call about tabs or layout; ``None`` for any other."""
        head = " ".join(args[:2])
        if head == "workspace create":
            workspace = f"w{len({t['workspace'] for t in self.tabs.values()}) + 9}"
            pane = self._new_pane(workspace)
            tab = self.open_tab(workspace, pane)
            return {
                "workspace": {"workspace_id": workspace},
                "tab": {"tab_id": tab},
                "root_pane": {"pane_id": pane},
            }
        if head == "pane split":
            parent = args[2]
            pane = self._new_pane(parent.split(":")[0])
            self.split(parent, pane, args[args.index("--direction") + 1])
            return {"pane": {"pane_id": pane}}
        if head == "tab create":
            workspace = args[args.index("--workspace") + 1]
            label = args[args.index("--label") + 1] if "--label" in args else None
            pane = self._new_pane(workspace)
            tab = self.open_tab(workspace, pane, label)
            return {"tab": {"tab_id": tab}, "root_pane": {"pane_id": pane}}
        if head == "tab list":
            workspace = args[args.index("--workspace") + 1] if "--workspace" in args else None
            return {
                "tabs": [
                    {
                        "tab_id": tab,
                        "workspace_id": t["workspace"],
                        "number": t["number"],
                        "label": t["label"],
                        "pane_count": len(self.in_tab(tab)),
                    }
                    for tab, t in self.tabs.items()
                    if workspace in (None, t["workspace"])
                ]
            }
        if head == "tab rename":
            self.tabs[args[2]]["label"] = args[3]
            return {}
        if head == "pane layout":
            tab = self.tab_of(args[args.index("--pane") + 1])
            return {
                "layout": {
                    "tab_id": tab,
                    "panes": [
                        {"pane_id": p, "rect": self.panes[p]["rect"]} for p in self.in_tab(tab)
                    ],
                }
            }
        if head == "pane list":
            return {
                "panes": [
                    {
                        "pane_id": p,
                        "workspace_id": self.tabs[v["tab"]]["workspace"],
                        "tab_id": v["tab"],
                    }
                    for p, v in self.panes.items()
                ]
            }
        return None
