#!/usr/bin/env python3
# SPDX-License-Identifier: Apache-2.0
"""
Mycelium demo orchestrator — runs on oclw4 (the EC2 itself).

Flow:
  1. Playwright runs headless — no display, no Xvfb needed
  2. Playwright's built-in video recorder captures the browser → raw .webm
  3. Exact segment timestamps logged to timestamps.json
  4. Run merge-av.py to combine .webm + narration audio → final MP4

Prerequisites:
  pip install playwright
  playwright install chromium
  sudo apt-get install -y ffmpeg      # for merge-av.py only
  python gen-audio.py --tts openai    # or --tts kokoro

Usage:
  python demo-orchestrator.py                   # full run
  python demo-orchestrator.py --dry-run         # no agents, no video
  python demo-orchestrator.py --room my-room    # custom room name
"""

import argparse
import asyncio
import json
import subprocess
import sys
import time
from pathlib import Path

from playwright.async_api import async_playwright, Page

# ── Config ─────────────────────────────────────────────────────────────────────

FRONTEND_URL = "http://localhost:3000"
ROOM_NAME_DEFAULT = "dissent-map-demo"
DEMO_AGENT_SCRIPT = str(Path(__file__).parent / "demo-agent.py")
PERSONAS = ["pm-agent", "eng-lead", "sre-agent", "secops-agent"]

def segment_duration(audio_dir: Path, filename: str, fallback: float = 20.0) -> float:
    """Return audio file duration in seconds using ffprobe, or fallback if unavailable."""
    path = audio_dir / filename
    if not path.exists():
        return fallback
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return fallback


HUMAN_RULING = (
    "Ship Friday with checkout behind a feature flag. "
    "Run the exploitability review in parallel. "
)

# ── Demo agents (local) ────────────────────────────────────────────────────────

def spawn_agent(persona: str, room: str) -> subprocess.Popen:
    cmd = [sys.executable, DEMO_AGENT_SCRIPT, "--persona", persona, "--room", room]
    print(f"  [agent] Spawning {persona}…")
    return subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)


def spawn_all_agents(room: str) -> list[subprocess.Popen]:
    return [spawn_agent(p, room) for p in PERSONAS]


# ── Playwright UI helpers ───────────────────────────────────────────────────────

async def create_room(page: Page, room_name: str) -> None:
    print("  [ui] Creating room…")
    await page.get_by_role("button", name="+ NEW ROOM").click()
    await page.get_by_placeholder("design-review").fill(room_name)
    await page.get_by_role("button", name="Create").click()
    # Pause on the room list so viewers can see the new room appear before we enter it
    await asyncio.sleep(2)
    # Click the room link rather than jumping directly to the URL.
    # Match by href — the link text also includes a relative timestamp so
    # an exact name match fails.
    await page.locator(f'a[href="/room/{room_name}"]').first.click()
    await page.wait_for_load_state("networkidle")
    print(f"  [ui] Room created and opened: {room_name}")


async def navigate_to_active_session(page: Page, room: str, timeout: int = 60) -> None:
    """Navigate to session by polling the CLI directly — faster than waiting for UI rail."""
    print("  [ui] Navigating into active session (polling CLI)…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["mycelium", "session", "ls", "--room", room],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            raw = result.stdout.strip()
            if raw:
                print(f"  [debug] session ls output: {raw!r}")
            for line in (raw.splitlines() if raw else []):
                token = line.split()[0].lstrip(":") if line.split() else ""
                # Validate: session IDs are hex strings, 6-12 chars
                if len(token) >= 6 and all(c in "0123456789abcdef" for c in token.lower()):
                    url = f"{FRONTEND_URL}/room/{room}/session/{token}"
                    await page.goto(url)
                    await page.wait_for_url("**/session/**", timeout=10_000)
                    await page.wait_for_load_state("networkidle")
                    print(f"  [ui] Session page: {page.url}")
                    return
        await asyncio.sleep(1)
    print("  [ui] WARNING: no session found via CLI — staying on room page")


async def navigate_to_next_session(page: Page, room: str, current_url: str, timeout: int = 180) -> None:
    """Poll CLI for second session and navigate to it directly."""
    print("  [ui] Waiting for session 2 via CLI…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        result = subprocess.run(
            ["mycelium", "session", "ls", "--room", room],
            capture_output=True, text=True,
        )
        if result.returncode == 0:
            for line in result.stdout.strip().splitlines():
                token = line.split()[0].lstrip(":") if line.split() else ""
                if len(token) < 6 or not all(c in "0123456789abcdef" for c in token.lower()):
                    continue
                session_id = token
                url = f"{FRONTEND_URL}/room/{room}/session/{session_id}"
                if url not in current_url:
                    print(f"  [ui] Session 2 found: {session_id}")
                    await page.goto(url)
                    await page.wait_for_url("**/session/**", timeout=10_000)
                    await page.wait_for_load_state("networkidle")
                    return
        await asyncio.sleep(2)
    print("  [ui] WARNING: session 2 not found — continuing")


async def wait_for_4_participants(page: Page, timeout: int = 180) -> None:
    """Wait until the session view shows 4 participants."""
    print("  [ui] Waiting for 4 participants…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Read raw page text and check for "4 participants" (case-insensitive)
        body = (await page.inner_text("body")).lower()
        if "4 participants" in body:
            print("  [ui] 4 participants visible.")
            return
        await asyncio.sleep(2)
    print("  [ui] WARNING: 4 participants not confirmed — continuing")


async def wait_for_negotiation_started(page: Page, timeout: int = 180) -> None:
    """Wait until negotiating content appears on the current session page."""
    print("  [ui] Waiting for negotiation to start…")
    try:
        # Wait for participant count or TOPIC banner — confirms session is live
        await page.get_by_text("PARTICIPANTS", exact=False).first.wait_for(
            state="visible", timeout=timeout * 1000
        )
        print("  [ui] Negotiation started.")
    except Exception:
        print("  [ui] WARNING: negotiation start not confirmed — continuing")


async def wait_for_impasse(page: Page, timeout: int = 600) -> None:
    print("  [ui] Waiting for impasse…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        # Check via CLI — most reliable, independent of SSE
        try:
            room_from_url = page.url.split("/room/")[1].split("/")[0]
            r = subprocess.run(["mycelium", "session", "ls", "--room", room_from_url], capture_output=True, text=True)
            if r.returncode == 0 and "broken" in r.stdout.lower():
                print("  [ui] Impasse confirmed via CLI.")
                return
        except Exception:
            pass
        # Check page text for signals that exclusively appear post-impasse
        body = (await page.inner_text("body")).lower()
        if "dissent" in body or "enter your ruling" in body or "record ruling" in body:
            print("  [ui] Impasse visible on page.")
            return
        await asyncio.sleep(3)
    print("  [ui] WARNING: impasse not detected — continuing")


async def wait_for_consensus(page: Page, timeout: int = 600) -> None:
    print("  [ui] Waiting for session 2 consensus…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        body = (await page.inner_text("body")).lower()
        if "consensus" in body:
            print("  [ui] Consensus visible.")
            return
        await asyncio.sleep(2)
    print("  [ui] WARNING: consensus not visible — continuing")


async def scroll_to_bottom(page: Page) -> None:
    await page.evaluate("window.scrollTo(0, document.body.scrollHeight)")


async def scroll_to_top(page: Page) -> None:
    await page.evaluate("window.scrollTo(0, 0)")


BANNER_SIGNALS = ("issues not yet structured", "TOPIC", "DISCUSSION")


async def find_banner_button(page: Page):
    """Return the TOPIC/DISCUSSION banner button using role+text filter."""
    for signal in BANNER_SIGNALS:
        btn = page.get_by_role("button").filter(has_text=signal).first
        if await btn.count() > 0:
            return btn
    return None


async def wait_for_discussion_banner(page: Page, timeout: int = 120, require_issues: bool = False) -> None:
    """Wait until the TOPIC/DISCUSSION banner button is in the DOM.

    If require_issues=True, also wait until CE has structured the issues
    (i.e. banner no longer shows 'issues not yet structured').
    """
    print("  [ui] Waiting for TOPIC/DISCUSSION banner…")
    deadline = time.time() + timeout
    while time.time() < deadline:
        btn = await find_banner_button(page)
        if btn and await btn.count() > 0:
            if require_issues:
                text = (await btn.inner_text()).lower()
                if "issues not yet struct" in text:
                    await asyncio.sleep(2)
                    continue
            print("  [ui] Banner found (with issues structured)." if require_issues else "  [ui] Banner found.")
            return
        await asyncio.sleep(2)
    body = (await page.inner_text("body"))[:300].replace("\n", " ")
    print(f"  [debug] page snippet: {body!r}")
    print("  [ui] WARNING: banner not found — continuing")


async def expand_discussion_banner(page: Page) -> None:
    """Click the TOPIC/DISCUSSION banner to expand agent positions."""
    print("  [ui] Expanding TOPIC/DISCUSSION banner…")
    # Debug: capture screenshot and button info
    await page.screenshot(path="demo-output/debug-banner.png")
    debug = await page.evaluate("""() => {
        const btns = Array.from(document.querySelectorAll('button'));
        return btns.map(b => b.textContent?.trim().slice(0, 60) + ' [aria-expanded=' + b.getAttribute('aria-expanded') + ']');
    }""")
    print(f"  [debug] buttons on page: {debug[:5]}")

    # Try JS click on aria-expanded button
    clicked = await page.evaluate("""() => {
        // Try aria-expanded first, then any button containing TOPIC or DISCUSSION
        let btn = document.querySelector('button[aria-expanded]');
        if (!btn) {
            btn = Array.from(document.querySelectorAll('button')).find(
                b => b.textContent?.includes('TOPIC') || b.textContent?.includes('DISCUSSION')
                  || b.textContent?.includes('positions') || b.textContent?.includes('issues')
            );
        }
        if (btn) { btn.click(); return btn.textContent?.trim().slice(0, 40); }
        return null;
    }""")
    if clicked:
        await asyncio.sleep(1)
        print(f"  [ui] Banner expanded: {clicked!r}")
        return
    print("  [ui] WARNING: could not click banner — no matching button found")


async def type_ruling(page: Page, ruling: str, room: str) -> None:
    print(f"  [ui] Typing ruling… (url: {page.url})")
    chat = page.get_by_placeholder("Enter your ruling…")
    try:
        await chat.wait_for(state="visible", timeout=20_000)
        await chat.scroll_into_view_if_needed()
        await chat.click()
        await chat.type(ruling, delay=40)
        await asyncio.sleep(1)
        await page.get_by_role("button", name="RECORD RULING").click()
        print("  [ui] Ruling submitted via UI.")
    except Exception as e:
        # Ruling textarea not found — write directly via CLI (visible on screen as terminal)
        print(f"  [ui] Ruling textarea not found ({e!s:.60}), falling back to CLI…")
        subprocess.run(
            ["mycelium", "session", "ruling", ruling, "--room", room],
            capture_output=True,
        )
        print("  [ui] Ruling submitted via CLI.")


async def open_memory_panel(page: Page) -> None:
    try:
        await page.get_by_role("button", name="Memory").click()
        await asyncio.sleep(1)
    except Exception:
        pass


# ── Timestamps ─────────────────────────────────────────────────────────────────

class Timer:
    def __init__(self) -> None:
        self._start = time.time()
        self.marks: dict[str, float] = {}

    def mark(self, seg: str) -> float:
        elapsed = time.time() - self._start
        self.marks[seg] = elapsed
        print(f"  [t={elapsed:.1f}s] {seg}")
        return elapsed

    def save(self, path: Path) -> None:
        path.write_text(json.dumps(self.marks, indent=2))
        print(f"  [timer] Timestamps → {path}")


# ── Main orchestration ──────────────────────────────────────────────────────────

async def run_demo(args: argparse.Namespace, timer: Timer, video_dir: Path) -> None:
    room = args.room
    dry_run = args.dry_run
    audio_dir = Path(args.audio_dir)

    def dur(filename: str, fallback: float = 20.0) -> float:
        return segment_duration(audio_dir, filename, fallback)

    d = {
        "seg1":  dur("seg1.mp3",  24),
        "seg2":  dur("seg2.mp3",   4),
        "seg3":  dur("seg3.mp3",  33),
        "seg4":  dur("seg4.mp3",   7),
        "seg4c": dur("seg4c.mp3", 21),
        "seg4b": dur("seg4b.mp3", 27),
        "seg5":  dur("seg5.mp3",  25),
        "seg6":  dur("seg6.mp3",  23),
        "seg7":  dur("seg7.mp3",  27),
        "seg8":  dur("seg8.mp3",  10),
        "seg8b": dur("seg8b.mp3", 18),
        "seg9":  dur("seg9.mp3",   8),
    }
    print("  Audio durations:", {k: f"{v:.1f}s" for k, v in d.items()})

    async with async_playwright() as pw:
        browser = await pw.chromium.launch(headless=True)

        # Playwright records exactly what the browser renders — no display needed
        ctx = await browser.new_context(
            viewport={"width": 1920, "height": 1080},
            **({"record_video_dir": str(video_dir),
                "record_video_size": {"width": 1920, "height": 1080}}
               if not dry_run else {}),
        )
        # Reset timer NOW — recording starts when the context is created.
        # Without this, timestamps are offset by browser-launch time (~1-3 s),
        # making merge-av.py seek too far into the webm and capture navigation
        # transitions that should land in trimmed gaps.
        timer._start = time.time()
        page = await ctx.new_page()

        # seg1–seg2: show local Mycelium intro slide (no network flicker)
        intro_path = Path(__file__).parent / "mycelium-intro.html"
        await page.goto(f"file://{intro_path.resolve()}")
        await page.wait_for_load_state("domcontentloaded")

        # ── seg1: Hook + IoC framing ─────────────────────────────────────────────
        timer.mark("seg1")
        await asyncio.sleep(d["seg1"])
        timer.mark("seg1_end")

        # ── seg2: Bridge narration ────────────────────────────────────────────────
        timer.mark("seg2")
        await asyncio.sleep(d["seg2"])
        timer.mark("seg2_end")

        # Gap: navigate to slide (trimmed).
        # Wait > tail_buffer (3 s default) before navigating so the seg2 clip
        # tail stays clean on slide1.  Then navigate and wait for full paint
        # before marking seg3, giving a clean hard-cut to slide2.
        await asyncio.sleep(3.5)
        slide_path = Path(__file__).parent / "dissent-positions.html"
        await page.goto(f"file://{slide_path.resolve()}")
        await page.wait_for_load_state("load")   # not just domcontentloaded
        await asyncio.sleep(0.5)                  # let browser fully paint

        # ── seg3: Dissent-map slide ───────────────────────────────────────────────
        timer.mark("seg3")
        await asyncio.sleep(d["seg3"])
        timer.mark("seg3_end")

        # Gap: navigate to UI (trimmed)
        await page.goto(FRONTEND_URL)
        await page.wait_for_load_state("networkidle")

        # ── seg4: "We create a room..." plays while room list is visible ───────────
        timer.mark("seg4")
        await asyncio.sleep(d["seg4"])  # short — just the room-creation sentence
        timer.mark("seg4_end")

        # Spawn first agent only — navigate the moment session exists
        await create_room(page, room)
        agent_procs: list[subprocess.Popen] = []
        if not dry_run:
            agent_procs.append(spawn_agent(PERSONAS[0], room))
            await navigate_to_active_session(page, room)
        else:
            print("  [agent] Dry run — skipping agent wait")

        # ── seg4c: First agent visible — stagger remaining joins during this clip ──
        timer.mark("seg4c")
        await scroll_to_top(page)
        if not dry_run:
            await asyncio.sleep(3)
            agent_procs.append(spawn_agent(PERSONAS[1], room))
            await asyncio.sleep(3)
            agent_procs.append(spawn_agent(PERSONAS[2], room))
            await asyncio.sleep(3)
            agent_procs.append(spawn_agent(PERSONAS[3], room))
            remaining = d["seg4c"] - 9
            if remaining > 0:
                await asyncio.sleep(remaining)
        else:
            await asyncio.sleep(d["seg4c"])
        timer.mark("seg4c_end")

        # Wait for TOPIC banner with CE-structured issues (not just "issues not yet structured")
        if not dry_run:
            await wait_for_discussion_banner(page, timeout=120, require_issues=True)

        # ── seg4b: All 4 joined — expand TOPIC banner ────────────────────────────
        timer.mark("seg4b")
        await expand_discussion_banner(page)
        await asyncio.sleep(d["seg4b"])
        timer.mark("seg4b_end")
        # Collapse banner before moving to negotiation
        await expand_discussion_banner(page)  # second click collapses it

        # ── seg5: Early negotiation rounds ───────────────────────────────────────
        timer.mark("seg5")
        await scroll_to_top(page)
        await asyncio.sleep(2)
        for _ in range(3):
            await scroll_to_bottom(page)
            await asyncio.sleep(3)
            await scroll_to_top(page)
            await asyncio.sleep(2)
        timer.mark("seg5_end")

        # Pre-seg6: wait for impasse, then wait for ruling textarea to render
        if not dry_run:
            await wait_for_impasse(page)
            # Ruling section only appears after session state updates to broken
            ruling_box = page.get_by_placeholder("Enter your ruling…")
            try:
                await ruling_box.wait_for(state="visible", timeout=30_000)
            except Exception:
                pass
        await scroll_to_bottom(page)
        # Scroll to show dissent section + ruling textarea
        await page.evaluate("""() => {
            // Try scrolling the textarea into view with block: 'center'
            const el = document.querySelector('[placeholder="Enter your ruling…"]');
            if (el) {
                el.scrollIntoView({ behavior: 'instant', block: 'center' });
                return;
            }
            // Fallback: scroll any overflow container to bottom
            document.querySelectorAll('*').forEach(el => {
                if (el.scrollHeight > el.clientHeight) el.scrollTop = el.scrollHeight;
            });
        }""")
        await asyncio.sleep(1)

        # ── seg6: Impasse banner + ruling textarea both visible ───────────────────
        timer.mark("seg6")
        await asyncio.sleep(d["seg6"])
        timer.mark("seg6_end")

        # ── seg7: Human types ruling ─────────────────────────────────────────────
        timer.mark("seg7")
        await type_ruling(page, HUMAN_RULING, room)
        await asyncio.sleep(8)
        timer.mark("seg7_end")

        # Pre-seg8: navigate to session 2, wait for consensus (trimmed gap)
        session1_url = page.url
        if not dry_run:
            await navigate_to_next_session(page, room, session1_url)
            await wait_for_consensus(page)

        # Wait until session 2 content is visible before marking seg8
        if not dry_run:
            print("  [ui] Waiting for session 2 to load…")
            await wait_for_negotiation_started(page)

        # ── seg8: Session 2 consensus ────────────────────────────────────────────
        timer.mark("seg8")
        await scroll_to_top(page)
        await asyncio.sleep(d["seg8"])
        timer.mark("seg8_end")

        # Navigate via breadcrumb so viewers see the path to the plan tab
        await asyncio.sleep(1)
        try:
            # Click room name in breadcrumb (e.g. "dissent-map-demo" link)
            await page.get_by_role("link", name=room, exact=True).first.click()
            await page.wait_for_load_state("networkidle")
        except Exception:
            await page.goto(f"{FRONTEND_URL}/room/{room}")
            await page.wait_for_load_state("networkidle")

        # Brief pause on CHANNEL tab so viewers see we're on the room page
        await asyncio.sleep(2)

        # Click PLAN tab
        try:
            await page.get_by_role("button", name="PLAN").click()
            await asyncio.sleep(1)
        except Exception:
            try:
                await page.get_by_text("PLAN", exact=True).first.click()
                await asyncio.sleep(1)
            except Exception:
                pass

        # ── seg8b: Show the compiled plan ────────────────────────────────────────
        timer.mark("seg8b")
        await asyncio.sleep(d["seg8b"])
        timer.mark("seg8b_end")

        # ── seg9: Wrap — stays on plan page ──────────────────────────────────────
        timer.mark("seg9")
        await asyncio.sleep(d["seg9"])

        timer.mark("end")
        await asyncio.sleep(2)

        # Close context first — this finalises the video file
        await ctx.close()
        await browser.close()

    for p in agent_procs:
        p.terminate()


# ── Entry point ─────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(description="Mycelium demo orchestrator")
    parser.add_argument("--room", default=ROOM_NAME_DEFAULT)
    parser.add_argument("--out-dir", default="./demo-output")
    parser.add_argument("--audio-dir", default="./audio")
    parser.add_argument("--dry-run", action="store_true", help="Skip agents and video recording")
    parser.add_argument("--merge", action="store_true", help="Run merge-av.py automatically after recording")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    video_dir = out_dir / "video"
    video_dir.mkdir(exist_ok=True)
    timestamps_path = out_dir / "timestamps.json"

    timer = Timer()

    print(f"\n🪨 Mycelium demo orchestrator")
    print(f"   Room:     {args.room}")
    print(f"   Out dir:  {out_dir}")
    print(f"   Dry run:  {args.dry_run}\n")

    asyncio.run(run_demo(args, timer, video_dir))
    timer.save(timestamps_path)

    if not args.dry_run:
        videos = list(video_dir.glob("*.webm"))
        if videos:
            webm = videos[0]
            final = out_dir / "demo-final.mp4"
            print(f"\n✅ Raw video : {webm}")
            print(f"   Timestamps: {timestamps_path}")

            if args.merge:
                print("\n  Merging audio…")
                merge_script = Path(__file__).parent / "merge-av.py"
                result = subprocess.run([
                    "python3", str(merge_script),
                    "--video", str(webm),
                    "--timestamps", str(timestamps_path),
                    "--audio-dir", args.audio_dir,
                    "--out", str(final),
                ])
                if result.returncode == 0:
                    print(f"\n✅ Final video: {final}")
                else:
                    print("WARNING: merge-av.py failed — run manually.")
            else:
                print(f"\nNext — merge audio:")
                print(f"  python merge-av.py \\")
                print(f"    --video {webm} \\")
                print(f"    --timestamps {timestamps_path} \\")
                print(f"    --audio-dir {args.audio_dir} \\")
                print(f"    --out {final}")
        else:
            print("WARNING: No .webm found in video dir — check Playwright output.")


if __name__ == "__main__":
    main()
