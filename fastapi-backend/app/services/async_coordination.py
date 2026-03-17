"""
Async CognitiveEngine — synthesis for async/hybrid rooms.

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
from sqlalchemy.ext.asyncio import AsyncSession

from app.bus import agent_channel, notify
from app.config import settings
from app.database import async_session_maker
from app.models import Memory, Room, Session

logger = logging.getLogger(__name__)


async def check_trigger(room_name: str) -> None:
    """Check if an async room's trigger condition is met and run synthesis if so."""
    async with async_session_maker() as db:
        result = await db.execute(select(Room).where(Room.name == room_name))
        room = result.scalar_one_or_none()
        if not room or room.mode not in ("async", "hybrid"):
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
                room_name, count, min_contributions,
            )
            await run_synthesis(room_name)


async def run_synthesis(room_name: str) -> dict | None:
    """
    Run CognitiveEngine async synthesis on a room's accumulated memories.

    Reads all memories since last synthesis, calls LLM to produce a summary,
    and writes the result back as a memory under _synthesis/{timestamp}.
    """
    async with async_session_maker() as db:
        # Set room state to synthesizing
        await db.execute(
            update(Room)
            .where(Room.name == room_name)
            .values(coordination_state="synthesizing")
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
                    update(Room)
                    .where(Room.name == room_name)
                    .values(coordination_state="idle")
                )
                await db.commit()
                return None

            # Build context for LLM synthesis
            memory_texts = []
            for mem in memories:
                memory_texts.append(
                    f"[{mem.created_by} @ {mem.created_at.isoformat()}] "
                    f"key={mem.key}: {mem.content_text or json.dumps(mem.value, default=str)}"
                )
            context = "\n".join(memory_texts)

            # Call LLM for synthesis
            synthesis_text = await _llm_synthesize(room_name, context, len(memories))

            # Write synthesis result as a memory
            timestamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
            synthesis_key = f"_synthesis/{timestamp}"

            synthesis_mem = Memory(
                room_name=room_name,
                key=synthesis_key,
                value={"synthesis": synthesis_text, "memory_count": len(memories)},
                content_text=synthesis_text,
                created_by="CognitiveEngine",
                updated_by="CognitiveEngine",
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

            logger.info(
                "Synthesis complete for room %s: %d memories → %s",
                room_name, len(memories), synthesis_key,
            )
            return {"key": synthesis_key, "memory_count": len(memories)}

        except Exception as e:
            logger.exception("Synthesis failed for room %s: %s", room_name, e)
            await db.execute(
                update(Room)
                .where(Room.name == room_name)
                .values(coordination_state="idle")
            )
            await db.commit()
            return None


async def _llm_synthesize(room_name: str, context: str, memory_count: int) -> str:
    """Call LLM to synthesize accumulated memories into insights."""
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
                        f"Memories:\n{context}\n\n"
                        "Produce a synthesis that a new agent arriving for the first time "
                        "could read and immediately be productive. Structure it as:\n\n"
                        "## Current State\n"
                        "What has been established. Key decisions made, results achieved, "
                        "consensus reached.\n\n"
                        "## What Worked\n"
                        "Successful approaches, validated findings, proven configurations. "
                        "Include specific values/parameters when available.\n\n"
                        "## What Failed\n"
                        "Approaches that were tried and didn't work. Include why, so no one "
                        "repeats them.\n\n"
                        "## Open Questions\n"
                        "Unresolved tensions, untested hypotheses, gaps in coverage. "
                        "These are the highest-value next steps.\n\n"
                        "## Recommended Next Actions\n"
                        "Concrete things an agent should try next, prioritized by expected impact.\n\n"
                        "Be specific and actionable. Reference agent handles and memory keys "
                        "when citing findings."
                    ),
                }
            ],
        }
        if settings.LLM_API_KEY:
            kwargs["api_key"] = settings.LLM_API_KEY
        if settings.LLM_BASE_URL:
            kwargs["api_base"] = settings.LLM_BASE_URL

        response = litellm.completion(**kwargs)
        return response.choices[0].message.content

    except Exception as e:
        logger.warning("LLM synthesis failed, using fallback: %s", e)
        return (
            f"Synthesis of {memory_count} memories in room '{room_name}' "
            f"(LLM unavailable — raw summary). "
            f"Contributors: {context[:500]}..."
        )


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
