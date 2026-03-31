# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Julia Valenti

"""
Async CognitiveEngine — synthesis for namespace rooms.

Unlike sync coordination (NegMAS tick loop), async coordination:
  - Triggers on configurable conditions (threshold, schedule, explicit)
  - Reads accumulated memories instead of live messages
  - Produces synthesis summaries written back as memories
  - Does not require agents to be online simultaneously
"""

import json
import logging
from datetime import UTC, datetime
from urllib.parse import urlparse

import asyncpg
from sqlalchemy import func, select, update

from app.bus import agent_channel, notify
from app.config import LLMUnavailableError, require_llm, settings
from app.database import async_session_maker
from app.models import Memory, Room
from app.services.filesystem import get_room_dir, write_memory_file

logger = logging.getLogger(__name__)


async def check_trigger(room_name: str) -> None:
    """Check if an async room's trigger condition is met and run synthesis if so."""
    async with async_session_maker() as db:
        result = await db.execute(select(Room).where(Room.name == room_name))
        room = result.scalar_one_or_none()
        if not room or not room.is_namespace:
            return

        config = room.trigger_config
        if not config or config.get("type") != "threshold":
            return

        min_contributions = config.get("min_contributions", 5)

        # Count memories since last synthesis
        query = select(func.count()).select_from(Memory).where(Memory.room_name == room_name)
        if room.last_synthesis_at:
            query = query.where(Memory.updated_at > room.last_synthesis_at)

        result = await db.execute(query)
        count = result.scalar() or 0

        if count >= min_contributions:
            logger.info(
                "Async trigger met for room %s: %d memories >= threshold %d",
                room_name,
                count,
                min_contributions,
            )
            await run_synthesis(room_name)


async def run_synthesis(room_name: str) -> dict | None:
    """
    Run CognitiveEngine async synthesis on a room's accumulated memories.

    Reads all memories since last synthesis, calls LLM to produce a summary,
    and writes the result back as a memory under _synthesis/{timestamp}.
    """
    import time as _time

    from app.services.metrics import record_synthesis

    _synth_t0 = _time.monotonic()
    async with async_session_maker() as db:
        # Set room state to synthesizing
        await db.execute(
            update(Room).where(Room.name == room_name).values(coordination_state="synthesizing")
        )
        await db.commit()

        try:
            # Fetch memories since last synthesis
            result = await db.execute(select(Room).where(Room.name == room_name))
            room = result.scalar_one_or_none()
            if not room:
                return None

            query = (
                select(Memory)
                .where(Memory.room_name == room_name)
                .where(Memory.key.not_like("_synthesis/%"))
            )
            if room.last_synthesis_at:
                # Use updated_at so upserts count as new contributions
                query = query.where(Memory.updated_at > room.last_synthesis_at)
            query = query.order_by(Memory.created_at.asc())

            result = await db.execute(query)
            memories = list(result.scalars().all())

            if not memories:
                logger.info("No new memories to synthesize for room %s", room_name)
                await db.execute(
                    update(Room).where(Room.name == room_name).values(coordination_state="idle")
                )
                await db.commit()
                return None

            # Check LLM availability before doing work
            require_llm()

            # Build context for LLM synthesis, grouped by category prefix
            context = _build_structured_context(memories)

            # Call LLM for synthesis
            synthesis_text = await _llm_synthesize(room_name, context, len(memories))

            # Write synthesis result as a markdown file + DB index
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            synthesis_key = f"_synthesis/{timestamp}"

            # Write markdown file
            room_dir = get_room_dir(room_name)
            write_memory_file(
                room_dir,
                synthesis_key,
                synthesis_text,
                created_by="CognitiveEngine",
                updated_by="CognitiveEngine",
                version=1,
                extra_meta={"memory_count": len(memories)},
            )

            synthesis_mem = Memory(
                room_name=room_name,
                key=synthesis_key,
                value={"synthesis": synthesis_text, "memory_count": len(memories)},
                content_text=synthesis_text,
                created_by="CognitiveEngine",
                updated_by="CognitiveEngine",
                file_path=f"rooms/{room_name}/{synthesis_key}.md",
            )
            db.add(synthesis_mem)

            # Update room state
            await db.execute(
                update(Room)
                .where(Room.name == room_name)
                .values(
                    coordination_state="idle",
                    last_synthesis_at=datetime.now(UTC),
                )
            )
            await db.commit()

            # Notify agents with active sessions
            await _notify_synthesis_complete(room_name, synthesis_key)

            record_synthesis(
                room=room_name,
                duration_ms=(_time.monotonic() - _synth_t0) * 1000,
            )
            logger.info(
                "Synthesis complete for room %s: %d memories → %s",
                room_name,
                len(memories),
                synthesis_key,
            )
            return {"key": synthesis_key, "memory_count": len(memories)}

        except (LLMUnavailableError, RuntimeError) as e:
            await db.execute(
                update(Room).where(Room.name == room_name).values(coordination_state="idle")
            )
            await db.commit()
            if isinstance(e, LLMUnavailableError) or "authentication failed" in str(e).lower():
                raise
            logger.exception("Synthesis failed for room %s: %s", room_name, e)
            return None
        except Exception as e:
            record_synthesis(
                room=room_name,
                duration_ms=(_time.monotonic() - _synth_t0) * 1000,
                error=True,
            )
            logger.exception("Synthesis failed for room %s: %s", room_name, e)
            await db.execute(
                update(Room).where(Room.name == room_name).values(coordination_state="idle")
            )
            await db.commit()
            return None


# Canonical definition: mycelium-cli/src/mycelium/sstp.py STRUCTURED_CATEGORY_LABELS
# Keep in sync — these are the same categories used by CLI validation.
STRUCTURED_CATEGORIES = {
    "work": "Work Done",
    "decisions": "Decisions Made",
    "context": "Background & Preferences",
    "status": "Current Status",
    "procedures": "Reusable Procedures",
}


def _build_structured_context(memories: list) -> str:
    """Group memories by category prefix for structure-aware synthesis.

    Memories with known category prefixes (work/, decisions/, context/, status/)
    are grouped under headings. Uncategorized memories go in a general section.
    """
    categorized: dict[str, list[str]] = {cat: [] for cat in STRUCTURED_CATEGORIES}
    uncategorized: list[str] = []

    for mem in memories:
        text = (
            f"[{mem.created_by} @ {mem.created_at.isoformat()}] "
            f"key={mem.key}: {mem.content_text or json.dumps(mem.value, default=str)}"
        )
        category = mem.key.split("/", 1)[0] if "/" in mem.key else None
        if category in categorized:
            categorized[category].append(text)
        else:
            uncategorized.append(text)

    sections = []
    for cat, label in STRUCTURED_CATEGORIES.items():
        if categorized[cat]:
            sections.append(f"### {label}")
            sections.extend(categorized[cat])
            sections.append("")

    if uncategorized:
        sections.append("### Other Contributions")
        sections.extend(uncategorized)
        sections.append("")

    return (
        "\n".join(sections)
        if sections
        else "\n".join(
            f"[{m.created_by} @ {m.created_at.isoformat()}] "
            f"key={m.key}: {m.content_text or json.dumps(m.value, default=str)}"
            for m in memories
        )
    )


async def _llm_synthesize(room_name: str, context: str, memory_count: int) -> str:
    """Call LLM to synthesize accumulated memories into insights."""
    import time

    from app.services.metrics import record_llm_call

    try:
        import litellm

        kwargs: dict = {
            "model": settings.LLM_MODEL,
            "max_tokens": 4096,
            "messages": [
                {
                    "role": "user",
                    "content": (
                        f"You are CognitiveEngine synthesizing {memory_count} contributions "
                        f"from agents in room '{room_name}'.\n\n"
                        "Memories are grouped by category when agents used structured keys "
                        "(work/, decisions/, context/, status/):\n\n"
                        f"{context}\n\n"
                        "Produce a synthesis that a new agent arriving for the first time "
                        "could read and immediately be productive. Structure it as:\n\n"
                        "## What's Built\n"
                        "What agents have created or configured. Reference work/* memories.\n\n"
                        "## Current Status\n"
                        "What's active, what's failing, what needs attention. "
                        "Reference status/* memories.\n\n"
                        "## Key Decisions\n"
                        "Choices that were made and why. Reference decisions/* memories.\n\n"
                        "## What Failed\n"
                        "Approaches that were tried and didn't work, and why. Include enough "
                        "detail so no one repeats them. Look for decisions/* memories that "
                        "describe rejected alternatives.\n\n"
                        "## Context\n"
                        "User goals, preferences, constraints. Reference context/* memories.\n\n"
                        "## Open Questions\n"
                        "Unresolved tensions, untested hypotheses, gaps in coverage.\n\n"
                        "## Recommended Next Actions\n"
                        "Concrete things an agent should try next, prioritized by expected impact.\n\n"
                        "Be specific and actionable. Reference agent handles and memory keys "
                        "when citing findings. If a section has no relevant memories, omit it."
                    ),
                }
            ],
        }
        if settings.LLM_API_KEY:
            kwargs["api_key"] = settings.LLM_API_KEY
        if settings.LLM_BASE_URL:
            kwargs["api_base"] = settings.LLM_BASE_URL

        t0 = time.monotonic()
        response = litellm.completion(**kwargs)
        elapsed_ms = (time.monotonic() - t0) * 1000

        usage = getattr(response, "usage", None)
        input_tok = getattr(usage, "prompt_tokens", 0) or 0 if usage else 0
        output_tok = getattr(usage, "completion_tokens", 0) or 0 if usage else 0
        hidden = getattr(response, "_hidden_params", {})
        cost = hidden.get("response_cost", 0.0) or 0.0

        record_llm_call(
            operation="synthesis",
            model=settings.LLM_MODEL,
            input_tokens=input_tok,
            output_tokens=output_tok,
            cost_usd=cost,
            duration_ms=elapsed_ms,
        )

        return response.choices[0].message.content

    except litellm.AuthenticationError:
        logger.warning(
            "LLM authentication failed for model %s. Check LLM_API_KEY in ~/.mycelium/.env",
            settings.LLM_MODEL,
        )
        raise RuntimeError(
            f"LLM authentication failed for {settings.LLM_MODEL}. "
            "Check LLM_API_KEY in ~/.mycelium/.env"
        )
    except Exception:
        record_llm_call(operation="synthesis", model=settings.LLM_MODEL, error=True)
        logger.exception("LLM synthesis failed for room %s", room_name)
        raise


async def _notify_synthesis_complete(room_name: str, synthesis_key: str) -> None:
    """Notify agents with active sessions that synthesis is complete."""
    try:
        parsed = urlparse(settings.DATABASE_URL)
        conn: asyncpg.Connection = await asyncpg.connect(
            host=parsed.hostname,
            port=parsed.port or 5432,
            user=parsed.username,
            password=parsed.password,
            database=parsed.path.lstrip("/"),
        )
        try:
            rows = await conn.fetch(
                "SELECT DISTINCT agent_handle FROM sessions WHERE room_name = $1",
                room_name,
            )
            for row in rows:
                await notify(
                    conn,
                    agent_channel(row["agent_handle"]),
                    {
                        "type": "synthesis_complete",
                        "room_name": room_name,
                        "synthesis_key": synthesis_key,
                        "created_at": datetime.now(UTC).isoformat(),
                    },
                )
        finally:
            await conn.close()
    except Exception as e:
        logger.warning("Synthesis notification failed: %s", e)
