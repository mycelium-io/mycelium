# Feature Specification: Mycelium Baseline System

**Feature Branch**: `001-baseline-spec`
**Created**: 2026-03-23
**Status**: Baseline (documents existing system)
**Input**: User description: "Baseline specification of existing mycelium system"

---

> **Note**: This is a brownfield baseline spec. It describes what the system already does,
> establishing the foundation for future feature specs. It is not a new feature proposal.

---

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Agent Stores and Retrieves Persistent Memory (Priority: P1)

An AI agent working on a project needs to save context that persists beyond the current
session — decisions made, approaches tried, findings from research. The agent writes
named memories into a shared room and can retrieve or search them in any future session,
even from a different machine if the room directory is committed to git.

**Why this priority**: Memory persistence is the core value proposition. Without it,
every agent session starts from zero.

**Independent Test**: An agent writes a memory, the session ends, a new session reads
the same memory back by key and by semantic search.

**Acceptance Scenarios**:

1. **Given** an agent has a room set, **When** it runs `mycelium memory set "decision/api-style" "REST"`, **Then** a markdown file appears at `.mycelium/rooms/{room}/decision/api-style.md` with the value and YAML frontmatter
2. **Given** a memory exists, **When** the agent runs `mycelium memory get "decision/api-style"`, **Then** the stored value is returned
3. **Given** multiple memories exist, **When** the agent runs `mycelium memory search "what was decided about the API"`, **Then** semantically relevant memories are returned ranked by relevance
4. **Given** the `.mycelium/rooms/` directory is committed to git and checked out on another machine, **When** the agent runs `mycelium memory get "decision/api-style"` on that machine, **Then** the same value is returned

---

### User Story 2 - Multiple Agents Coordinate in Real Time (Priority: P2)

Two or more AI agents need to reach a shared decision — e.g., agreeing on an
architectural approach, dividing work, or resolving a conflict between proposals.
They join a coordination session within a shared room; the CognitiveEngine mediates
structured negotiation rounds and produces a consensus outcome that all agents receive.

**Why this priority**: Real-time coordination is what differentiates mycelium from
simple shared memory. Without it, agents can only communicate asynchronously via memory.

**Independent Test**: Two agents join a session, submit proposals, and both receive
the same consensus decision from the CognitiveEngine.

**Acceptance Scenarios**:

1. **Given** a room exists, **When** an agent runs `mycelium session join --handle agent-a -m "I propose GraphQL"`, **Then** the agent is registered in the session and the CognitiveEngine is notified
2. **Given** a session is active with multiple agents, **When** each agent submits a proposal, **Then** the CognitiveEngine drives negotiation rounds and addresses agents in turn
3. **Given** negotiation is complete, **When** consensus is reached, **Then** all agents receive a `{"type": "consensus", ...}` message with the agreed outcome
4. **Given** an agent uses `mycelium session await`, **When** the CognitiveEngine addresses that agent, **Then** the command unblocks and outputs a structured JSON tick message

---

### User Story 3 - Agent Catches Up on Room Context (Priority: P2)

An agent joining a room mid-project needs to get up to speed quickly without reading
every individual memory. It runs `mycelium catchup` to get the CognitiveEngine's
latest synthesis of accumulated context, plus a summary of recent activity since
that synthesis.

**Why this priority**: Without a catchup mechanism, each new agent session must
manually enumerate and read memories, which doesn't scale.

**Independent Test**: An agent populates a room with several memories, a second agent
(new session) runs `catchup` and receives a coherent summary of what has happened.

**Acceptance Scenarios**:

1. **Given** a room has accumulated memories and a prior synthesis, **When** an agent runs `mycelium catchup`, **Then** the latest synthesis plus post-synthesis activity is returned
2. **Given** no synthesis exists yet, **When** an agent runs `mycelium catchup`, **Then** a meaningful summary of existing memories is returned
3. **Given** an agent runs `mycelium room synthesize`, **Then** the CognitiveEngine processes accumulated memories and writes a new synthesis, which subsequent `catchup` calls will return

---

### User Story 4 - Human Views Room Activity via Frontend (Priority: P3)

A human team member or project lead wants to observe what AI agents have been doing
in a room — what memories have been written, what decisions were reached, what sessions
occurred. They open the web frontend to browse room contents without needing CLI access.

**Why this priority**: Observability for humans is important but not blocking for
agent workflows. Agents work without it; humans benefit from it.

**Independent Test**: Memories written via CLI are visible in the frontend room viewer
without any manual sync step.

**Acceptance Scenarios**:

1. **Given** memories exist in a room, **When** a user opens the frontend and navigates to that room, **Then** memories are listed by namespace with their content readable
2. **Given** a new memory is written, **When** the user refreshes the frontend, **Then** the new memory appears
3. **Given** the user selects a memory, **When** the detail view opens, **Then** the full markdown content and metadata (handle, timestamp, version) are visible

---

### User Story 5 - Agent Connects via Adapter (Priority: P3)

An AI agent running inside Claude Code or the OpenClaw runtime needs to participate
in mycelium coordination without manual CLI setup. The adapter hooks into the
agent's lifecycle and exposes mycelium commands as a skill within the agent's toolset.

**Why this priority**: Adapters lower the adoption barrier but the core system works
without them.

**Independent Test**: A Claude Code session can run `mycelium memory set` and
`mycelium session join` via the skill without any manual setup beyond installing the adapter.

**Acceptance Scenarios**:

1. **Given** the Claude Code adapter is installed, **When** the agent invokes the mycelium skill, **Then** it can run memory and session commands within the conversation
2. **Given** the OpenClaw adapter is installed, **When** the OpenClaw agent runtime starts, **Then** mycelium commands are available as part of the agent's tool palette

---

### Edge Cases

- What happens when two agents write to the same memory key simultaneously? (Last write wins; version counter increments)
- What happens when a session times out with no consensus? (`{"type": "timeout"}` is returned to all awaiting agents)
- What happens when the backend is unreachable and an agent tries `memory set`? (CLI reports a connection error; no partial write occurs)
- What happens when a room directory is missing from the filesystem? (Backend auto-creates the directory structure on first write)
- What happens when semantic search embeddings are not yet indexed for a new memory? (Search may not return it immediately; `reindex` resolves this for out-of-band writes)

## Requirements *(mandatory)*

### Functional Requirements

**Memory**

- **FR-001**: The system MUST allow agents to write named memories to a room using `mycelium memory set <key> <value>`
- **FR-002**: The system MUST persist memories as markdown files with YAML frontmatter at `.mycelium/rooms/{room}/{namespace}/{key}.md`
- **FR-003**: The system MUST allow agents to retrieve a memory by key using `mycelium memory get <key>`
- **FR-004**: The system MUST allow agents to list memories, optionally filtered by key prefix
- **FR-005**: The system MUST allow agents to search memories using natural language via vector embeddings
- **FR-006**: The system MUST allow agents to delete a memory by key
- **FR-007**: Memory writes MUST be upserts — writing to an existing key overwrites the value and increments the version counter
- **FR-008**: The system MUST support subscribing to memory key pattern changes

**Rooms**

- **FR-009**: The system MUST allow agents to create named rooms
- **FR-010**: The system MUST allow agents to set an active room, scoping all subsequent memory and session commands
- **FR-011**: Rooms MUST persist across sessions and MUST NOT be automatically deleted
- **FR-012**: Room directories MUST be git-friendly (plain markdown files, no binary artifacts)

**Coordination**

- **FR-013**: The system MUST allow agents to join a coordination session within a room with an initial position
- **FR-014**: The CognitiveEngine MUST mediate all negotiation — agents MUST NOT communicate directly with each other
- **FR-015**: The system MUST support a blocking `session await` command that unblocks when the CognitiveEngine addresses the calling agent
- **FR-016**: `session await` MUST output structured JSON with action type: `propose`, `respond`, `consensus`, or `timeout`
- **FR-017**: The CognitiveEngine MUST produce a consensus outcome and deliver it to all session participants
- **FR-018**: The system MUST support triggering room synthesis on demand via `mycelium room synthesize`
- **FR-019**: The system MUST support `mycelium catchup` to retrieve the latest synthesis plus post-synthesis activity

**Adapters**

- **FR-020**: A Claude Code adapter MUST expose mycelium commands as a usable skill within Claude Code sessions
- **FR-021**: An OpenClaw adapter MUST expose mycelium commands within the OpenClaw agent runtime

### Key Entities

- **Room**: A persistent named namespace. Contains memories organized by namespace subdirectory. Scopes all agent coordination.
- **Memory**: A named piece of agent-written context. Stored as a markdown file with YAML frontmatter (key, value, handle, timestamp, version). Searchable via embeddings.
- **Session**: An ephemeral real-time coordination context spawned within a room. Ends when consensus is reached or timeout occurs.
- **Agent**: Identified by a `handle` string. Metadata on memories and session messages — not a stored entity in the primary workflow.
- **Synthesis**: A CognitiveEngine-generated summary of accumulated room memories. Written back as a special memory. Serves as the "current state" snapshot for new participants.
- **Workspace / MAS**: Registry-level groupings that organize rooms and agents at a higher namespace level.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An agent can write a memory and retrieve it by exact key with no data loss
- **SC-002**: A memory written in one session is retrievable by key and by semantic search in a subsequent session, including after a backend restart
- **SC-003**: Two or more agents joining a session reach a consensus outcome delivered to all participants, without any direct agent-to-agent message exchange
- **SC-004**: An agent running `mycelium catchup` in a room with prior activity receives a coherent summary that accurately reflects accumulated decisions and context
- **SC-005**: Room contents committed to git and checked out on a second machine are immediately accessible to agents on that machine without any additional sync step beyond `git pull`
- **SC-006**: All agent interactions with mycelium are traceable via audit events stored in the backend
