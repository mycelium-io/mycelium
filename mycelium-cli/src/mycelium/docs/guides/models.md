# Models

The hub's [engines](#engines) need a model to think with. This page is about
that one setting: what uses it, how to set it, and which models it can be.

## What uses it

One model, set on the hub, is used by every engine that thinks:

- the [aligner](#aligner), which helps agents agree when they disagree;
- [personas](#persona), which play a character you describe;
- [workers](#worker), which take tasks off the board and do them;
- the [synthesizer](#synthesizer), which writes summaries of a room;
- [hello](#hello), which just replies;
- the step that turns an aligner agreement into tasks on the board.

The [conductor](#conductor) uses none: it follows a flow in code. There's no
way yet to give different engines different models.

Agents you bring, like Claude Code, Codex or OpenCode, don't use this setting.
They sign in with their own accounts, the same way they do outside Mycelium.

## Set it

**In the Mac app**, the first run asks for it, and you can change it any time
in **Settings → Model** (⌘,). Pick a provider, paste a key, and save. The
model name is filled in for you.

**From the command line**:

```bash
mycelium config set llm.model "anthropic/claude-sonnet-4-6"
mycelium config set llm.api_key "<your key>"
mycelium config apply
```

`llm.base_url` sets the address for a provider the hub can't find on its own,
like Ollama or a company gateway.

Set this on the hub's machine; a spoke's model setting does nothing. The key is
saved in `~/.mycelium/config.toml` there, readable only by you, and passed to
the hub when it starts. Anything running inside the hub can read it, including
[workers](#worker). The Mac app
never shows it again after you save it, only its last four characters, so you
can tell which key is in use.

## Providers

| Provider | Model names look like | Key |
|---|---|---|
| Anthropic | `anthropic/claude-sonnet-4-6` | from console.anthropic.com |
| OpenAI | `openai/gpt-4.1` | from platform.openai.com |
| OpenRouter | `openrouter/anthropic/claude-sonnet-4-6` | from openrouter.ai |
| Ollama | `ollama/llama3.3` | none; set the address to where Ollama runs |
| Other | `provider/model` | if the service needs one; set its address |

A name is always the provider, a slash, then the model.

## Under the hood

The engines run on [Pi](https://github.com/earendil-works/pi), an
open-source agent runtime that talks to many model providers. Any
`provider/model` that Pi knows works here. Its
[model catalog](https://pi.dev/models) lists every provider and model name,
with their context limits and prices.

## Check it

In the Mac app, **Settings → Model** says whether the model answered, and
**Health check…** shows it under **Models**. From the command line,
`mycelium doctor` asks the model for a real reply and says what went wrong if
it can't get one: a missing key, a key the provider refuses, or a model name
it doesn't know.
