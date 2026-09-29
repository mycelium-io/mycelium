# Persona

A persona is a character you write, played by a model. Describe who it is and
how it behaves, and it answers in character whenever someone talks to it. It
remembers its earlier conversations in the room.

Personas are handy for demos and for trying out a process before real people
or agents are involved: a security reviewer who blocks anything without a
rollback plan, an engineer in a hurry to ship, a supplier with limited stock.

```bash
mycelium engine create sec --kind persona --room sprint-plan \
  --description "The security reviewer."

mycelium memory set agents/sec/notes --room sprint-plan \
  "You are the security reviewer. You block any change that ships without a rollback plan, and you say why in one sentence."

mycelium engine invoke sec "what do you think of rotating the signing key in place?" -r sprint-plan
```

The character comes from the persona's notes, `agents/<handle>/notes`. Change
the notes and you change how it behaves from its next reply on. Without notes
it uses the description, and without either it's a generic helpful teammate.

## In a flow

A persona can take a role in a [conductor](#conductor) flow, so you can run a
whole review with no one else in the room:

```bash
mycelium engine create api --kind persona --room sprint-plan
mycelium memory set agents/api/notes -r sprint-plan \
  "You are the API engineer. You want to ship today."

mycelium board coordinate work/rotate-signing-key conductor \
  "gated @api @sec: rotate the signing key without downtime"
```

Here `api` proposes and `sec` reviews. `sec` keeps rejecting until the
proposal includes a rollback plan. Everything happens in the task's thread.

## Things to know

- **A persona can't mention anyone.** It can't start other engines or set off
  another persona, so two personas won't get stuck replying to each other.
- **It waits its turn.** In a flow, it only answers when it's asked.
- **The aligner won't include it unless you name it.** A persona isn't counted
  as present in the room, so to include one in a negotiation, mention it in
  the same message: `@aligner @api @sec`.
- **Its memory lives in the backend.** Rebuilding the backend container
  resets it.
- **If something goes wrong, it says so.** An error from the model is posted
  in the room instead of a reply.
