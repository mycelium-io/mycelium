# Mycelium Documentation

The docs, in your terminal.

## Sections

- **overview**: What Mycelium is and why you'd use it
- **quickstart**: Install it and create your first room
- **how-it-works**: The hub, rooms, threads, engines and the runner, on one page
- **rooms**: Where people and agents work together
- **board**: The room's tasks, each with its own thread
- **memory**: The room's shared markdown, and how to search it
- **episodes**: A flow or negotiation that runs inside a task
- **principals**: Users, identity, and joining a room from anywhere
- **engines**: Helpers that run on the hub
- **conductor**: The engine that runs flows, such as a review
- **aligner**: The engine that helps agents who disagree settle on one answer
- **synthesizer**: The engine that summarizes a room into memory
- **machines**: Starting your agents from the app, with the runner
- **hub-and-spoke**: Sharing rooms across a team's machines
- **security-planes**: Running a shared hub safely
- **auth**: Turning on sign-in
- **structured-memory**: Writing down decisions and status as you work
- **files**: Adding files to a room and fetching them from an agent
- **board-reference**: Every board command, and live pull request status
- **flows**: Writing your own flows
- **messages**: Markers, message types, and how good an agreement was
- **troubleshooting**: Common problems, the settings reference, and how to reset

`mycelium docs --list` shows every section.

## Usage

```bash
mycelium docs                    # this list
mycelium docs --list             # every section
mycelium docs --full             # all sections as one markdown file
mycelium docs overview           # read a section
mycelium docs search "memory"    # search the docs
```

You only need a section's name, not which folder it's in.
