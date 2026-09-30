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

1. **Start a recording stack.** It uses port 8000, so stop your everyday stack
   first (`mycelium down`). Its data lives in `~/.mycelium-l9`, apart from your own.

   ```bash
   MYCELIUM_DATA_DIR=~/.mycelium-l9 docker compose -p mycelium-l9 \
     -f mycelium-cli/src/mycelium/docker/compose.yml \
     -f mycelium-cli/src/mycelium/docker/compose-dev.yml \
     -f shotkit/recordings/l9/compose-l9.yml \
     up -d --build slim mycelium-backend
   ```

2. **Start the app from this checkout**, pointed at that backend:

   ```bash
   cd mycelium-frontend
   MYCELIUM_INTERNAL_API_URL=http://localhost:8000 pnpm exec next dev -p 51268
   ```

3. **Record.** From the repo root, with the app's address:

   ```bash
   export APP_URL=http://localhost:51268
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

5. **Put it on the page.** Videos aren't committed. Drag the mp4 into a comment on
   the pull request, and GitHub gives it a `github.com/user-attachments/assets/...`
   address. Put that address in the `<video src>` in `docs/l9-integration.html`,
   and update the step table under the video if the run went differently.

## Why takes can fail, and why room names matter

A take is a live run, so it can end without agreement ("Couldn't get everyone
there" for Concord, a stopped run for Accord). Then the closing captions aren't
true, and `record.sh` moves on to the next room name.

With the same room name, the same prompts and a fresh backend, the model gives
the same run word for word. So repeating a failed take under the same name
fails the same way, and a name that worked before gives the same take again.
`acme-renewal-q4` gave the Concord video (agreement on option F after two
fixes) and `acme-handoff` gave the Accord video.

The backend restart before each try matters for the same reason: persona
teammates keep a model session per room and handle, so a room recreated under
an old name would otherwise remember the last take.

## When you're done

```bash
docker compose -p mycelium-l9 down
rm -rf ~/.mycelium-l9
```
