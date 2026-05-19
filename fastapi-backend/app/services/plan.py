# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Plan view over the ``plan/`` namespace of a room.

A plan is a set of markdown files under ``.mycelium/rooms/{room}/plan/`` plus
the todo lines (``- [ ]`` / ``- [x]``) embedded in those files.  Plan files are
stored using the same markdown-with-frontmatter convention as memories, so the
existing ``write_memory_file`` / ``read_memory_file`` helpers handle persistence.

This module is the read projection + the in-place task mutator.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from app.services.filesystem import get_room_dir, parse_memory

PLAN_DIR = "plan"
DEFAULT_TASK_FILE = "tasks"  # plan/tasks.md

# Matches a markdown task line, capturing the leading indentation, the
# checkbox state, and the body text.
#   "- [ ] do the thing"
#   "  * [x] done"
_TASK_RE = re.compile(r"^(?P<indent>\s*)[-*]\s+\[(?P<mark>[ xX])\]\s+(?P<body>.*)$")


@dataclass(frozen=True)
class PlanTask:
    """A single checkbox line inside a plan file."""

    id: str  # "<slug>:<line>" — stable as long as the file isn't reflowed
    slug: str  # plan key without the "plan/" prefix
    line: int  # 1-indexed line number in the source file's body
    text: str
    done: bool


@dataclass
class PlanFile:
    """One markdown file under plan/."""

    slug: str  # key without "plan/" prefix or ".md"
    title: str  # first markdown heading, else slug
    content: str  # body without frontmatter
    updated_at: str | None
    updated_by: str | None
    tasks: list[PlanTask]


def _plan_dir(room_name: str) -> Path:
    return get_room_dir(room_name) / PLAN_DIR


def _slug_from_path(file_path: Path, base: Path) -> str:
    rel = file_path.relative_to(base)
    s = str(rel)
    return s[:-3] if s.endswith(".md") else s


def _first_heading(content: str) -> str | None:
    for line in content.splitlines():
        stripped = line.lstrip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip() or None
    return None


def parse_tasks(slug: str, content: str) -> list[PlanTask]:
    """Extract ``- [ ]`` / ``- [x]`` lines from a markdown body.

    Line numbers are 1-indexed against the body (i.e. excluding frontmatter).
    """
    tasks: list[PlanTask] = []
    for i, line in enumerate(content.splitlines(), start=1):
        m = _TASK_RE.match(line)
        if not m:
            continue
        done = m.group("mark").lower() == "x"
        tasks.append(
            PlanTask(
                id=f"{slug}:{i}",
                slug=slug,
                line=i,
                text=m.group("body").strip(),
                done=done,
            )
        )
    return tasks


def load_plan(room_name: str) -> tuple[list[PlanFile], list[PlanTask]]:
    """Read every ``plan/*.md`` file in the room and return files + flat tasks.

    Files are sorted alphabetically by slug; tasks follow file order then
    appearance order, so IDs are stable across reads.
    """
    base = _plan_dir(room_name)
    if not base.exists():
        return [], []

    files: list[PlanFile] = []
    all_tasks: list[PlanTask] = []
    for path in sorted(base.rglob("*.md")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            continue
        meta, body = parse_memory(text)
        slug = _slug_from_path(path, base)
        tasks = parse_tasks(slug, body)
        files.append(
            PlanFile(
                slug=slug,
                title=_first_heading(body) or slug,
                content=body,
                updated_at=str(meta.get("updated_at")) if meta.get("updated_at") else None,
                updated_by=str(meta.get("updated_by") or meta.get("created_by") or "") or None,
                tasks=tasks,
            )
        )
        all_tasks.extend(tasks)
    return files, all_tasks


def _split_frontmatter(text: str) -> tuple[str, str]:
    """Return (frontmatter_block_with_delimiters, body).  Body has no leading newline."""
    m = re.match(r"^(---\n.*?\n---\n)(.*)$", text, re.DOTALL)
    if not m:
        return "", text
    return m.group(1), m.group(2)


def _rewrite_body(path: Path, new_body: str) -> None:
    text = path.read_text(encoding="utf-8")
    fm, _ = _split_frontmatter(text)
    if not new_body.endswith("\n"):
        new_body += "\n"
    path.write_text(fm + new_body, encoding="utf-8")


def toggle_task(room_name: str, task_id: str, *, done: bool | None = None) -> PlanTask:
    """Toggle (or set) the checkbox on a task line.  Returns the updated task.

    Raises ``KeyError`` if the task can't be located.
    """
    if ":" not in task_id:
        raise KeyError(task_id)
    slug, _, line_str = task_id.rpartition(":")
    try:
        line_no = int(line_str)
    except ValueError as e:
        raise KeyError(task_id) from e

    base = _plan_dir(room_name)
    path = base / f"{slug}.md"
    if not path.exists():
        raise KeyError(task_id)

    text = path.read_text(encoding="utf-8")
    fm, body = _split_frontmatter(text)
    lines = body.splitlines()
    if line_no < 1 or line_no > len(lines):
        raise KeyError(task_id)

    m = _TASK_RE.match(lines[line_no - 1])
    if not m:
        raise KeyError(task_id)

    current_done = m.group("mark").lower() == "x"
    new_done = (not current_done) if done is None else done
    mark = "x" if new_done else " "
    indent = m.group("indent")
    body_text = m.group("body")
    lines[line_no - 1] = f"{indent}- [{mark}] {body_text}"

    new_body = "\n".join(lines) + ("\n" if body.endswith("\n") else "")
    path.write_text((fm or "") + new_body, encoding="utf-8")

    return PlanTask(
        id=task_id,
        slug=slug,
        line=line_no,
        text=body_text.strip(),
        done=new_done,
    )


def add_task(room_name: str, text: str, *, slug: str = DEFAULT_TASK_FILE) -> PlanTask:
    """Append a new ``- [ ]`` line to ``plan/{slug}.md``, creating it if needed."""
    base = _plan_dir(room_name)
    base.mkdir(parents=True, exist_ok=True)
    path = base / f"{slug}.md"
    line = f"- [ ] {text.strip()}"

    if not path.exists():
        # Bare body; the memory-style frontmatter is optional for plan files
        # created via the task API.
        path.write_text(f"# Tasks\n\n{line}\n", encoding="utf-8")
        body_lines = ["# Tasks", "", line]
        new_line_no = len(body_lines)
    else:
        existing = path.read_text(encoding="utf-8")
        fm, body = _split_frontmatter(existing)
        body = body.rstrip("\n")
        new_body = (body + "\n" + line + "\n") if body else line + "\n"
        path.write_text((fm or "") + new_body, encoding="utf-8")
        new_line_no = len(new_body.rstrip("\n").splitlines())

    return PlanTask(
        id=f"{slug}:{new_line_no}",
        slug=slug,
        line=new_line_no,
        text=text.strip(),
        done=False,
    )


def open_task_summary(room_name: str, *, limit: int = 20) -> str | None:
    """Human-readable list of open tasks for injection into agent context.

    Returns ``None`` if the room has no plan files.
    """
    files, tasks = load_plan(room_name)
    if not files:
        return None
    open_tasks = [t for t in tasks if not t.done][:limit]
    if not open_tasks:
        return "Plan: no open tasks."
    bullets = "\n".join(f"- [{t.slug}] {t.text}" for t in open_tasks)
    return f"Open tasks ({len(open_tasks)}):\n{bullets}"
