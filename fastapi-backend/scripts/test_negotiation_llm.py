#!/usr/bin/env python3
"""
Test script for intent_discovery + options_generation using the configured LiteLLM.

Run from fastapi-backend/:
    uv run python scripts/test_negotiation_llm.py

Requires LLM_API_KEY (and optionally LLM_MODEL / LLM_BASE_URL) set in .env or environment.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Add project root to path so app.* imports work
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.agents.semantic_negotiation.intent_discovery import IntentDiscovery
from app.agents.semantic_negotiation.options_generation import OptionsGeneration
from app.config import settings

print(f"Model: {settings.LLM_MODEL}")
print(f"API key set: {bool(settings.LLM_API_KEY)}")
print()

# ── Test cases ────────────────────────────────────────────────────────────────

CASES = [
    {
        "sentence": "I brought way too much raw meat, which means I'll need some firewood to cook it. I didn't bring enough water and I'm going to do a ton of hiking, so I need to stay hydrated. I already have plenty of food, and I can cook more, which is why I prioritize firewood over this.",
        "context": "Two campsite neighbors negotiate for Food, Water, and Firewood packages based on their individual needs.",
    },
    {
        "sentence": "We need an affordable solution delivered soon with high quality.",
        "context": "Two software agents negotiating a service contract.",
    },
]

discovery = IntentDiscovery()
options_gen = OptionsGeneration()

for i, case in enumerate(CASES, 1):
    print(f"{'=' * 60}")
    print(f"Case {i}: {case['sentence'][:80]}...")
    print(f"Context: {case['context']}")
    print()

    print("── Intent Discovery ──")
    entities = discovery.discover(case["sentence"], context=case["context"])
    print(f"Entities ({len(entities)}): {entities}")
    print()

    if not entities:
        print("  (no entities — skipping options generation)")
        print()
        continue

    print("── Options Generation (LLM-only) ──")
    options = options_gen.generate_options_llm_only(entities, case["sentence"], case["context"])
    for term, opts in options.items():
        print(f"  {term}: {opts}")
    print()

    print("── Options Generation (memory+LLM) ──")
    options_mem = options_gen.generate_options_with_memory(
        entities, case["sentence"], case["context"]
    )
    for term, opts in options_mem.items():
        print(f"  {term}: {opts}")
    print()

print("Done.")
