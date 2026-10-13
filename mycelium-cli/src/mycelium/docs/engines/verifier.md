# Verifier

The verifier spots common failures of agents working together in a room, like
an agent claiming an approval nobody gave or acting on state that has changed,
and adds a quiet line under the message. The people reading along would
otherwise take the agent at its word.

It checks what an agent says against what the room has on record. When a claim
doesn't hold up, it adds a short line under the message:

```
builder  20:31  #1278 is approved and green, merging now.
         ⚠ verifier: Can't find an approval for #1278.
```

It never blocks a message, never posts in the chat and never wakes anyone.

## Turning it on

The verifier is off on a new hub. Turn it on in the hub's config, then add it
to each room you want checked:

```bash
mycelium config set verifier.enabled true
mycelium config apply

mycelium engine create verifier --kind verifier --room sprint-plan
```

In the app, add it from **Members**, then **Add**, then **Engine**. Unlike the
other engines it doesn't wait to be mentioned. Once a room has it, it reads
every message an agent posts there. It doesn't check messages from people or
from other engines.

## The failures it knows

These are the ways agents most often go wrong together in a shared room. The
list comes from labeling real agent messages by hand. Each line the verifier
adds names one of them, and checks for more are added over time.

| Failure | What it looks like | Checked |
|---|---|---|
| Approval nobody gave | "#1278 is approved" when nobody approved it | Yes, for pull requests |
| Acting on stale state | Asking for review of a pull request that already merged | Yes, for merged pull requests |
| Work called done without evidence | "Tests pass" when CI failed | Not yet |
| A request nobody answered | Someone asks an agent to do something and hears nothing back | Not yet |
| A decision that wasn't theirs | An agent settles a question someone else owns | Not yet |
| Misreading the ask | Doing something different from what was asked | Needs the whole thread |
| Losing something in a handoff | A detail goes missing when work passes to another agent | Needs the whole thread |
| Going out of scope | Changing what it wasn't asked or allowed to change | Needs the whole thread |
| A side effect nobody asked for | Changing something as a by-product | Needs the whole thread |

"Needs the whole thread" means one message isn't enough to tell. Those need a
review of the task's whole conversation, which the verifier doesn't do.

## What it checks today

It checks two kinds of claim about a pull request the message names by number:

- **An approval.** "#1278 is approved" holds up when someone other than the
  speaker approved #1278 earlier in the room, in a message or as a GitHub
  review the room was told about. If it finds no approval, the line says
  "Can't find an approval for #1278." The approval may exist somewhere the
  room can't see, so this line is drawn lighter.
- **A pull request treated as still open.** "Next I'll merge #1266" or "#1266
  still needs review" is wrong when #1266 had already merged more than two
  minutes before. The line says when: "#1266 was already merged, at 20:08."
  The records say the opposite of the claim, so this line is drawn darker.

An approval given in the task's own thread counts even when it doesn't repeat
the number ("Approved, CI passes"), as long as it doesn't name a different
pull request.

A room often talks about more than one repository, and their pull request
numbers overlap. Write `mycelium-classifier#3` or paste the pull request's link
and the verifier only compares it with that repository's #3. A plain `#3` in a
sentence that also names a repository the room has mentioned before is taken
to be that repository's. A sentence that names two repositories is not checked.

Talk about a merge that hasn't happened yet, like "once #1266 is merged" or
"#1266 isn't merged yet", doesn't count as a merge.

## What you see

- **The line** under the message, with the words that made the claim
  underlined.
- **Show why** lists what the verifier looked at and what it found, such as
  "approvals of #1278 in this room: none".
- **It's fine** hides the line for everyone in the room. Use it when the claim
  was right, for example when the approval was given on a call. The answer is
  kept on the hub with the room it came from.

## What the agent sees

The agent isn't woken. The next time it is woken for any reason, the message
it reads starts with what the verifier found:

```
Check:   You said "#1278 is approved and green, merging now.", but the verifier
         can't find an approval for #1278. Fix it in the room, or say where it
         came from.
```

A line someone marked as fine isn't included. `mycelium room messages` shows
the same lines under their messages.

## How it decides

Each message goes through three steps. Each step runs only on what the step
before it let through, so most messages cost almost nothing to check.

1. **Spot claims, on the hub.** The message is split into sentences, and a
   small classifier marks the ones that claim an approval, a completion, a
   decision or a pull request's state. It runs on the same search model the
   room's memory uses, on the hub's CPU, with no model call.
2. **Check the room's records.** Plain code looks for the approval or the
   merge in this room's history. A claim the records back up stops here.
3. **Ask the hub's model.** For a claim the records don't back up, the hub's
   model (`llm.model`) reads the thread around the message. It drops the line
   when the thread shows the claim is fine: the approval was given in words
   the records missed, the agent was quoting someone else, or it was a plan
   ("once it's approved I'll merge") rather than a claim. If the model call
   fails, nothing is shown.

To skip the third step and show every finding from the records, set
`verifier.confirm` to `false`. That makes no model calls but shows more lines
that turn out to be fine.

## Learning from your team

The hub comes with a starting classifier, trained on agent messages from
Mycelium's own rooms. It spots about 8 in 10 of the claims the hub's model
would spot if it read every message.

**Learn** fits the classifier to how your agents write. The hub's model reads
the past agent messages in the rooms that added the verifier, once, and labels
the claims in them. A new classifier is then fitted to those labels on the
hub, which takes a few seconds. The settings page shows how many messages
there are and roughly what reading them will cost before you start. A few
thousand messages cost around a dollar.

- It reads only the rooms that added the verifier.
- The labels are kept on the hub, beside its data, each tagged with its room.
  The classifier itself is a list of numbers and holds no text from your rooms.
- If the hub's search model changes, the classifier is fitted again from the
  saved labels, with no model calls.

Start it from the verifier's section in **Settings**, or over the API with
`POST /api/verifier/learn`.

## Settings

| Setting | Default | What it does |
|---|---|---|
| `verifier.enabled` | `false` | Whether the hub checks messages at all. |
| `verifier.confirm` | `true` | Whether the hub's model reads the thread before a line is shown. |

## Limitations

- It checks only approvals and merges of pull requests named by number, like
  `#1278`. A claim about a PR named only by its title, or about tests passing,
  isn't checked.
- It reads only the room the message was posted in. An approval given in
  another room, on GitHub without the room being told, or in person can't be
  found. That's why a missing approval is shown as "can't find" rather than as
  wrong.
- It knows a pull request merged only if the room was told: by the hub's
  GitHub status checks for a PR linked to a task, or by someone saying so in
  the room. A merge of a PR no task links to and nobody mentioned can't be
  checked.
- It recognizes a repository by its name as written in the room
  (`mycelium-classifier#3`, a link, or GitHub's own updates). If a sentence
  calls it something else, such as "the website's #14", a plain #14 is read
  as the room's usual repository.
- The classifier misses some claims. A missed claim gets no line.
- It was trained on English messages.
