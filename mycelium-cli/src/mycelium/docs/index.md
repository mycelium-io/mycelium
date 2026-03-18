# Mycelium CLI Documentation

Built-in reference for the Mycelium multi-agent coordination CLI.

## Sections

- **concepts** — Core ideas: rooms, memory, coordination, synthesis
- **guides** — How-to walkthroughs for common workflows

## Quick Start

```bash
mycelium init              # Set up local config
mycelium up                # Start the backend
mycelium room create lab   # Create a room
mycelium room set lab      # Make it your active room
mycelium memory log work/setup "Initialized the project"
mycelium memory status     # See what's active
mycelium catchup           # Get briefed on a room
```

## Browse

```bash
mycelium docs --list                  # List all docs
mycelium docs concepts memory         # Read about memory
mycelium docs guides structured-memory # Structured memory guide
mycelium docs search "synthesis"      # Search docs
```
