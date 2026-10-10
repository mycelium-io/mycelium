# Voice

You can talk instead of type. Turn on the mic in any message box, in the room
or in a task's thread, and what you say is typed into the box as you say it.
The mic stays on until you turn it off, so you can think out loud, pause, and
keep going. Nothing is sent until you send it: what you said is a draft you
can read and fix first.

Voice is off unless you turn it on, because the speech model takes space and
memory: about 150 MB on disk, and about 500 MB of memory while anyone is
talking.

## Turning it on

In the Mac app, turn on **Talk instead of type** in the first-run screens or
in Settings, under Voice. Mycelium restarts and downloads the speech model.

On a Docker hub, or any hub you run with the CLI:

```bash
mycelium config set voice.enabled true
mycelium config apply
mycelium up
```

The hub downloads the speech model when it starts, into its data folder, so
it's downloaded once and kept across restarts. The download is checked against
the file it should be before it's used. With `voice.download` set to false the
hub never downloads anything, and you put the files in the data folder under
`models/voice` yourself.

Turning voice off again (`voice.enabled false`, or the switch in the Mac app)
removes the mic from every message box. The downloaded model stays in the data
folder, and you can delete `models/voice` to get the space back.

## Using it

Press the mic button beside Send, or ⌘⌥V (Ctrl+Alt+V on Windows and Linux),
which works while you're typing. The key acts on the message box you're in,
or the room's own box when you're in none. The first time, your browser or the
Mac app asks to use the microphone. While it's on, the button is lit, the line
under the box says it's listening, and a ring around the button pulses while it
hears you speak.

Each time you pause, what you just said is added to the end of the draft. Keep
talking, type a fix, or send the message, and the mic stays on. Press the
button again to turn it off; anything you were in the middle of saying still
lands in the draft.

Voice is English only for now.

## Where it's transcribed

Your hub turns speech into text, on its own CPU, with a small speech model
(Moonshine) and a voice activity detector (Silero) that hears where you start
and stop. Neither sends audio anywhere else. In the Mac app the hub runs on
your machine, so your audio never leaves it. With a shared hub, your audio goes
to that hub the way your messages do.

Audio is never saved. The hub keeps only the few seconds it is listening to,
and lets go of them once they're text.

The model runs in a separate process that the hub starts when someone turns on
a mic and that stops about five minutes after the last mic is turned off. That's
when its memory is given back. Starting it takes about a second, during which
the line under the box says it's getting ready. Keep the mic on until your words
appear: what you say meanwhile is held and transcribed once it's ready, but
turning the mic off before then drops it.

The mic button is missing when voice is off or the hub can't run it (it has no
model and can't download one), and in the Mac app when it's connected to
another hub. The app gives the microphone only to the hub it runs itself, so a
remote hub's pages can't listen; use that hub in a browser to talk to it.
