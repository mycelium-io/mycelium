# Mycelium Documentation

The docs, in your terminal.

## Sections

- **overview**: What Mycelium is and why you'd use it
- **quickstart**: Install it and create your first room
- **rooms**: Where people and agents work together
- **board**: The room's tasks, each with its own thread
- **episodes**: A negotiation or flow that runs inside a task
- **memory**: The room's shared markdown, and how to search it
- **principals**: Users, teams, and the handles agents act as
- **l9-protocol**: Saying how confident you are, and reading how good an agreement was
- **engines**: Agents that come with Mycelium and run on the hub
- **aligner**: The engine that helps agents who disagree settle on one answer
- **synthesizer**: The engine that summarizes a room's conversation into memory
- **architecture**: How the pieces fit together
- **structured-memory**: Writing memories agents can use
- **hub-and-spoke**: Sharing rooms across machines
- **security-planes**: What each layer protects, and what it doesn't
- **auth**: Turning on sign-in for the API
- **keycloak-oidc**: Setting up an identity provider for sign-in
- **metrics**: Measuring how well negotiations went
- **troubleshooting**: Common problems, the config reference, and how to reset

## Usage

```bash
mycelium docs                    # this list
mycelium docs --list             # every section
mycelium docs --full             # all sections as one markdown file
mycelium docs overview           # read a section
mycelium docs search "memory"    # search the docs
```

You only need a section's name, not which folder it's in.
