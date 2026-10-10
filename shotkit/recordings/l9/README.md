# L9 recordings: Concord and Accord

The two videos on `docs/l9-integration.html` are real runs in the app, recorded
with `shot video`. These files re-record them: a room with four persona
teammates (customer success, finance, sales, legal) disagreeing about a
customer's renewal, one take of Concord on "Decide the renewal offer for Acme",
and one take of Accord on "Plan the Acme renewal handoff".

| File | What it does |
|---|---|
| `compose-l9.yml` | Runs a separate SLIM node and backend for recording, beside your everyday stack's files. |
| `setup.py` | Deletes earlier `acme-*` rooms, then makes the room: engines, the four personas and their notes, Morgan (the person the recording posts as), and the two tasks. |
| `concord.sh`, `accord.sh` | One take each: the clicks, the message that starts the flow, the captions, and where to speed up, wait and zoom. Edit these to change what the video shows. |
| `record.sh` | Restarts the backend, sets up a room and records a take, once per room name you give it, and stops at the first take that ends the way the captions say. |

## Record

You need Docker, `uv`, `pnpm`, a full `ffmpeg` on your PATH (for mp4), and a
model key in `~/.mycelium/.env` (the personas and the conductor's teammates
run on it; the videos used `anthropic/claude-haiku-4-5`).

1. **Start a recording stack.** Its data lives in `~/.mycelium-l9`, apart from
   your own. It runs on ports 8100 (the hub) and 46457 (SLIM), so it sits beside
   a hub you already run on 8000, such as the desktop app's.

   ```bash
   MYCELIUM_REPO_ROOT=$PWD MYCELIUM_DATA_DIR=~/.mycelium-l9 \
   MYCELIUM_BACKEND_PORT=8100 MYCELIUM_SLIM_PORT=46457 \
   docker compose -p mycelium-l9 \
     -f mycelium-cli/src/mycelium/docker/compose.yml \
     -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
     -f shotkit/recordings/l9/compose-l9.yml \
     up -d --build slim mycelium-backend
   ```

2. **Start the app from this checkout**, pointed at that backend:

   ```bash
   cd mycelium-frontend
   MYCELIUM_INTERNAL_API_URL=http://localhost:8100 pnpm exec next dev -p 51268
   ```

3. **Record.** From the repo root, with the app's address and the recording
   hub's. Always set `HUB`: setup deletes every `acme-*` room on the hub it is
   pointed at.

   ```bash
   export APP_URL=http://localhost:51268 HUB=http://localhost:8100
   bash shotkit/recordings/l9/record.sh concord acme-renewal-q4 acme-renewal-2027 acme-q4-renewal
   bash shotkit/recordings/l9/record.sh accord acme-handoff acme-renewal-handoff
   ```

   Each take is a live run of 2 to 3 minutes, played back at up to 5 times
   speed while it waits for replies. The kept take is printed, for example
   `.shotkit/l9-concord-acme-renewal-q4.mp4`, with its log beside it.

4. **Look at it.** A contact sheet is the quickest check:

   ```bash
   ffmpeg -i .shotkit/l9-concord-acme-renewal-q4.mp4 -vf "fps=1/3,scale=720:-1,tile=4x4" -frames:v 1 sheet.png
   ```

5. **Put it on the page.** Copy the kept take to `docs/l9-concord.mp4` or
   `docs/l9-accord.mp4` (committed through Git LFS, like every video under
   `docs/`), take a poster frame for `docs/l9-<flow>-poster.jpg`, and update the
   step table under the video in `docs/l9-integration.html` from the run's record.

## Why takes can fail, and why room names matter

A take is a live run, so it can end without agreement ("Couldn't get everyone
there" for Concord, a run where nobody gave any points for Accord). Then the closing captions aren't
true, and `record.sh` moves on to the next room name.

With the same room name, the same prompts and a fresh backend, runs often come
out alike, but not reliably word for word: repeated Accord tries on one name
gave different points each time. `acme-renewal-2027` gave the current Concord
video (agreement on option F after two fixes, where `acme-renewal-q4` ended
without one) and `acme-handoff` gave the Accord video.

The backend restart before each try matters because persona teammates keep a
model session per room and handle, so a room recreated under an old name would
otherwise remember the last take.

## When you're done

```bash
docker compose -p mycelium-l9 down
rm -rf ~/.mycelium-l9
```
