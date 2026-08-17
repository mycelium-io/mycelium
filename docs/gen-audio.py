#!/usr/bin/env python3
"""
Generate per-segment narration audio from demo-script.md.

Supports:
  --tts elevenlabs  ElevenLabs API (voice: Rachel). Needs ELEVENLABS_API_KEY.
  --tts openai      OpenAI TTS (tts-1-hd, voice: nova). Needs OPENAI_API_KEY.
  --tts kokoro      Kokoro local TTS (no API key). Needs: pip install kokoro soundfile

Output: ./audio/seg*.mp3

Usage:
  python gen-audio.py --tts elevenlabs
  python gen-audio.py --tts elevenlabs --voice Adam
  python gen-audio.py --tts openai
  python gen-audio.py --tts kokoro --voice af_heart
"""

import argparse
import os
from pathlib import Path

# ── Narration segments (extracted from demo-script.md) ─────────────────────────
# [pause] markers are removed — silences come from natural speech rhythm + audio gaps.

SEGMENTS: dict[str, str] = {
    "seg1": (
        "Mycelium is a coordination layer for autonomous AI agents — "
        "it provides shared rooms, persistent memory, and structured negotiation. "
        "It's our amuse-bouche of IoC capabilities. "
        "For this hackathon, we added two things: "
        "a dissent map that surfaces genuine agent disagreement, "
        "and a human-in-the-loop mechanism that lets a person break the deadlock "
        "and hand the team a decision they all inherit."
    ),
    "seg2": (
        "To make that concrete — here's the scenario we ran it against."
    ),
    "seg3": (
        "It's Thursday afternoon. There's a checkout bug and launch is scheduled for Friday morning. "
        "Four agents need to decide: ship, or slip? "
        "Each one has a different hard constraint. "
        "The product manager says we cannot slip — a paid marketing campaign "
        "lands Friday. "
        "The engineering lead will not ship known data corruption. "
        "The SRE requires a kill switch and under-two-minute rollback. "
        "Security needs an exploitability review — discount code bugs are a known attack surface. "
        "No single agent has the full picture. And none of them will just defer."
    ),
    "seg4": (
        "Using the Mycelium UI, we create a new room - let's call it dissent-map-demo. "
        "Each agent joins the room, using the Mycelium CLI, which creates a new session."
    ),
    "seg4c": (
        "You can see each agent registering their position with the CognitiveEngine — "
        "the mediator built into Mycelium that drives structured negotiation."
        "It doesn't pick a winner. It runs multi-issue negotiation rounds, "
        "surfacing where agents agree, where they don't, "
        "and what each one considers a hard limit versus a preference they can trade. "
    ),
    "seg4b": (
        "Once all agents have joined, the CognitiveEngine structures what's actually being decided — "
        "you can see it here in the Topic banner. "
        "Expand it and you get each agent's full opening position. "
        "These aren't summaries — they're the exact stakes each agent brought in. "
        "The CognitiveEngine works from these to frame the negotiation issues: "
        "Friday ship, kill switch, exploitability review, staging validation. "
        "This is the map before the territory."
    ),
    "seg5": (
        "The agents now negotiate, for up to 20 rounds, the CognitiveEngine mediating. "
        "Each agent responds to proposals, pushes their constraints, and tries to find common ground. "
        "For this demo, we've ensured their positions are irreconcilable. "
    ),
    "seg6": (
        "The negotiation ran twenty rounds before the CognitiveEngine "
        "confirmed no agreement was possible. "
        "That's the impasse. And look — Mycelium surfaces the ruling input right here in the "
        "session view. The ruling can be entered here or via the Mycelium CLI. "
    ),
    "seg7": (
        "The human steps in and writes a ruling directly into the room. "
        "Ship Friday with checkout behind a feature flag. "
        "Run the exploitability review in parallel. "
    ),
    "seg8": (
        "Mycelium spawns a second session. "
        "The same agents, the same room — now working within the constraints the human set. "
        "This time they converge."
    ),
    "seg8b": (
        "From that consensus, Mycelium compiles a shared plan — "
        "the checklist the whole team executes against. "
        "Not a document someone has to summarize. "
        "The coordination artifact becomes the work artifact."
    ),
    "seg9": (
        "Human in the loop. Agent dissent with a path forward. "
        "A decision every agent inherits. "
        "That's what Mycelium coordination looks like in practice."
    ),
}


# ── ElevenLabs TTS ─────────────────────────────────────────────────────────────

def gen_elevenlabs(segments: dict[str, str], voice: str, out_dir: Path) -> None:
    try:
        from elevenlabs.client import ElevenLabs
        from elevenlabs import save
    except ImportError:
        print("ERROR: pip install elevenlabs")
        raise

    api_key = os.environ.get("ELEVENLABS_API_KEY")
    if not api_key:
        raise ValueError("ELEVENLABS_API_KEY not set")

    client = ElevenLabs(api_key=api_key)

    for seg_id, text in segments.items():
        out_path = out_dir / f"{seg_id}.mp3"
        print(f"  Generating {seg_id} ({len(text)} chars)…")
        audio = client.text_to_speech.convert(
            text=text,
            voice_id=voice,
            model_id="eleven_multilingual_v2",
            output_format="mp3_44100_128",
        )
        save(audio, str(out_path))
        print(f"  → {out_path}")


# ── OpenAI TTS ─────────────────────────────────────────────────────────────────

def gen_openai(segments: dict[str, str], voice: str, out_dir: Path) -> None:
    try:
        from openai import OpenAI
    except ImportError:
        print("ERROR: pip install openai")
        raise

    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ValueError("OPENAI_API_KEY not set")

    client = OpenAI(api_key=api_key)

    for seg_id, text in segments.items():
        out_path = out_dir / f"{seg_id}.mp3"
        print(f"  Generating {seg_id} ({len(text)} chars)…")
        with client.audio.speech.with_streaming_response.create(
            model="tts-1-hd",
            voice=voice,
            input=text,
            response_format="mp3",
        ) as response:
            response.stream_to_file(str(out_path))
        print(f"  → {out_path}")


# ── Kokoro TTS ─────────────────────────────────────────────────────────────────

def gen_kokoro(segments: dict[str, str], voice: str, out_dir: Path) -> None:
    try:
        from kokoro import KPipeline
        import soundfile as sf
        import numpy as np
    except ImportError:
        print("ERROR: pip install kokoro soundfile")
        raise

    print("  Loading Kokoro pipeline…")
    pipeline = KPipeline(lang_code="a")  # 'a' = American English

    for seg_id, text in segments.items():
        out_path = out_dir / f"{seg_id}.mp3"
        print(f"  Generating {seg_id} ({len(text)} chars)…")
        audio_chunks = []
        for _, _, audio in pipeline(text, voice=voice, speed=0.95):
            audio_chunks.append(audio)
        combined = np.concatenate(audio_chunks)
        sf.write(str(out_path), combined, 24000)
        print(f"  → {out_path}")


# ── Entry point ────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Generate demo narration audio")
    parser.add_argument("--tts", choices=["elevenlabs", "openai", "kokoro"], default="elevenlabs")
    parser.add_argument(
        "--voice",
        default="",
        help="Voice name. Defaults: openai=nova, kokoro=af_heart",
    )
    parser.add_argument("--out-dir", default="./audio", help="Output directory")
    parser.add_argument("--segments", nargs="*", help="Only generate these segments (e.g. seg1 seg5)")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    segs = SEGMENTS
    if args.segments:
        segs = {k: v for k, v in SEGMENTS.items() if k in args.segments}

    defaults = {"elevenlabs": "Rachel", "openai": "nova", "kokoro": "af_heart"}
    voice = args.voice or defaults[args.tts]

    print(f"TTS backend : {args.tts}")
    print(f"Voice       : {voice}")
    print(f"Output dir  : {out_dir}")
    print(f"Segments    : {list(segs.keys())}\n")

    if args.tts == "elevenlabs":
        gen_elevenlabs(segs, voice, out_dir)
    elif args.tts == "openai":
        gen_openai(segs, voice, out_dir)
    else:
        gen_kokoro(segs, voice, out_dir)

    print("\nDone. Run demo-orchestrator.py to use these files.")


if __name__ == "__main__":
    main()
