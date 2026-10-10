# Voice

You can talk instead of type. Turn on the mic in any message box, in the room
or in a task's thread, and what you say is typed into the box as you say it.
The mic stays on until you turn it off, so you can think out loud, pause, and
keep going. Nothing is sent until you send it: what you said is a draft you
can read and fix first.

## Using it

Press the mic button beside Send, or ⌘⌥V (Ctrl+Alt+V on Windows and Linux),
which works while you're typing. The key acts on the message box you're in,
or the room's own box when you're in none. The first time, your browser or the
Mac app asks to use the microphone. While it's on, the button is lit, the line under
the box says it's listening, and a ring around the button pulses while it
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

The speech model is about 150 MB. The Mac app and the Docker image include it.
A hub without it downloads it the first time someone turns on a mic, and the
line under the box says it's getting ready. Keep the mic on until your words
appear: what you say meanwhile is held and transcribed once the model is
ready, but turning the mic off before then drops it.

The mic button is missing when the hub can't transcribe (it has no model and
can't download one), and in the Mac app when it's connected to another hub.
The app gives the microphone only to the hub it runs itself, so a remote hub's
pages can't listen; use that hub in a browser to talk to it.
