#!/usr/bin/env python3
"""
Merge recorded video with narration audio, auto-cutting waiting gaps.

For each segment the orchestrator logged a start timestamp. This script:
  1. Gets the audio duration of each segment (ffprobe)
  2. Clips the video to [seg_start, seg_start + audio_duration + tail_buffer]
  3. Concatenates the clips — gaps where IoC/agents were thinking are removed
  4. Overlays the narration audio on the matching clip
  5. Outputs a final MP4

Usage:
  python merge-av.py \\
    --video  demo-output/video/page@<hash>.webm \\
    --timestamps demo-output/timestamps.json \\
    --audio-dir ./audio \\
    --out demo-output/demo-final.mp4

Options:
  --tail-buffer N   Seconds of video to keep after narration ends (default: 3)
  --no-trim         Skip gap removal — place audio at raw timestamps instead
"""

import argparse
import json
import subprocess
import tempfile
from pathlib import Path

SEGMENT_AUDIO = {
    "seg1":  "seg1.mp3",
    "seg2":  "seg2.mp3",
    "seg3":  "seg3.mp3",
    "seg4":  "seg4.mp3",
    "seg4c": "seg4c.mp3",
    "seg4b": "seg4b.mp3",
    "seg5":  "seg5.mp3",
    "seg6":  "seg6.mp3",
    "seg7":  "seg7.mp3",
    "seg8":  "seg8.mp3",
    "seg8b": "seg8b.mp3",
    "seg9":  "seg9.mp3",
}


def audio_duration(path: Path) -> float:
    """Return duration of an audio file in seconds using ffprobe."""
    result = subprocess.run(
        [
            "ffprobe", "-v", "quiet",
            "-show_entries", "format=duration",
            "-of", "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0


def build_trimmed(
    video: Path,
    timestamps: dict[str, float],
    audio_dir: Path,
    out: Path,
    tail_buffer: float,
) -> None:
    """
    Cut waiting gaps out of the video, then merge audio.

    For each segment:
      - video clip = [ts_start … ts_start + audio_duration + tail_buffer]
      - audio sits at the start of that clip in the output
    """
    segments = [(sid, fn) for sid, fn in SEGMENT_AUDIO.items()
                if sid in timestamps and (audio_dir / fn).exists()]

    if not segments:
        raise ValueError("No matching segments found.")

    clips: list[dict] = []
    audio_offset = 0.0

    for seg_id, filename in segments:
        ts = timestamps[seg_id]
        audio_path = audio_dir / filename
        dur = audio_duration(audio_path)

        # Use {seg_id}_end if present — clips video to the marked end point,
        # trimming any async wait that happened after the segment content.
        end_key = f"{seg_id}_end"
        if end_key in timestamps:
            clip_dur = (timestamps[end_key] - ts) + tail_buffer
        else:
            clip_dur = dur + tail_buffer

        clips.append({
            "seg_id": seg_id,
            "video_start": ts,
            "video_dur": clip_dur,
            "audio_path": audio_path,
            "audio_offset": audio_offset,
            "audio_dur": dur,
        })
        # Audio timeline always advances by audio duration — video clip may be shorter
        audio_offset += dur + tail_buffer
        print(f"  {seg_id:8s}  video [{ts:.1f}s … {ts+clip_dur:.1f}s]  "
              f"audio → {audio_offset-clip_dur:.1f}s  ({dur:.1f}s narration)")

    total_dur = audio_offset
    print(f"\n  Total output duration: {total_dur:.1f}s "
          f"({total_dur/60:.1f} min)\n")

    with tempfile.TemporaryDirectory() as tmp:
        tmp = Path(tmp)

        # ── Step 1: extract clips sequentially ──────────────────────────────────
        clip_paths: list[Path] = []
        for i, clip in enumerate(clips):
            clip_path = tmp / f"clip_{i:02d}.mp4"
            result = subprocess.run([
                "ffmpeg", "-y",
                "-ss", str(clip["video_start"]),
                "-i", str(video),
                "-t", str(clip["video_dur"]),
                "-vf", "scale=1920:1080:force_original_aspect_ratio=decrease,"
                       "pad=1920:1080:(ow-iw)/2:(oh-ih)/2,fps=30",
                "-c:v", "libx264", "-preset", "fast", "-crf", "18",
                "-an",
                "-movflags", "+faststart",
                str(clip_path),
            ], capture_output=True)
            if result.returncode != 0:
                print(f"  WARNING: clip {i} ({clip['seg_id']}) failed:\n"
                      f"{result.stderr.decode()[-300:]}")
            else:
                print(f"  clip {i:02d} ({clip['seg_id']}) → {clip_path.stat().st_size // 1024}kB")
            clip_paths.append(clip_path)

        # ── Step 2: concat via demuxer with re-encode ────────────────────────────
        concat_video = tmp / "concat.mp4"
        concat_list = tmp / "concat.txt"
        concat_list.write_text("\n".join(f"file '{p}'" for p in clip_paths))
        subprocess.run([
            "ffmpeg", "-y",
            "-f", "concat", "-safe", "0", "-i", str(concat_list),
            "-c:v", "libx264", "-preset", "fast", "-crf", "18",
            "-movflags", "+faststart",
            str(concat_video),
        ], check=True)

        # ── Step 3: build audio mix with per-segment delays ──────────────────
        audio_inputs = []
        filter_parts = []
        cmd = ["ffmpeg", "-y", "-i", str(concat_video)]

        for i, clip in enumerate(clips):
            cmd += ["-i", str(clip["audio_path"])]
            idx = i + 1
            delay_ms = int(clip["audio_offset"] * 1000)
            filter_parts.append(
                f"[{idx}]adelay={delay_ms}|{delay_ms}[a{idx}]"
            )
            audio_inputs.append(f"[a{idx}]")

        n = len(audio_inputs)
        mix = "".join(audio_inputs)
        filter_complex = (
            ";".join(filter_parts)
            + f";{mix}amix=inputs={n}:normalize=0[aout]"
        )

        cmd += [
            "-filter_complex", filter_complex,
            "-map", "0:v",
            "-map", "[aout]",
        "-c:v", "copy",
        "-c:a", "aac", "-b:a", "192k",
        str(out),
        ]

        print("  Merging audio into final video…")
        subprocess.run(cmd, check=True, capture_output=True)


def build_raw(
    video: Path,
    timestamps: dict[str, float],
    audio_dir: Path,
    out: Path,
) -> None:
    """Place audio at raw timestamp offsets — no gap removal."""
    cmd = ["ffmpeg", "-y", "-i", str(video)]
    filter_parts = []
    audio_inputs = []
    idx = 1

    for seg_id, filename in SEGMENT_AUDIO.items():
        ts = timestamps.get(seg_id)
        audio_path = audio_dir / filename
        if ts is None or not audio_path.exists():
            continue
        cmd += ["-i", str(audio_path)]
        delay_ms = int(ts * 1000)
        filter_parts.append(f"[{idx}]adelay={delay_ms}|{delay_ms}[a{idx}]")
        audio_inputs.append(f"[a{idx}]")
        print(f"  {seg_id:8s} @ {ts:.1f}s")
        idx += 1

    n = len(audio_inputs)
    mix = "".join(audio_inputs)
    filter_complex = ";".join(filter_parts) + f";{mix}amix=inputs={n}:normalize=0[aout]"

    cmd += [
        "-filter_complex", filter_complex,
        "-map", "0:v", "-map", "[aout]",
        "-c:v", "copy", "-c:a", "aac", "-b:a", "192k",
        "-shortest", str(out),
    ]
    subprocess.run(cmd, check=True)


def main() -> None:
    parser = argparse.ArgumentParser(description="Merge demo video + narration audio")
    parser.add_argument("--video", required=True)
    parser.add_argument("--timestamps", required=True)
    parser.add_argument("--audio-dir", default="./audio")
    parser.add_argument("--out", default="demo-output/demo-final.mp4")
    parser.add_argument("--tail-buffer", type=float, default=3.0,
                        help="Seconds of video to keep after narration ends (default: 3)")
    parser.add_argument("--no-trim", action="store_true",
                        help="Skip gap removal — use raw timestamps")
    args = parser.parse_args()

    video = Path(args.video)
    timestamps: dict[str, float] = json.loads(Path(args.timestamps).read_text())
    audio_dir = Path(args.audio_dir)
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)

    print(f"Video      : {video}")
    print(f"Audio dir  : {audio_dir}")
    print(f"Output     : {out}")
    print(f"Trim gaps  : {not args.no_trim}\n")

    if args.no_trim:
        build_raw(video, timestamps, audio_dir, out)
    else:
        build_trimmed(video, timestamps, audio_dir, out, args.tail_buffer)

    print(f"\n✅ {out}")


if __name__ == "__main__":
    main()
