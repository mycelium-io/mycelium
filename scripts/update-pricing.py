#!/usr/bin/env python3
"""Extract model pricing from litellm and write pricing.json.

Run from the fastapi-backend uv environment (where litellm is installed):
    cd fastapi-backend && uv run python ../scripts/update-pricing.py

The output file is consumed by both the CLI (prompt cache savings) and the
backend (embedding cost avoidance baseline).
"""

from __future__ import annotations

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

PRICING_OUTPUT = (
    Path(__file__).resolve().parent.parent
    / "mycelium-cli"
    / "src"
    / "mycelium"
    / "data"
    / "pricing.json"
)

TRACKED_MODELS: list[dict] = [
    # Anthropic
    {"pattern": "claude-sonnet-4",   "provider": "anthropic"},
    {"pattern": "claude-3-7-sonnet", "provider": "anthropic"},
    {"pattern": "claude-3-5-sonnet", "provider": "anthropic"},
    {"pattern": "claude-3-5-haiku",  "provider": "anthropic"},
    {"pattern": "claude-haiku-4",    "provider": "anthropic"},
    {"pattern": "claude-3-haiku",    "provider": "anthropic"},
    {"pattern": "claude-3-opus",     "provider": "anthropic"},
    {"pattern": "claude-opus-4",     "provider": "anthropic"},
    # OpenAI
    {"pattern": "gpt-4o-mini",  "provider": "openai"},
    {"pattern": "gpt-4o",       "provider": "openai"},
    {"pattern": "gpt-4-turbo",  "provider": "openai"},
    {"pattern": "o3-mini",      "provider": "openai"},
    {"pattern": "o3",           "provider": "openai"},
    {"pattern": "o4-mini",      "provider": "openai"},
]

EMBEDDING_MODEL = "text-embedding-3-small"

DEFAULT_CACHE_DISCOUNT = 0.90


def _best_match(pattern: str, model_cost: dict) -> tuple[str, dict] | None:
    """Find the litellm entry whose key contains *pattern* and is a chat model.

    Preference order:
      1. Has both input_cost_per_token and cache_read_input_token_cost
      2. Has input_cost_per_token (no cache pricing)
      3. Shortest key (closest to the base model name)
    """
    candidates = [
        (k, v)
        for k, v in model_cost.items()
        if pattern in k and v.get("mode") == "chat"
    ]
    if not candidates:
        return None

    def _rank(kv: tuple[str, dict]) -> tuple[int, int]:
        v = kv[1]
        has_input = v.get("input_cost_per_token") is not None and v["input_cost_per_token"] > 0
        has_cache = v.get("cache_read_input_token_cost") is not None
        tier = 0 if (has_input and has_cache) else (1 if has_input else 2)
        return (tier, len(kv[0]))

    candidates.sort(key=_rank)
    return candidates[0]


def main() -> None:
    try:
        import litellm
    except ImportError:
        print(
            "ERROR: litellm is not installed. Run this from the fastapi-backend env:\n"
            "  cd fastapi-backend && uv run python ../scripts/update-pricing.py",
            file=sys.stderr,
        )
        sys.exit(1)

    model_cost = litellm.model_cost
    litellm_version = getattr(litellm, "__version__", "unknown")

    old_data: dict | None = None
    if PRICING_OUTPUT.exists():
        try:
            old_data = json.loads(PRICING_OUTPUT.read_text())
        except (json.JSONDecodeError, OSError):
            pass

    models: list[dict] = []
    warnings: list[str] = []

    for spec in TRACKED_MODELS:
        pattern = spec["pattern"]
        match = _best_match(pattern, model_cost)
        if not match:
            warnings.append(f"  WARNING: no litellm match for '{pattern}'")
            continue

        key, entry = match
        input_price = entry.get("input_cost_per_token", 0)
        cache_read = entry.get("cache_read_input_token_cost")

        if input_price and cache_read:
            cache_discount = round(1.0 - (cache_read / input_price), 2)
        else:
            cache_discount = DEFAULT_CACHE_DISCOUNT
            if not cache_read:
                warnings.append(
                    f"  NOTE: '{pattern}' ({key}) has no cache_read pricing, "
                    f"using default {DEFAULT_CACHE_DISCOUNT:.0%} discount"
                )

        models.append({
            "pattern": pattern,
            "input_per_token": input_price,
            "cache_discount": cache_discount,
            "litellm_key": key,
        })

    # Embedding baseline
    embed_entry = model_cost.get(EMBEDDING_MODEL, {})
    embed_price = embed_entry.get("input_cost_per_token", 2e-08)

    output = {
        "generated_at": datetime.now(UTC).isoformat(),
        "litellm_version": litellm_version,
        "models": models,
        "default": {
            "input_per_token": 8e-07,
            "cache_discount": DEFAULT_CACHE_DISCOUNT,
            "label": "unknown model",
        },
        "embedding_baseline": {
            "model": EMBEDDING_MODEL,
            "input_per_token": embed_price,
        },
    }

    PRICING_OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    PRICING_OUTPUT.write_text(json.dumps(output, indent=2) + "\n")

    print(f"Wrote {PRICING_OUTPUT}")
    print(f"  litellm {litellm_version}  •  {len(models)} models  •  embedding baseline: {EMBEDDING_MODEL}")
    print()

    if warnings:
        for w in warnings:
            print(w)
        print()

    # Show changes
    if old_data:
        old_models = {m["pattern"]: m for m in old_data.get("models", [])}
        changes = 0
        for m in models:
            old = old_models.get(m["pattern"])
            if not old:
                print(f"  + {m['pattern']:25s}  ${m['input_per_token']*1e6:.2f}/MTok  {m['cache_discount']:.0%} discount")
                changes += 1
            else:
                old_input = old.get("input_per_token", 0)
                old_discount = old.get("cache_discount", 0)
                if abs(old_input - m["input_per_token"]) > 1e-12 or abs(old_discount - m["cache_discount"]) > 0.001:
                    print(
                        f"  ~ {m['pattern']:25s}  "
                        f"${old_input*1e6:.2f} → ${m['input_per_token']*1e6:.2f}/MTok  "
                        f"{old_discount:.0%} → {m['cache_discount']:.0%} discount"
                    )
                    changes += 1

        old_embed = old_data.get("embedding_baseline", {}).get("input_per_token", 0)
        if abs(old_embed - embed_price) > 1e-12:
            print(f"  ~ embedding baseline  ${old_embed*1e6:.4f} → ${embed_price*1e6:.4f}/MTok")
            changes += 1

        if changes == 0:
            print("  No pricing changes detected.")
    else:
        print("  (first run — no previous data to compare)")


if __name__ == "__main__":
    main()
