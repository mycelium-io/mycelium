# Mycelium Demo — Setup Guide

Everything runs on **oclw4** (the EC2). Your laptop only needs an SSH connection to retrieve the final video file.

---

## What runs where

| Component | Where |
|---|---|
| Mycelium stack (backend, frontend, DB) | oclw4 |
| `demo-agent.py` (4 personas) | oclw4 (spawned directly by orchestrator) |
| Playwright + Chrome | oclw4 (virtual display via Xvfb) |
| ffmpeg screen capture | oclw4 |
| Audio playback | not needed during recording — merged in post |
| Final video | oclw4 → `scp` to laptop |

---

## Step 1 — Install dependencies on oclw4

```bash
# ffmpeg only needed for the merge step — not for recording
sudo apt-get install -y ffmpeg

pip install playwright
playwright install chromium
```

## Step 3 — Confirm Mycelium is running

```bash
mycelium status
# backend ✓  database ✓  frontend ✓
```

If not:
```bash
mycelium start
```

## Step 4 — Generate narration audio

### Option A: OpenAI TTS

```bash
export OPENAI_API_KEY=sk-...
cd ~/mycelium/docs
python gen-audio.py --tts openai --voice nova --out-dir ./audio
```

### Option B: Kokoro (local, no API key)

```bash
pip install kokoro soundfile
cd ~/mycelium/docs
python gen-audio.py --tts kokoro --voice af_heart --out-dir ./audio
```

Produces `./audio/seg1.mp3` … `./audio/seg9.mp3`.

---

## Step 5 — Dry run (verify UI flow)

```bash
cd ~/mycelium/docs
python demo-orchestrator.py --dry-run
```

This skips Xvfb, ffmpeg, and agents. It just runs Playwright against `localhost:3000` and steps through the UI. Use it to verify:
- Mycelium UI loads
- "New Room" button is found
- Chat box accepts input

If selectors fail, inspect the running UI and update `create_room()` / `type_ruling()` in `demo-orchestrator.py`.

---

## Step 6 — Record the demo

```bash
cd ~/mycelium/docs
python demo-orchestrator.py --out-dir ./demo-output
```

This:
1. Launches Chrome **headless** — no display needed, no Xvfb
2. Playwright's built-in recorder captures the browser → `demo-output/video/*.webm`
3. Drives the full demo (creates room, spawns all 4 agents, waits for impasse, types ruling, shows memory)
4. Saves `demo-output/timestamps.json` — exact offsets (seconds from start) for each segment

---

## Step 7 — Merge audio + video

```bash
python merge-av.py \
  --video  demo-output/demo-raw.mp4 \
  --timestamps demo-output/timestamps.json \
  --audio-dir ./audio \
  --out demo-output/demo-final.mp4
```

Each audio segment is placed at its recorded timestamp. ffmpeg mixes and outputs one MP4.

---

## Step 8 — Download to laptop

```bash
# From your laptop:
scp ubuntu@oclw4:~/mycelium/docs/demo-output/demo-final.mp4 ~/Desktop/
```

---

## Files

| File | Purpose |
|---|---|
| `demo-orchestrator.py` | Controls Chrome (Xvfb) + spawns agents + records video |
| `gen-audio.py` | Generates `audio/seg*.mp3` from script text |
| `merge-av.py` | Places audio at recorded timestamps → final MP4 |
| `demo-script.md` | Narration script with timestamps |
| `demo-agent.py` | Simulator for all 4 personas |

---

## Troubleshooting

**"New Room" button not found**
Add `await page.pause()` in `demo-orchestrator.py` after `goto()` and open the Playwright Inspector to find the real selector.

**Agents not joining**
Check `mycelium status`. Run one agent manually:
```bash
python3 demo-agent.py --persona pm-agent --room dissent-map-demo
```

**Audio offset is wrong in final video**
Re-run just the merge step with adjusted delays — no need to re-record.
The timestamps in `timestamps.json` are the ground truth from the actual run.
