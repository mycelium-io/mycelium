# Voice

You can talk instead of type. Turn on the mic in any message box, and what you
say is typed into the box as you say it. The mic stays on until you turn it
off, so you can pause and keep going. Nothing is sent until you send it, so you
can read what you said and fix it first.

Voice is off unless you turn it on, because the speech model takes space and
memory. The default model takes about 150 MB on disk and about 500 MB of memory
while anyone is talking.

## Turning it on

In the desktop app, turn on **Talk instead of type** in the first-run screens or
in **Settings → Voice**. Mycelium restarts and downloads the speech model.

On a hub you run with the CLI:

```bash
mycelium config set voice.enabled true
mycelium config apply
mycelium up
```

The hub downloads the speech model into its data folder when it starts, and
keeps it across restarts. It checks the download matches the expected file
before using it. To stop the hub downloading anything, set `voice.download` to
`false` and put the files in the data folder under `models/voice` yourself.

Turning voice off removes the mic from every message box. The downloaded model
stays in `models/voice` until you delete it.

## Choosing a speech model

| | `fast` (the default) | `accurate` |
| --- | --- | --- |
| Model | Moonshine v2 base | NVIDIA Parakeet TDT 0.6B v2 |
| Download | about 150 MB, when the hub starts | about 480 MB, the first time a mic is turned on |
| Memory while anyone talks | about 500 MB | about 1.4 GB |
| Mistakes, on our test recordings | about 1 word in 16 | about half as many |

Both run on the hub's CPU, and both are English only. `accurate` waits for a
longer pause, about a second, before it types what you said.

To switch, run this and restart the hub:

```bash
mycelium config set voice.model accurate
mycelium config apply
mycelium up
```

In the desktop app, pick **Fast** or **Accurate** under **Settings → Voice** and
save. Mycelium restarts.

The first time you turn on a mic with `accurate`, the hub downloads the model,
which can take a few minutes. The line under the box says it's getting ready.
With `voice.download` set to `false`, put the model's folder
(`sherpa-onnx-nemo-parakeet-tdt-0.6b-v2-int8`) in `models/voice` yourself.

## Using it

Press the mic button beside Send, or ⌘⌥V (Ctrl+Alt+V on Windows and Linux). The
key works while you're typing, and acts on the message box you're in. The first
time, your browser or the desktop app asks to use the microphone.

Each time you pause, what you just said is added to the end of the draft. You
can keep talking, type a fix or send the message, and the mic stays on. Press
the button again to turn it off. Anything you were in the middle of saying
still lands in the draft.

After the mic has been off for a while, turning it on takes about a second.
Keep the mic on until your words appear. What you say meanwhile is transcribed
once it's ready.

## Where it's transcribed

Your hub turns speech into text on its own CPU. No audio is sent anywhere else.
In the desktop app the hub runs on your computer, so your audio never leaves
it. With a shared hub, your audio goes to that hub the way your messages do.

Audio is never saved. The hub keeps only the few seconds it's transcribing and
discards them once they're text.

The mic button is missing when voice is off, or when the hub has no model and
can't download one. It's also missing in the desktop app when the app is
connected to another hub. To talk to a remote hub, open it in a browser.

## Reading messages aloud

The app can also read messages to you. It says who sent each one and where,
then reads the message. A popover on the bell shows the words as they're read.
Click the popover to open the message, press **Read all** for the rest, or press
✕ or Esc to stop.

Mycelium ships no text-to-speech model. Whoever runs the hub points it at an
OpenAI-style text-to-speech server they run, such as one serving Kokoro's
voices:

```bash
mycelium config set voice.speech_url http://127.0.0.1:8880/v1
mycelium config set voice.speech_voice <a voice the server has>
mycelium config apply
mycelium up
```

If the server expects a model name, set `voice.speech_model`. If it asks for a
key, set `voice.speech_api_key`. You can also set all four on the Hub settings
page. The key stays on the hub, because the app asks the hub and the hub asks
the server. Reading aloud doesn't need the mic to be on, and the mic doesn't
need reading aloud.

Each person then turns it on for themselves under **Settings → Read aloud**.
**Try it** reads a sample line. The other choices there are:

| Setting | Choices |
| --- | --- |
| What it reads | Mentions of you and messages sent to you, or everything in rooms you pick |
| Skip what's in front of me | The thread you have open, the room you have open, or nothing |
| How much | The start, with **Read all** for the rest, or all of it |
| Voice | The hub's voice, or another the speech server lists |
| Speed | Normal, slower or faster |

Only a window you can see reads aloud, and only one at a time. It waits while a
mic is open, so what it says never lands in your draft. Do not disturb and muted
rooms keep it quiet. A browser plays nothing until you've clicked or typed in
the page once, so the first message after you open the app isn't read.
