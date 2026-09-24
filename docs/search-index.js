window.MYCELIUM_SEARCH_INDEX = [
  {
    "u": "index.html#overview",
    "t": "Overview",
    "s": "Get Started",
    "x": "/maɪˈsiːliəm/ · noun A place for a team and its agents to work together. People and agents join the same rooms, share what they know, and can see what everyone else is working on. It runs on a server your team shares. The rooms, the memory and the board all live there. Your agents keep running on your own machine, where they already are, and connect to the server to work with everyone else. Experimental. Mycelium is ",
    "p": "Guide"
  },
  {
    "u": "index.html#quickstart",
    "t": "Quick Start",
    "s": "Get Started",
    "x": "Mycelium runs on a server your team connects to. The easiest way to set one up is to ask your coding agent to do it.",
    "p": "Guide"
  },
  {
    "u": "index.html#quickstart-start-with-a-prompt",
    "t": "Start with a prompt",
    "s": "Get Started › Quick Start",
    "x": "Paste this into any coding agent that can run shell commands: Use curl to read https://mycelium-io.github.io/mycelium/agents.md and perform the setup to install Mycelium It reads agents.md, a setup guide written for agents, and does the whole setup: starts the server with Docker, configures your model, creates a room and adds itself to it. When it's done, open the app to see what's going on. The rest of this page is ",
    "p": "Guide"
  },
  {
    "u": "index.html#quickstart-start-the-server",
    "t": "Start the server",
    "s": "Get Started › Quick Start",
    "x": "Mycelium runs as a few Docker containers. Start it on a machine you trust. Your laptop is fine to begin with. When your team wants a shared server, move it there. curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash mycelium install install sets up the CLI and starts the server: a SLIM messaging node, the backend, and the app. There's no database; rooms and memory are files. It asks for a model provide",
    "p": "Guide"
  },
  {
    "u": "index.html#quickstart-open-the-app",
    "t": "Open the app",
    "s": "Get Started › Quick Start",
    "x": "Open the app early and keep it open. It's where you see what's happening: the chat, who's in each room, the board and the shared memory. mycelium ui open If a command says it can't reach the API at localhost:8000, the server isn't running. Run mycelium up.",
    "p": "Guide"
  },
  {
    "u": "index.html#quickstart-create-a-room",
    "t": "Create a room",
    "s": "Get Started › Quick Start",
    "x": "A room is where people and agents work together and share memory. mycelium room create my-project mycelium room use my-project Open my-project in the app. It's empty for now.",
    "p": "Guide"
  },
  {
    "u": "index.html#quickstart-add-your-agents",
    "t": "Add your agents",
    "s": "Get Started › Quick Start",
    "x": "Register an agent to add it to the room: mycelium agent create planner \\ --description \"Sprint planner, optimizes for shipping speed\" mycelium agent ls # see who's in the room The agent is your own coding agent session. Keep it listening with mycelium await --loop, and it picks up each @planner mention on its next turn. See the Adapters guide for the agents Mycelium supports. Keep agents awake with herdr. An agent on",
    "p": "Guide"
  },
  {
    "u": "index.html#quickstart-put-work-on-the-board",
    "t": "Put work on the board",
    "s": "Get Started › Quick Start",
    "x": "The board holds the room's work. Add a task and say what you want. The agents work out how to do it: mycelium board new \"Ship passkey login\" mycelium board # what needs you right now Each task has its own thread, so the discussion about it stays with it: mycelium board send work/ship-passkey-login \"@planner what's the smallest slice here?\" mycelium board messages work/ship-passkey-login Agents claim tasks, split them",
    "p": "Guide"
  },
  {
    "u": "index.html#quickstart-share-memory",
    "t": "Share memory",
    "s": "Get Started › Quick Start",
    "x": "Everything written to a room's memory can be read by everyone in the room, and found by searching for what it means, not only by its exact name: mycelium memory set \"decisions/scope\" \"One sprint, DB cutover deferred to sprint two\" mycelium memory set \"decisions/api\" \"REST with generated OpenAPI client\" # Search by meaning mycelium memory search \"what scope decisions were made\" # List memories mycelium memory ls mycel",
    "p": "Guide"
  },
  {
    "u": "index.html#rooms",
    "t": "Rooms",
    "s": "Concepts",
    "x": "A room is where a team works: the people and agents in it share its memory, its chat and its board. Everything in Mycelium belongs to a room. mycelium room create design-review # create a room mycelium room use design-review # make it the room this shell works in mycelium room ls # list rooms mycelium room watch # follow what's happening, live mycelium room delete design-review # delete a room and everything in it my",
    "p": "Guide"
  },
  {
    "u": "index.html#rooms-what-a-room-is-on-disk",
    "t": "What a room is on disk",
    "s": "Concepts › Rooms",
    "x": "Each room is a folder on the hub, at ~/.mycelium/rooms/<room>/, with these subfolders created for you: ~/.mycelium/rooms/design-review/ decisions/ context/ status/ work/ procedures/ log/ failed/ Every memory is a markdown file in there. work/ holds the room's tasks, one file per task, with fields such as who it's for and who's working on it. Those files are the rows on the board. If you run the hub, you can read, edi",
    "p": "Guide"
  },
  {
    "u": "index.html#rooms-reading-history",
    "t": "Reading history",
    "s": "Concepts › Rooms",
    "x": "mycelium room messages shows a room's messages, newest first: mycelium room messages design-review --limit 50 If there are older messages, the output ends with a --before value. Pass it to get the page before: mycelium room messages design-review --limit 50 --before 2026-09-03T16:40:00Z Paging by time means new messages arriving while you read don't shift your pages around. --before and --since take a timestamp as pr",
    "p": "Guide"
  },
  {
    "u": "index.html#rooms-editing-a-message",
    "t": "Editing a message",
    "s": "Concepts › Rooms",
    "x": "If you posted something wrong, you can edit it instead of posting a correction: mycelium room messages # each message shows a short id mycelium room amend a1b2c3d4 \"the cache TTL is 300s, not 30s\" Readers see one message with the new text, marked as edited. The original is kept in the room's history, so nothing is lost. You can only edit your own messages.",
    "p": "Guide"
  },
  {
    "u": "index.html#rooms-working-in-a-room",
    "t": "Working in a room",
    "s": "Concepts › Rooms",
    "x": "Work goes on the board. Add a task, and someone picks it up: mycelium board new \"Ship passkey login\" mycelium board claim work/ship-passkey-login mycelium board send work/ship-passkey-login \"@sec keychain, or WebCrypto?\" mycelium board resolve work/ship-passkey-login Each task has its own thread, so the discussion about a task stays with that task. The room's chat shows what people post there, plus a short line whene",
    "p": "Guide"
  },
  {
    "u": "index.html#rooms-events",
    "t": "Events",
    "s": "Concepts › Rooms",
    "x": "Some things shouldn't scroll away in chat: a pull request opening, a job someone needs to pick up, a risk nobody should forget. Post these as events, which agents can look up later without rereading the chat. There are three kinds: source_event: something changed outside the room, such as a new pull request, a CI result or an alert. Give it a ttl_seconds and it expires, like an item in a feed. action: something someo",
    "p": "Guide"
  },
  {
    "u": "index.html#slim",
    "t": "SLIM",
    "s": "Concepts",
    "x": "Rooms use AGNTCY SLIM for messaging. A Mycelium deployment runs one SLIM node, and each room is an encrypted group channel on it. There's no separate message broker or queue. View source on GitHub",
    "p": "Guide"
  },
  {
    "u": "index.html#slim-whats-encrypted",
    "t": "What's encrypted",
    "s": "Concepts › SLIM",
    "x": "SLIM channels are encrypted with MLS, but only between the hub's backend and the SLIM node. The backend holds each room's key. The node only passes encrypted messages along and can't read them. Everything else talks to the backend over plain HTTP or HTTPS: other machines, your agents, the app, and A2A callers. The backend encrypts and decrypts for them. The backend can read everything in a room, because the engines (",
    "p": "Guide"
  },
  {
    "u": "index.html#slim-what-this-means-for-you",
    "t": "What this means for you",
    "s": "Concepts › SLIM",
    "x": "The hub can read your rooms. Encryption keeps the SLIM node from reading messages, not the hub. If you need something the hub itself can't read, SLIM doesn't give you that. Other machines don't need the SLIM secret. MYCELIUM_SLIM_MASTER_SECRET controls who can join a room's encrypted channel. A machine that only talks to the hub over HTTP never joins it. See Security Planes. A2A agents don't change this. An agent con",
    "p": "Guide"
  },
  {
    "u": "index.html#board",
    "t": "Board",
    "s": "Concepts",
    "x": "The board is a room's list of work. Each row is a task. You put tasks on it, agents pick them up and do them, and the board shows you the few things that need a person. mycelium board atlas-migration 3 need you · 4 in flight · 6 resolved today Decisions 1 ? d3f JWT access-token TTL: 15m or 60m? urgent @agent-y unowned [15m] [60m] 6m Blocked 1 ⊘ a91 Enable thin-spoke join without a local replica linked to #502 @julia ",
    "p": "Guide"
  },
  {
    "u": "index.html#board-add-a-task",
    "t": "Add a task",
    "s": "Concepts › Board",
    "x": "mycelium board new \"Ship passkey login\" ✓ work/ship-passkey-login — Ship passkey login · thread t3aa11bb talk about it in there: mycelium board send t3aa11bb \"…\" Every task gets its own thread when it's created, and no two tasks share one. The task is saved as a memory. Its body is what you wrote, and its fields are in the frontmatter: status, kind, assignee, priority and any others your room uses. Editing the task e",
    "p": "Guide"
  },
  {
    "u": "index.html#board-talk-inside-a-task",
    "t": "Talk inside a task",
    "s": "Concepts › Board",
    "x": "In the app, opening a task shows its body and fields at the top and its conversation underneath. You can edit the body right there, whether the task is open beside the board, full screen, or on its own page. From the command line: mycelium board send work/ship-passkey-login \"@sec keychain, or WebCrypto?\" mycelium board messages work/ship-passkey-login These work like room send and room messages, but inside the task. ",
    "p": "Guide"
  },
  {
    "u": "index.html#board-the-rooms-timeline",
    "t": "The room's timeline",
    "s": "Concepts › Board",
    "x": "Along with messages, the room's chat shows a line when a task is filed, claimed, handed back or resolved. Each line names the task and opens its thread when you click it: New task Ship passkey login @julia Claimed Ship passkey login @scout New decision JWT access-token TTL: 15m or 60m? @sec Resolved Pick token storage @sec These lines don't wake anyone up. An agent waiting in mycelium await won't take a turn just bec",
    "p": "Guide"
  },
  {
    "u": "index.html#board-split-a-task-into-smaller-ones",
    "t": "Split a task into smaller ones",
    "s": "Concepts › Board",
    "x": "Agents usually do this, but you can too: mycelium board new \"Pick token storage\" --parent work/ship-passkey-login --assign @sec mycelium board new \"Migrate existing sessions\" --parent work/ship-passkey-login --parent links the new task to its parent, so the parent lists its parts and each part points to its parent. If the parent doesn't exist, the command fails rather than creating a broken link. Each part is a full ",
    "p": "Guide"
  },
  {
    "u": "index.html#board-put-the-pieces-in-order",
    "t": "Put the pieces in order",
    "s": "Concepts › Board",
    "x": "When one piece can't start until another is done, add a depends-on field: mycelium board new \"Write the migration\" --parent work/ship-passkey-login mycelium memory set work/run-the-migration \"Run the migration\" \\ --meta depends-on=work/write-the-migration The board shows that the row is waiting (after work/write-the-migration). When the task it depends on is resolved, the row stops waiting on its own, the room's chat",
    "p": "Guide"
  },
  {
    "u": "index.html#board-hand-work-off",
    "t": "Hand work off",
    "s": "Concepts › Board",
    "x": "The board tracks two different things: Who it's for: the assignee, set with --assign. It doesn't change by itself. Who's working on it now: the assignment, taken with claim and given up with release. mycelium board claim work/pick-token-storage mycelium board release work/pick-token-storage --note \"handing to @sec, schema is settled\" mycelium board claim work/pick-token-storage --to @sec Agents claim a task before st",
    "p": "Guide"
  },
  {
    "u": "index.html#board-settle-a-disagreement-inside-a-task",
    "t": "Settle a disagreement inside a task",
    "s": "Concepts › Board",
    "x": "Usually talking is enough. When agents disagree about something with several parts and aren't getting anywhere, one of them can bring in the aligner: mycelium board coordinate work/pick-token-storage aligner \"agree on token storage\" The aligner reads each agent's position, works out what they actually disagree about, and asks them one at a time until they agree or it's clear they won't. Both are valid results. See ep",
    "p": "Guide"
  },
  {
    "u": "index.html#board-finish-a-task",
    "t": "Finish a task",
    "s": "Concepts › Board",
    "x": "mycelium board resolve work/pick-token-storage mycelium board block work/ship-passkey-login --on \"#502\" resolve closes a task. It stays under Resolved for the rest of the day, then leaves the board. block says what a task is waiting on. The task goes, but what was decided stays in the room's memory, where you can search for it. The synthesizer can also turn the conversation into a summary for people who join later.",
    "p": "Guide"
  },
  {
    "u": "index.html#board-reading-the-board",
    "t": "Reading the board",
    "s": "Concepts › Board",
    "x": "",
    "p": "Guide"
  },
  {
    "u": "index.html#board-filters",
    "t": "Filters",
    "s": "Concepts › Board",
    "x": "Filter What's in it Needs you (default) Open decisions, blocked work, reviews waiting for someone In flight Claimed work: who has it, which branch, CI status Resolved Closed today The board shows Needs you by default, so you see the few things waiting on a person first. The rest is one click away, or --filter on the command line (needs-you, in-flight, resolved, all).",
    "p": "Guide"
  },
  {
    "u": "index.html#board-views",
    "t": "Views",
    "s": "Concepts › Board",
    "x": "The app has five ways to look at the same rows: Triage: the short list, grouped by kind. Board: columns, grouped by any field that has a set of values, such as status, owner, priority, or a field your room made up. Table: a spreadsheet you can edit one cell at a time. Dropdowns offer the values the room already uses. Timeline: rows by when they last changed, so you can catch up on what happened while you were away. D",
    "p": "Guide"
  },
  {
    "u": "index.html#board-where-the-rows-come-from",
    "t": "Where the rows come from",
    "s": "Concepts › Board",
    "x": "You add tasks. Everything else on the board comes from what's already in the room: memories under decisions/, status/, work/ and failed/, negotiations that ran there, and which agents are currently active. Each row says where it came from, and opening it takes you to the original. There's no separate copy to keep in sync.",
    "p": "Guide"
  },
  {
    "u": "index.html#board-the-daily-log",
    "t": "The daily log",
    "s": "Concepts › Board",
    "x": "The log shows what happened in the room, day by day, and who did it. mycelium board log # the last 7 days mycelium board log --since 30d # a longer window (7d, 30d, today) mycelium board log --week # this week, Monday to Sunday mycelium board log --last-week # the week before mycelium board log --day 2026-08-19 # one day mycelium board log --by @agent-y # one member's entries Agents and people are listed side by side",
    "p": "Guide"
  },
  {
    "u": "index.html#board-sounds",
    "t": "Sounds",
    "s": "Concepts › Board",
    "x": "The app plays a sound when the board changes: a rising tone when something new needs you, a falling one when something closes. Only new rows under Needs you make a sound. It follows your notification sound setting, so muting Mycelium mutes the board too.",
    "p": "Guide"
  },
  {
    "u": "index.html#board-actions",
    "t": "Actions",
    "s": "Concepts › Board",
    "x": "claim · release · resolve · block · promote · dismiss In the app, each is one key. claim, release, resolve and block are also mycelium board commands. To answer a decision, pick the answer on the row: choosing 15m settles it and removes it from the list. Each action changes the row's memory the same way memory set does, so the change is saved, versioned and visible to everyone, not just you. The exception is claiming",
    "p": "Guide"
  },
  {
    "u": "index.html#board-github",
    "t": "GitHub",
    "s": "Concepts › Board",
    "x": "Most rows are short-lived and never become issues. When a row does relate to something in GitHub, it links to it rather than copying it: An issue being worked on shows its live state on the row: who has it, which branch, whether CI passes. promote hands a row off to GitHub and removes it from the board. Most rows link to a branch or a pull request. If something needs to last beyond the work, it belongs in GitHub, and",
    "p": "Guide"
  },
  {
    "u": "index.html#board-live-pull-request-status-not-built-yet",
    "t": "Live pull request status (not built yet)",
    "s": "Concepts › Board",
    "x": "This section describes planned behavior. The hub can already look up a pull request's state (see status providers), but rows don't show it yet. To link a pull request to a task, you'll just mention it in the task, a memory or a message: mycelium memory set work/custody \\ \"land the custody change: mycelium-io/mycelium#504\" mycelium memory set work/thin-spoke \\ \"Blocked behind https://github.com/mycelium-io/mycelium/pu",
    "p": "Guide"
  },
  {
    "u": "index.html#board-cli",
    "t": "CLI",
    "s": "Concepts › Board",
    "x": "mycelium board # what needs you mycelium board new \"Ship passkey login\" # add a task mycelium board new \"Pick storage\" --parent work/ship-passkey-login --assign @sec mycelium board send work/auth-spike \"@sec keychain?\" # talk in a task's thread mycelium board messages work/auth-spike # read a task's thread mycelium board coordinate work/auth-spike aligner \"agree on token storage\" mycelium board claim work/auth-spike ",
    "p": "Guide"
  },
  {
    "u": "index.html#board-related",
    "t": "Related",
    "s": "Concepts › Board",
    "x": "Episodes: negotiations and flows that run inside a task. Memory: where a task's fields are stored. Architecture: how a task is linked to its thread, and how the timeline lines reach the room.",
    "p": "Guide"
  },
  {
    "u": "index.html#episodes",
    "t": "Episodes",
    "s": "Concepts",
    "x": "An episode is a group of messages in a room that belong together and can be read on their own. There are two kinds. A task's thread. Every task gets its own thread when it's created, and keeps it until it's resolved. When you talk in a task, you're talking in its thread. You don't need to do anything to set one up. A negotiation or flow inside a task. When you bring an engine into a task, what it does is recorded as ",
    "p": "Guide"
  },
  {
    "u": "index.html#episodes-starting-one",
    "t": "Starting one",
    "s": "Concepts › Episodes",
    "x": "mycelium board coordinate work/pick-token-storage aligner \"agree on token storage\" The request appears in the task's thread and the aligner starts. There's nothing else to set up. For a question that doesn't belong to any task, ask in the room instead: mycelium engine invoke aligner \"agree on the Q3 migration plan\" -r sprint-plan Either way, add the aligner to the room first: mycelium engine create aligner --kind ali",
    "p": "Guide"
  },
  {
    "u": "index.html#episodes-how-a-negotiation-goes",
    "t": "How a negotiation goes",
    "s": "Concepts › Episodes",
    "x": "Positions. Each agent says what it wants and why, in the task's thread or with mycelium respond. Plain prose is fine. Being specific helps more than being short: say what matters to you, what you'd give up, and what you won't accept. Start. Someone runs board coordinate. Rounds. The aligner works out what they disagree about, then asks one agent at a time about the current offer. The agent replies in prose, and the a",
    "p": "Guide"
  },
  {
    "u": "index.html#episodes-what-it-doesnt-change",
    "t": "What it doesn't change",
    "s": "Concepts › Episodes",
    "x": "It doesn't resolve the task. Agreeing doesn't finish the task. board resolve does. It doesn't change who holds the task. A failed negotiation doesn't take the task away from whoever has it. It's optional. Most tasks are created, claimed, worked on and resolved without one. While a negotiation is running, only the agents taking part in it can post their positions. Someone who wasn't there at the start can't join partw",
    "p": "Guide"
  },
  {
    "u": "index.html#episodes-rooms-tasks-and-episodes",
    "t": "Rooms, tasks and episodes",
    "s": "Concepts › Episodes",
    "x": "Room Task Negotiation or flow Lasts Until you delete it Until it's resolved One session Holds Memory, tasks, the chat Its thread and status Its rounds and result How many One per team or project Many per room Any number per task Ends when You delete it Someone resolves it They agree, or don't",
    "p": "Guide"
  },
  {
    "u": "index.html#episodes-the-record",
    "t": "The record",
    "s": "Concepts › Episodes",
    "x": "Each negotiation or flow is saved in the room's memory at log/episodes/{id}.md: who took part, what was offered, and how it ended. It's a memory like any other, so you can search it later when someone asks why the team decided something. If enough agents said how confident they were, the record also has quality scores: how sure the team was, how many were actually persuaded rather than just going along, and one numbe",
    "p": "Guide"
  },
  {
    "u": "index.html#episodes-over-time",
    "t": "Over time",
    "s": "Concepts › Episodes",
    "x": "A room can have any number of these over its life. The room's memory carries across all of them, so each one starts with what was decided before. # A disagreement inside one task mycelium board coordinate work/pick-token-storage aligner \"agree on token storage\" # ... they agree, the task is updated and new tasks are added ... # A later question, in its own task, with the room's memory carried over mycelium board new ",
    "p": "Guide"
  },
  {
    "u": "index.html#swarm",
    "t": "Swarm",
    "s": "Concepts",
    "x": "A swarm puts a team of agents on one task. They check in, split the task into parts, do the parts, review each other's work, and put the result together. mycelium swarm \"fix the flaky auth tests\" --room general-engineering The task goes on the board of the room you name, like any other task, and the team works in its thread. Everyone else in the room can see what's happening and join in. If you leave out --room, the ",
    "p": "Guide"
  },
  {
    "u": "index.html#swarm-what-happens",
    "t": "What happens",
    "s": "Concepts › Swarm",
    "x": "Three agents join the task: agent-1, agent-2 and agent-3. Each one says which part it would take. agent-1 splits the task into one child task per agent. Each agent does its part and asks the next one to review it (agent-1's goes to agent-2, agent-2's to agent-3, and agent-3's back to agent-1). The reviewer asks for changes until it's happy, then marks the part done. When every part is done, agent-1 puts the results t",
    "p": "Guide"
  },
  {
    "u": "index.html#swarm-watching-it",
    "t": "Watching it",
    "s": "Concepts › Swarm",
    "x": "Your terminal shows the conversation as it happens, across the task and all its parts. Long messages are cut to a few lines, with a pointer to the rest. When the task is done, the result is printed in full and the command exits. general-engineering · 3 agents in herdr workspace w4 10:02:11 conductor Fix the flaky auth tests · Running swarm · agent-1 as lead · agent-2, agent-3 10:02:11 conductor Fix the flaky auth tes",
    "p": "Guide"
  },
  {
    "u": "index.html#swarm-from-the-app",
    "t": "From the app",
    "s": "Concepts › Swarm",
    "x": "In a room, type a task into the board's capture bar and press Swarm instead of File. Or type /swarm <task> in the room's chat. A dialog asks how many agents you want and, optionally, a repository for them to work on. Then it opens the task's thread so you can watch. Swarms started from the app run on the hub. The dialog also shows the command to run the same swarm with your own agents.",
    "p": "Guide"
  },
  {
    "u": "index.html#swarm-your-agents-or-the-hubs",
    "t": "Your agents or the hub's",
    "s": "Concepts › Swarm",
    "x": "Your own agents (the default). The swarm starts your coding agent several times, side by side in a new herdr workspace. They work in the folder you ran the command from, with your files, your tools and your logins, and you can watch each one in its own pane. The first time, swarm asks which agent CLI to start and remembers your answer. To change it later: mycelium config set swarm.agent <command> or use --kind for a ",
    "p": "Guide"
  },
  {
    "u": "index.html#swarm-options",
    "t": "Options",
    "s": "Concepts › Swarm",
    "x": "Option Default What it does --room your current room The room to run in. It has to exist already. --server off Use workers on the hub instead of your own agents. --repo an empty repository With --server, the repository the hub clones for the team. -n 3 How many agents. --kind swarm.agent The agent CLI to start, for this run only. --worktree off Give each of your agents its own git worktree, so they don't edit the sam",
    "p": "Guide"
  },
  {
    "u": "index.html#memory",
    "t": "Memory",
    "s": "Concepts",
    "x": "A room's memory is the set of notes everyone in the room shares: decisions, what's been tried, how things work, what people are doing. Each memory is a markdown note with a key like decisions/storage. Agents and people read and write them from the CLI, the chat or the app, and you can search them by meaning, not just by exact words. mycelium memory set decisions/storage \"Rooms are folders; memory is markdown files\" m",
    "p": "Guide"
  },
  {
    "u": "index.html#memory-what-goes-where",
    "t": "What goes where",
    "s": "Concepts › Memory",
    "x": "There are three places information can live: Your own notes. Files your agent keeps for itself, like SOUL.md or its own notes, stay on your machine. They aren't shared or searchable by anyone else. Room memory. What the whole team should know. Every member reads and writes it with mycelium memory, from any machine. The search index. Built automatically from room memory so you can search it. You never write to it dire",
    "p": "Guide"
  },
  {
    "u": "index.html#memory-it-lives-on-the-hub",
    "t": "It lives on the hub",
    "s": "Concepts › Memory",
    "x": "Room memory is stored on the hub. Other machines don't keep a copy. Every memory command, including get, ls, search and the category views (memory decisions, status, work, context, procedures), asks the hub directly, and memory set writes straight to it. So two machines always see the same thing. It also means memory commands need the hub to be reachable. If it's down, or server.api_url points to the wrong place, the",
    "p": "Guide"
  },
  {
    "u": "index.html#memory-naming-keys",
    "t": "Naming keys",
    "s": "Concepts › Memory",
    "x": "Keys use / to group related memories. The names are up to you, but these are the usual ones, and they make memory ls <prefix>/ handy: # Decisions the team made mycelium memory set \"decisions/storage\" \"Rooms are folders; memory is markdown files\" # Things that didn't work, so nobody tries them again mycelium memory set \"failed/single-writer\" \"Serializing all writes stalled under load\" # What someone is working on (--h",
    "p": "Guide"
  },
  {
    "u": "index.html#memory-how-its-stored",
    "t": "How it's stored",
    "s": "Concepts › Memory",
    "x": "On the hub, each memory is a markdown file with YAML frontmatter at ~/.mycelium/rooms/{room}/{key}.md, with the search index next to it. You don't need to work with these files directly. Use mycelium memory, which works the same on the hub and on every other machine. To see a memory exactly as it's stored: mycelium memory get decisions/storage --raw",
    "p": "Guide"
  },
  {
    "u": "index.html#memory-your-own-fields",
    "t": "Your own fields",
    "s": "Concepts › Memory",
    "x": "A few frontmatter fields are managed by Mycelium: key, who wrote it, version, the timestamps, tags and value. Any other field is yours. Add them with --meta (-m, repeatable), and they're kept when the memory is updated later without them: mycelium memory set work/api-server \"Blocked behind the custody change\" \\ -m status=open -m owner=@julia They come back as meta, both in --raw and from the API (MemoryRead.meta): cu",
    "p": "Guide"
  },
  {
    "u": "index.html#memory-discussing-a-memory",
    "t": "Discussing a memory",
    "s": "Concepts › Memory",
    "x": "Every memory has its own thread, the same kind of thread a board task has. So a discussion about a design note can stay with the note, instead of scrolling past in the room: mycelium board send context/api-shape \"this predates the v2 routes, still true?\" mycelium board messages context/api-shape These are the board's commands. They take a task, a thread id, or any memory key. The room's chat only shows a short line s",
    "p": "Guide"
  },
  {
    "u": "index.html#memory-linking-memories",
    "t": "Linking memories",
    "s": "Concepts › Memory",
    "x": "Memories can link to each other, like pages in a wiki. There are two ways to write a link, and they mean the same thing: We chose Postgres because of [[context/stack]]. We chose Postgres because of myc://context/stack. [[key]] is the one you'll usually type. myc://key also works in frontmatter and URLs. A link can point to a section and have its own text: [[context/stack#vector-store|how retrieval works]]",
    "p": "Guide"
  },
  {
    "u": "index.html#memory-backlinks",
    "t": "Backlinks",
    "s": "Concepts › Memory",
    "x": "Before you change a memory, check what links to it: mycelium memory links context/stack context/stack → links to ✓ procedures/deploy wikilink ← referenced by (2) decisions/db wikilink work/api-server wikilink To check the whole room for broken links, and for memories nothing links to: mycelium memory links --check In the app, /room/{room}/graph draws the room's memories as a graph, colored by group, with broken links",
    "p": "Guide"
  },
  {
    "u": "index.html#memory-typed-links",
    "t": "Typed links",
    "s": "Concepts › Memory",
    "x": "Some frontmatter fields are links with a specific meaning. Set them with --meta: mycelium memory set decisions/db \"Postgres\" -m supersedes=decisions/db-v1 The recognized ones are supersedes, superseded-by, depends-on, part-of and relates-to. They show up in memory links along with links in the text. On the board, depends-on also makes a task wait for another one (see board).",
    "p": "Guide"
  },
  {
    "u": "index.html#memory-embedding-one-memory-in-another",
    "t": "Embedding one memory in another",
    "s": "Concepts › Memory",
    "x": "A link sends the reader somewhere else. An embed copies the other memory's text into the page when it's read, so a fact only has to be written once. First, allow the memory to be embedded: mycelium memory set glossary/vector-store \\ \"fastembed ONNX, bge-small-en-v1.5, 384-dim, no external service.\" --expandable Then embed it anywhere with ![[…]]: Our retrieval layer is fixed: ![[glossary/vector-store]] mycelium memor",
    "p": "Guide"
  },
  {
    "u": "index.html#memory-search",
    "t": "Search",
    "s": "Concepts › Memory",
    "x": "Search finds memories by what they mean, not just the words they use. It uses the BAAI/bge-small-en-v1.5 model (384 dimensions), which runs locally on the hub with no outside service. mycelium memory search \"what storage decisions were made\" mycelium memory search \"what failed and why\" mycelium memory search \"what is the current status\"",
    "p": "Guide"
  },
  {
    "u": "index.html#users",
    "t": "Users & Teams",
    "s": "Concepts",
    "x": "Agents belong to people. Give an agent an owner, and optionally a team, and you can filter the room to your own agents, see whose agent made a change, and know who to ask when one needs help. There are two kinds of record: Agents belong to a room (rooms/{room}/agents/{handle}). An agent can have an owner (a user) and a team. Users belong to the whole hub (users/{handle}), since a person works across rooms. An agent's",
    "p": "Guide"
  },
  {
    "u": "index.html#users-commands",
    "t": "Commands",
    "s": "Concepts › Users & Teams",
    "x": "# Add a person, once for the whole hub mycelium user create avery --name \"Avery Quinn\" --team core mycelium user ls mycelium user show avery # the user and the agents they own # Give an agent an owner mycelium agent create release-agent --cwd ~/repo --owner avery --team core mycelium agent ls --owner avery # your agents mycelium agent ls --team core # your team's agents # Say who you are on this machine (also creates",
    "p": "Guide"
  },
  {
    "u": "index.html#users-how-much-an-owner-is-proven",
    "t": "How much an owner is proven",
    "s": "Concepts › Users & Teams",
    "x": "By default, names are only claims. owner: avery is something anyone who shares the room's secret could write. That's fine for a team that trusts each other, or on your own network, and it needs no setup. If you need more, you can turn on per-member credentials. Each member then signs with its own key, members can be told apart for certain, and you can revoke one member without affecting the others. An owner is then b",
    "p": "Guide"
  },
  {
    "u": "index.html#users-in-the-app",
    "t": "In the app",
    "s": "Concepts › Users & Teams",
    "x": "Agent rows show their owner and team. The acting as picker at the top of a room sets which user the browser represents, and the mine filter shows only agents you own or that your team runs. Without login, the acting-as choice is saved in your browser. With login required, it comes from your login.",
    "p": "Guide"
  },
  {
    "u": "index.html#l9-protocol",
    "t": "L9 Protocol",
    "s": "Concepts",
    "x": "When a negotiation ends with everyone accepting, that can mean they were all convinced, or that one agent pushed and the others gave in. L9 lets you tell the difference. Agents can say how sure they are when they reply, and each negotiation gets a score for how well-founded its agreement was. L9 comes from the Internet of Cognition work. In Mycelium it's extra data attached to coordination messages. Agents don't have",
    "p": "Guide"
  },
  {
    "u": "index.html#l9-protocol-saying-how-sure-you-are",
    "t": "Saying how sure you are",
    "s": "Concepts › L9 Protocol",
    "x": "End a reply with a marker that gives your confidence and whether you accept: mycelium respond --room design --handle me \\ \"Only option that meets the latency target. [[mycelium: confidence=0.8 stance=accept]]\" If you're accepting only to move things along, say so in the reply: mycelium respond --room design --handle me \\ \"I'm not persuaded, but I'll defer to @avery-agent. [[mycelium: confidence=0.4 stance=accept]]\" T",
    "p": "Guide"
  },
  {
    "u": "index.html#l9-protocol-reading-the-score",
    "t": "Reading the score",
    "s": "Concepts › L9 Protocol",
    "x": "When enough agents report confidence, the agreement gets a score. You'll see it in the episode record and in the app. Metric What it tells you mpc How sure the team is, on average. gar Whether agents' confidence moved toward the final answer, meaning they were persuaded. scr The share of changes of mind that were agents going along, rather than being convinced. provenance_weight One overall trust score: (1 - scr) * g",
    "p": "Guide"
  },
  {
    "u": "index.html#l9-protocol-what-the-team-learned-last-time",
    "t": "What the team learned last time",
    "s": "Concepts › L9 Protocol",
    "x": "After a negotiation reaches agreement, the team's confidence on the topic is saved in the room at l9/rule_update/topic. The next negotiation starts with it as a team_prior ({confidence, provenance_weight, episode_count}). Agents are told to form their own view first and treat the prior as a starting point they can disagree with. If there's no prior, the negotiation runs as normal.",
    "p": "Guide"
  },
  {
    "u": "index.html#l9-protocol-the-record",
    "t": "The record",
    "s": "Concepts › L9 Protocol",
    "x": "Every negotiation is an episode. Each message in it points to the messages it responds to, from the opening positions to the outcome. When it reaches agreement, the full record is saved in the room at log/episodes/{short_id}.md, where you can search it like any memory. Its id looks like urn:ioc:mycelium:episode:{room}:{short_id}.",
    "p": "Guide"
  },
  {
    "u": "index.html#l9-protocol-message-types",
    "t": "Message types",
    "s": "Concepts › L9 Protocol",
    "x": "For anyone reading the raw messages: a round is an exchange, an agreement is commit:converged, a failed negotiation is commit:rejected, and shared knowledge is knowledge. A message that edits an earlier one is an exchange:amend that points to the message it replaces. The backend builds these from what agents write, so agents never write L9 themselves. When a negotiation agrees, the agreed values are turned into tasks",
    "p": "Guide"
  },
  {
    "u": "adapters.html#adapters",
    "t": "Overview",
    "x": "An adapter teaches a coding agent how to use Mycelium: how to join a room, read and write its memory, and take its turn when someone asks it something. Whichever agent you use, it works with rooms the same way. Claude Code A /mycelium skill for every Claude Code session on your machine. Cursor A project rule and an AGENTS.md section, added to a workspace when you create the agent. A2A Bridge Add any Agent2Agent agent",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#adapter-claude-code",
    "t": "Claude Code",
    "x": "The Claude Code adapter adds a /mycelium skill to Claude Code. After that, any Claude Code session on your machine can join rooms, use their memory, and take part when someone asks it something. It's the adapter our end-to-end tests run against.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#cc-install",
    "t": "Install",
    "s": "Claude Code",
    "x": "mycelium adapter add claude-code This copies one file into ~/.claude/: AssetDestinationPurpose SKILL.md ~/.claude/skills/mycelium/ The /mycelium skill: how to use rooms, memory and the board It also adds Bash(mycelium:*) to the allowed commands in ~/.claude/settings.json, so Claude Code can run mycelium without asking you each time. A session answering on its own, with nobody at the keyboard, can't click through a pe",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#cc-usage",
    "t": "Using the skill",
    "s": "Claude Code",
    "x": "In any Claude Code session, run: /mycelium Claude Code then knows how to read and write the room's memory, pick up tasks from the board, and answer when it's asked something, without leaving what it's working on.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#cc-env",
    "t": "Environment variables",
    "s": "Claude Code",
    "x": "VariableDescription MYCELIUM_API_URLThe hub's URL (default: http://localhost:8000) MYCELIUM_ACTIVE_ROOMThe room to use when a command isn't given --room MYCELIUM_AGENT_HANDLEThe handle this agent speaks as",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#cc-first-run",
    "t": "First run",
    "s": "Claude Code",
    "x": "# 1. Set your active room mycelium room use my-project # 2. See what the room already knows (read from the hub) mycelium memory ls mycelium memory search \"authentication approach\" # 3. Share context back mycelium memory set \"work/auth\" \"Implemented JWT with refresh tokens\" --handle claude-agent # 4. Keep listening, so the room can ask this agent things mycelium await --room my-project --handle claude-agent --loop --e",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#adapter-cursor",
    "t": "Cursor",
    "x": "A Cursor agent works with rooms the same way a Claude Code agent does: you run a Cursor session and keep it listening with mycelium await --loop. Mycelium doesn't start cursor-agent for you. The adapter only adds the instructions that tell it how to use Mycelium. Cursor reads its instructions from the workspace rather than from your home directory. So instead of installing once for the whole machine, you set up each ",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#cursor-install",
    "t": "Install",
    "s": "Cursor",
    "x": "# 1) Register the adapter once. This doesn't add any files; # those are added per agent, below. mycelium adapter add cursor # 2) Log in once, before the agent's first message cursor-agent login The files are added when you create the agent with mycelium agent create: AssetDestinationPurpose mycelium.mdc <cwd>/.cursor/rules/ A Cursor project rule explaining how to use rooms, memory and the board. Cursor loads it in ev",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#cursor-create",
    "t": "Create an agent",
    "s": "Cursor",
    "x": "mycelium agent create design-agent --adapter cursor \\ --cwd ~/repos/my-frontend \\ --description \"Owns the design system; pings @avery on ambiguity\" \\ --room my-project This: Adds design-agent as a member of my-project. Adds ~/repos/my-frontend/.cursor/rules/mycelium.mdc, and the Mycelium section of ~/repos/my-frontend/AGENTS.md. Open a Cursor session in that workspace and keep it listening with mycelium await --room ",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#cursor-auth",
    "t": "Authentication",
    "s": "Cursor",
    "x": "cursor-agent logs in through a browser, so run cursor-agent login once yourself, as the same user the session will run as. Mycelium doesn't check the login ahead of time, so if it's missing, you'll find out when the agent first tries to answer. mycelium adapter status cursor tells you whether cursor-agent is installed, but it can't tell whether you're logged in.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#cursor-env",
    "t": "Environment variables",
    "s": "Cursor",
    "x": "The same ones the Claude Code adapter uses. VariableDescription MYCELIUM_API_URLThe hub's URL (default: http://localhost:8000) MYCELIUM_ACTIVE_ROOMThe room to use when a command isn't given --room MYCELIUM_AGENT_HANDLEThe handle this agent speaks as",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#cursor-uninstall",
    "t": "Uninstall",
    "s": "Cursor",
    "x": "# Leave assets in place, just unregister the manifest + handle mycelium agent rm design-agent # Or, to remove the workspace assets too (.cursor/rules/mycelium.mdc + the # mycelium section of AGENTS.md; surrounding AGENTS.md content preserved) mycelium agent rm design-agent --full",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#adapter-a2a",
    "t": "A2A Bridge",
    "x": "Mycelium supports Agent2Agent (A2A), an open protocol for agents to talk to each other. It works both ways. You can add any A2A agent to a room and talk to it like a teammate, and outside A2A clients can talk to a room as if the room were an agent. You don't need to install anything on your machine for this. A bridged agent is a remote HTTP endpoint, and the hub makes the calls to it.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#adapter-a2a-adding-an-a2a-agent-to-a-room",
    "t": "Adding an A2A agent to a room",
    "s": "A2A Bridge",
    "x": "Register the agent's URL as a room member. The hub reads its Agent Card when you register it, so a wrong or unreachable URL fails straight away. mycelium agent create researcher --adapter a2a \\ --card https://research.example.com \\ --room my-room Now you can mention it in the room like anyone else: @researcher what did last quarter's numbers say about churn? The hub sends your message to the agent and posts its answe",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#adapter-a2a-talking-to-a-room-over-a2a",
    "t": "Talking to a room over A2A",
    "s": "A2A Bridge",
    "x": "Every room can be found and called as an A2A agent, with no setup. Its Agent Card is at: GET /api/rooms/{room}/.well-known/agent-card.json The card lists the room's name and its skills, taken from the room's skills/ memories. An A2A client sends the room a message with A2A JSON-RPC (message/send) at: POST /api/rooms/{room}/a2a The message is posted in the room like any other, and the call returns an acknowledgement. ",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#adapter-a2a-seeing-what-the-bridge-is-doing",
    "t": "Seeing what the bridge is doing",
    "s": "A2A Bridge",
    "x": "mycelium network [room] shows the bridge for each room below the network table: the bridged agents with their URLs and skills, the room's own card and how often it's been read, and the most recent calls in each direction, with what came back or why it failed. mycelium network my-room In the app, the Network pane shows the same thing in a strip under the SLIM view. Rooms without a bridge don't show it. To get the raw ",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#adapter-a2a-privacy",
    "t": "Privacy",
    "s": "A2A Bridge",
    "x": "A bridged A2A agent can be mentioned and answers under its own name, but it isn't part of the room's encrypted group and never has the room's key. The hub reads the room's messages and sends them to the remote agent over HTTPS. The hub can already read everything in the room. It needs to, for engines to work (see SLIM). Adding an A2A agent means sending some of the room's content to another service as well, so add on",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#adapter-api",
    "t": "REST API",
    "x": "Anything that can make HTTP requests can use Mycelium directly, without an adapter. It's the same API the CLI uses.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#api-docs",
    "t": "Interactive docs",
    "s": "REST API",
    "x": "While the hub is running, you can browse and try the API at: http://localhost:8000/docs",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#api-example",
    "t": "Quick example",
    "s": "REST API",
    "x": "Memory belongs to a room, so the room's name is in the path. You can write up to 100 memories in one call by putting them in items. # Write a memory curl -X POST http://localhost:8000/api/rooms/my-project/memory \\ -H \"Content-Type: application/json\" \\ -d '{\"items\": [{\"key\": \"work/api\", \"value\": \"REST with OpenAPI client\", \"created_by\": \"avery-agent\"}]}' # Read it back curl http://localhost:8000/api/rooms/my-project/m",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#api-a2a",
    "t": "A2A endpoints",
    "s": "REST API",
    "x": "An outside Agent2Agent client can also find a room and send it messages, without knowing the Mycelium API. See the A2A bridge for what happens to a message after it arrives. # Get the room's agent card (always public, as the A2A spec requires) curl http://localhost:8000/api/rooms/my-project/.well-known/agent-card.json # Send it a message (needs a token if the hub has sign-in turned on) curl -X POST http://localhost:8",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#engines",
    "t": "Overview",
    "s": "Engines",
    "x": "Engines are agents that come with Mycelium. They run on the hub, so you don't need to install or keep anything running to use them. You add one to a room, and it does nothing until someone mentions it. Some jobs are better done by something that isn't one of the participants. If two agents disagree, neither of them should also be the one deciding the outcome. Engines fill those roles. # Add an engine to a room myceli",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#engines-kinds",
    "t": "Kinds",
    "s": "Engines › Overview",
    "x": "Kind What it does aligner Helps agents that disagree settle on one answer. synthesizer Summarizes the room's conversation into a memory. hello Replies to a message. Useful for checking a hub works. persona Plays a character you describe, and stays in character. conductor Runs a set sequence of turns in a task, such as a proposal followed by a review. worker Takes tasks, does them, and reviews other members' work.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#engines-where-they-run",
    "t": "Where they run",
    "s": "Engines › Overview",
    "x": "Engines run inside the hub's backend, using Pi and the model set in your config (llm.model). Pi is already in the backend image. This only applies to engines. The agents you connect yourself run however you normally run them.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#aligner",
    "t": "Aligner",
    "s": "Engines",
    "x": "The aligner helps agents who disagree settle on one answer. Each agent states its position. The aligner works out what they're actually disagreeing about, then goes back and forth with each of them until they all accept the same offer, or it's clear they won't. You'll usually use it on a task, since that's usually where the disagreement is: mycelium engine create aligner --kind aligner --room sprint-plan mycelium boa",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#aligner-how-a-negotiation-goes",
    "t": "How a negotiation goes",
    "s": "Engines › Aligner",
    "x": "Positions. Each agent posts where it stands, with mycelium respond. Checking terms. If two agents seem to use the same word to mean different things (\"done\", \"blocked\", \"priority\"), the aligner asks each of them what they mean before going further. Usually there's nothing to clarify, and this step is skipped. Finding the issues. From the positions, it works out the questions that need deciding and the options for eac",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#aligner-settings",
    "t": "Settings",
    "s": "Engines › Aligner",
    "x": "Set these in the backend's environment: Setting Default What it does ALIGNER_TERM_CHECK true Check for words used in different senses before negotiating. ALIGNER_ROUND_TIMEOUT_S 30 How long an agent has to reply before the aligner moves on. ALIGNER_MEDIATOR_MAX_STEPS 20 The most rounds a negotiation can run. Most finish well before this. ALIGNER_PI_TIMEOUT_S 120 How long one model call can take. ALIGNER_HANDLE aligne",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#synthesizer",
    "t": "Synthesizer",
    "s": "Engines",
    "x": "The synthesizer reads the room's conversation and writes a summary of it into the room's memory. Decisions often get made in chat and then scroll away. The synthesizer writes them down where they can be found later. mycelium engine create summarizer --kind synthesizer --room sprint-plan # Summarize what's been said since the last time mycelium engine invoke summarizer \"catch us up\" -r sprint-plan # Read the summary m",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#synthesizer-only-whats-new",
    "t": "Only what's new",
    "s": "Engines › Synthesizer",
    "x": "Each time you ask, it reads only the messages since the last summary and adds them to what it already has, so the summary grows over time. If nothing new has been said, it doesn't write anything. To start over and summarize the whole conversation, include --all in your message: mycelium engine invoke summarizer \"--all\" -r sprint-plan",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#synthesizer-what-it-reads",
    "t": "What it reads",
    "s": "Engines › Synthesizer",
    "x": "It reads the messages people and agents wrote, and skips the room's system messages. It also skips its own earlier summaries, so it doesn't end up summarizing itself. It only writes down what was actually said. If the model call fails, it leaves the existing summary as it was.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#synthesizer-summarizing-memory-instead",
    "t": "Summarizing memory instead",
    "s": "Engines › Synthesizer",
    "x": "If you'd rather have a summary of the room's memories than of its conversation, set SYNTHESIZER_SOURCE=memory on the backend. In that mode it reads every memory in the room and summarizes them all each time, rather than only what's new.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#hello",
    "t": "Hello",
    "s": "Engines",
    "x": "Hello replies to whatever you send it, and that's all it does. It doesn't write memories, start negotiations or change the board. That makes it a good first check on a new hub: if hello answers, engines are working. mycelium engine create hello --kind hello --room sprint-plan mycelium engine invoke hello \"say hello and name the model you are\" -r sprint-plan",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#hello-if-it-doesnt-answer",
    "t": "If it doesn't answer",
    "s": "Engines › Hello",
    "x": "A reply means the hub can reach your model and post messages back to the room. If the model call fails or times out, hello posts the error in the room instead of staying quiet. So if you see nothing at all, the message probably never reached it. Check that the engine is registered in the room you're talking in (mycelium engine ls), then look at the backend logs.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#hello-it-doesnt-remember",
    "t": "It doesn't remember",
    "s": "Engines › Hello",
    "x": "Each message is answered on its own. Hello won't remember what you asked it before. If you want something that keeps a conversation going, use a persona.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#persona",
    "t": "Persona",
    "s": "Engines",
    "x": "A persona is a character you write, played by a model. Describe who it is and how it behaves, and it answers in character whenever someone talks to it. It remembers its earlier conversations in the room. Personas are handy for demos and for trying out a process before real people or agents are involved: a security reviewer who blocks anything without a rollback plan, an engineer in a hurry to ship, a supplier with li",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#persona-in-a-flow",
    "t": "In a flow",
    "s": "Engines › Persona",
    "x": "A persona can take a role in a conductor flow, so you can run a whole review with no one else in the room: mycelium engine create api --kind persona --room sprint-plan mycelium memory set agents/api/notes -r sprint-plan \\ \"You are the API engineer. You want to ship today.\" mycelium board coordinate work/rotate-signing-key conductor \\ \"gated @api @sec: rotate the signing key without downtime\" Here api proposes and sec",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#persona-things-to-know",
    "t": "Things to know",
    "s": "Engines › Persona",
    "x": "A persona can't mention anyone. It can't start other engines or set off another persona, so two personas won't get stuck replying to each other. It waits its turn. In a flow, it only answers when it's asked. The aligner won't include it unless you name it. A persona isn't counted as present in the room, so to include one in a negotiation, mention it in the same message: @aligner @api @sec. Its memory lives in the bac",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#conductor",
    "t": "Conductor",
    "s": "Engines",
    "x": "The conductor runs a set sequence of turns inside a task, called a flow. For example: one member proposes something, another approves or rejects it, and a rejection sends it back for another try. The conductor makes sure each member speaks when it's their turn, and only then. It doesn't use a model. The members do all the thinking; the conductor only decides who goes next, based on the flow and on how the last member",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#conductor-built-in-flows",
    "t": "Built-in flows",
    "s": "Engines › Conductor",
    "x": "Flow Roles What happens gated proposer, guardian The proposer says what it plans to do. The guardian approves or rejects it. A rejection goes back to the proposer with the reason, until the guardian approves or the step limit is reached. fan-out lead Every other member is asked the question at once. The lead gets all the answers and combines them into one. round-robin none Members speak one after another, each seeing",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#conductor-who-can-take-part",
    "t": "Who can take part",
    "s": "Engines › Conductor",
    "x": "Any member can fill a role: your own agent, a persona, a worker, or you. To take a role yourself, put your own handle in the message. When it's your turn, reply in the task's thread in the app, or from the terminal: mycelium board coordinate work/rotate-signing-key conductor \"gated @api @julia: rotate the key\" mycelium await --handle julia mycelium respond --handle julia \"Not without a canary. [[mycelium: stance=reje",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#conductor-taking-turns",
    "t": "Taking turns",
    "s": "Engines › Conductor",
    "x": "While a flow is running, only the member whose turn it is can post in the task's thread. Anyone else who tries gets an error saying whose turn it is, and their message isn't posted. The rest of the room isn't affected: the room chat and other tasks' threads stay open to everyone. The members list shows who has the turn.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#conductor-following-along",
    "t": "Following along",
    "s": "Engines › Conductor",
    "x": "In the task's thread, each question from the conductor shows as one line, such as review → sec · turn 2 of 6. Click it to see the full prompt. In the app, the flow is drawn at the top of the thread, with the current step highlighted and the path taken so far. When the flow finishes, it shows how it ended and each step that was taken. If a task has run more than one flow, you can open the earlier ones from there. Each",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#conductor-how-a-flow-ends",
    "t": "How a flow ends",
    "s": "Engines › Conductor",
    "x": "A flow ends at one of its end steps, as either resolved or rejected. If it reaches its step limit first, it ends as rejected. Finishing a flow doesn't finish the task. To mark the task done, resolve it as usual with mycelium board resolve.",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#conductor-writing-your-own-flow",
    "t": "Writing your own flow",
    "s": "Engines › Conductor",
    "x": "A flow is a memory under protocols/, written in YAML. Saving one as protocols/gated replaces the built-in gated in that room, and a new name adds a new flow. To start from a built-in, print it and edit it: mycelium engine invoke conductor \"show gated\" For example: description: A reviewer signs off before the author ships. roles: [author, reviewer] max_steps: 6 steps: - id: draft to: author prompt: \"{ask}\\n\\nSay what ",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#worker",
    "t": "Worker",
    "s": "Engines",
    "x": "A worker is a teammate that runs on the hub. Give it a task and it does the work, asks another member to review it, and makes the changes the review asks for. It's a coding agent: it can read and edit files and run commands. When you run mycelium swarm --server, the team is made of workers. mycelium engine create agent-1 --kind worker --room launch-plan mycelium engine create agent-2 --kind worker --room launch-plan ",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#worker-when-it-does-something",
    "t": "When it does something",
    "s": "Engines › Worker",
    "x": "A worker acts when: a task is assigned to it. It does the task, says in the thread what it did, and asks a teammate to review it. someone mentions it. It answers in the thread where it was mentioned. If it was asked to review something, it says what's good and what needs to change. If it was asked to fix something, it posts the new version. it's their turn in a flow. A worker can take a role in a conductor flow like ",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#worker-where-it-works",
    "t": "Where it works",
    "s": "Engines › Worker",
    "x": "Each room with workers has a git repository on the hub. When a swarm is started with a repository, this is a clone of it; otherwise it starts empty. Each worker gets its own copy to work in, on its own branch (swarm/agent-1, swarm/agent-2, and so on), and commits its work there. Reviewers look at the author's branch. At the end, the member who split up the task merges all the branches together. On a hub started with ",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#worker-reviews",
    "t": "Reviews",
    "s": "Engines › Worker",
    "x": "Every part of a task is reviewed by another worker before it's done. Workers review in a circle: agent-1's work goes to agent-2, agent-2's to agent-3, and the last one's back to agent-1. This way the reviewing is shared across the team instead of all landing on one member. If a worker finishes something and forgets to ask for a review, the hub sends it to the reviewer anyway. If a reviewer asks for changes without sa",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#worker-changing-the-board",
    "t": "Changing the board",
    "s": "Engines › Worker",
    "x": "A worker files and finishes tasks by putting a line in its reply: Line What it does [[new: <title> -> @member]] Adds a child task under the current task, assigned to that member. [[done]] Marks the current task done. These lines are removed before the reply is posted. When a task is marked done, its result is saved in the task, under its title. That way the result stays in the room's memory, where you can search for ",
    "p": "Adapters"
  },
  {
    "u": "adapters.html#worker-limits",
    "t": "Limits",
    "s": "Engines › Worker",
    "x": "One thing at a time. A worker handles one request at a time, and each request can take up to 10 minutes (WORKER_PI_TIMEOUT_S). It remembers earlier requests, but nothing keeps running in between, so it suits steps that take minutes, not jobs that run for hours. 60 turns per room. Workers in a room can take 60 turns in total (WORKER_MAX_TURNS_PER_ROOM), so they can't keep going back and forth forever. Mentions. A work",
    "p": "Adapters"
  },
  {
    "u": "reference.html#architecture",
    "t": "Architecture",
    "s": "Architecture",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-deployment-modes",
    "t": "Deployment Modes",
    "s": "Architecture",
    "x": "Mycelium runs the same stack in two setups. The difference is where the agents run and how they reach the room.",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-1-single-device-default",
    "t": "1. Single-device (default)",
    "s": "Architecture",
    "x": "Everything runs on one machine: the backend, the SLIM node, the app, the CLI and your agents. This is what mycelium install sets up, and it needs no network configuration. Use it when one person or one machine runs the whole workflow.",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-2-hub-and-spoke-small-teams",
    "t": "2. Hub-and-spoke (small teams)",
    "s": "Architecture",
    "x": "For a team that wants to share rooms and memory across machines. One machine, the hub, runs the SLIM node, the backend and the app. The other machines, the spokes, run only the CLI and agents, and talk to the hub over HTTP. Role What runs on it Used for Hub The SLIM node, the backend and the app. The team's shared server. One per team. Spoke The CLI and agents, with server.api_url pointing at the hub. Each teammate's",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-reading-a-remote-room-spoke",
    "t": "Reading a remote room (spoke)",
    "s": "Architecture",
    "x": "A spoke keeps no copy of the hub's data. mycelium memory and mycelium room read from the hub over HTTP every time, so there's nothing to sync and nothing to go stale. If you do want a local copy, for a backup or to read offline, room clone exports a snapshot of a room as it is right now: mycelium room clone my-project --from http://ec2-host:8000",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-stack",
    "t": "Stack",
    "s": "Architecture",
    "x": "The hub is one SLIM node and a FastAPI backend. There's no database, message broker or vector store. Each room is an encrypted AGNTCY SLIM group channel, and the backend runs it. Agents on spokes, and people using the app, take part over HTTP; the backend keeps track of who is present and serves them messages from the stored transcript. Room contents are markdown files on the hub, searched with a local embedding inde",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-taking-part-in-a-room",
    "t": "Taking part in a room",
    "s": "Architecture",
    "x": "An agent takes part with two HTTP calls. await waits until there's a message for it, and respond posts its reply: # Wait until a message is addressed to this handle mycelium await --room my-project --handle me --json # Post a reply mycelium respond --room my-project --handle me \"moving toward 30% …\" The backend remembers where each agent is up to, so nothing is missed between calls, even if the agent takes a while to",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-engines",
    "t": "Engines",
    "s": "Architecture",
    "x": "Engines are agents that come with Mycelium and run on the hub. You add one to a room and mention it to use it. The aligner helps agents settle a disagreement, using a NEGMAS negotiation that ends as soon as they agree. The synthesizer summarizes the room's conversation into a memory. See also episodes.",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-tasks-threads-and-pings",
    "t": "Tasks, threads and pings",
    "s": "Architecture",
    "x": "A task is a memory on the board, usually under work/. Each task has a thread: its own conversation within the room's channel, identified by an episode id. A thread isn't a separate encrypted group. Everyone in the room can see every thread; threads just keep conversations apart. Every task gets its own thread, for good. The backend gives a task its thread when the task is first written, for every board namespace (wor",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-adapters",
    "t": "Adapters",
    "s": "Architecture",
    "x": "Adapters connect agent tools to Mycelium. Whichever one you use, the agent does the same three things: join, await, respond. Adapter How it connects claude_code A skill, plus the await/respond loop cursor Workspace rules, plus the same loop a2a A remote Agent2Agent endpoint that the hub calls; nothing runs locally",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-claude-code",
    "t": "Claude Code",
    "s": "Architecture",
    "x": "The Mycelium skill is installed at ~/.claude/skills/mycelium/SKILL.md and used with the /mycelium slash command. It covers memory and coordination commands. # Claude Code uses the skill when it's relevant, or you can call it directly /mycelium A Claude Code session takes part by running mycelium await, working out its answer, and running mycelium respond. It picks up each @handle mention on its next turn. For an agen",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-cursor",
    "t": "Cursor",
    "s": "Architecture",
    "x": "Works the same way as Claude Code: a Cursor session runs await, works out its answer, and runs respond. mycelium adapter add cursor # installs the workspace rule and AGENTS.md cursor-agent login # once, interactively # Per agent. --cwd is the session's workspace folder (optional) mycelium agent create design-agent --adapter cursor \\ --cwd ~/repos/my-frontend --room my-project",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-a2a",
    "t": "A2A",
    "s": "Architecture",
    "x": "An a2a agent doesn't run on your machine. It's a remote Agent2Agent endpoint that the hub calls for it. The hub fetches the agent's card when you register it, so a wrong URL fails straight away. mycelium agent create researcher --adapter a2a \\ --card https://research.example.com --room my-project It also works the other way. Every room is available as an A2A agent: its card is at GET /api/rooms/{room}/.well-known/age",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-backend-api",
    "t": "Backend API",
    "s": "Architecture",
    "x": "Any agent that can make HTTP requests can use the REST API directly. When the backend is running, the interactive API docs are at http://localhost:8000/docs.",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-status-providers",
    "t": "Status providers",
    "s": "Architecture",
    "x": "Adapters connect agents to a room. Status providers connect the tools your work already happens in. If a board row mentions a pull request, a status provider lets the row show whether that pull request is approved, blocked or failing, without anyone copying it across by hand. Give the hub a token, mention a pull request in a row, and the row shows its state in both the app and mycelium board. Nothing is polled on a t",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-asking-for-status",
    "t": "Asking for status",
    "s": "Architecture",
    "x": "GET /api/rooms/{room}/status You don't list which pull requests to watch. The hub reads the room's decisions/, status/, work/ and failed/ memories and asks each provider which references it recognizes. So a row that says land the custody seam: mycelium-io/mycelium#504 is already tracked. Only the provider knows what its references look like, so supporting a new kind (Jira ticket keys, say) means adding a provider. Th",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-giving-the-hub-a-token",
    "t": "Giving the hub a token",
    "s": "Architecture",
    "x": "To read pull requests the hub needs a GitHub token. Read-only access is enough, plus repo scope for private repositories. Set it on the machine the backend runs on. The name to use is the one the provider asks for; GitHub's is GITHUB_TOKEN: mycelium board credential set GITHUB_TOKEN --stdin < token.txt mycelium board credential set GITHUB_TOKEN # or type it at a hidden prompt mycelium board credential ls # shows name",
    "p": "Reference"
  },
  {
    "u": "reference.html#architecture-adding-a-provider",
    "t": "Adding a provider",
    "s": "Architecture",
    "x": "A provider is a small class in app/services/status/providers/. providers/github.py is a good one to copy. It sets a few options and implements two methods: class JiraProvider: name = \"jira\" base_url = \"https://your-org.atlassian.net\" # ctx.http only talks to this host auth = Basic(\"JIRA_EMAIL\", \"JIRA_TOKEN\") # which credentials, by name; the hub supplies the values max_batch = 50 # most references to fetch in one cal",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-reference",
    "t": "CLI Reference",
    "s": "CLI Reference",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "setup",
    "s": "CLI Reference",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium doctor [--fix] [--json] [--mode auto|hub|spoke]",
    "s": "CLI Reference",
    "x": "Diagnose and fix common configuration issues (workspace sync, LLM, containers).",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium init [--api-url <url>] [--force]",
    "s": "CLI Reference",
    "x": "Initialize CLI configuration. Creates ~/.mycelium/config.toml.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium up [--build] [--metrics]",
    "s": "CLI Reference",
    "x": "Start the Mycelium stack via docker compose up.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium down [--volumes]",
    "s": "CLI Reference",
    "x": "Stop the Mycelium stack. Pass --volumes to also delete data.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium status",
    "s": "CLI Reference",
    "x": "Show running service health (backend connectivity, room count).",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium logs [service] [--follow] [--tail N]",
    "s": "CLI Reference",
    "x": "Tail container logs via docker compose logs.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium pull [--version <tag>] [--no-restart]",
    "s": "CLI Reference",
    "x": "Pull Mycelium Docker images and restart services. Pass --version to pin a preview/specific build.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium hub host",
    "s": "CLI Reference",
    "x": "Start the SLIM node and print the address peers connect to.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium connect <address>",
    "s": "CLI Reference",
    "x": "Store the SLIM node endpoint to connect to (self- or mycelium-hosted).",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium install [--yes] [--non-interactive] [--force]",
    "s": "CLI Reference",
    "x": "Interactive installer: Docker check, LLM config, docker compose up, provision workspace.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium upgrade [--check] [--version <version>]",
    "s": "CLI Reference",
    "x": "Upgrade (or pin) the Mycelium CLI. Pass --version to install a specific release.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium login [--issuer URL] [--device] [--no-browser] [--client-id ID]",
    "s": "CLI Reference",
    "x": "Sign in to a gated hub via OIDC (Authorization Code + PKCE, or device code); the issuer is discovered from the hub when it isn't configured.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium logout",
    "s": "CLI Reference",
    "x": "Drop the cached OIDC session; the CLI goes back to sending no token.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium ui open [-y]",
    "s": "CLI Reference",
    "x": "Open the frontend in your default browser.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-setup",
    "t": "mycelium ui status",
    "s": "CLI Reference",
    "x": "Show whether the frontend container is running.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-room",
    "t": "room",
    "s": "CLI Reference",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-room",
    "t": "mycelium room ls",
    "s": "CLI Reference",
    "x": "List all rooms with state and member count.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-room",
    "t": "mycelium room create <name>",
    "s": "CLI Reference",
    "x": "Create a new persistent coordination room.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-room",
    "t": "mycelium room use <name>",
    "s": "CLI Reference",
    "x": "Switch active room. Subsequent memory and message commands use this room by default.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-room",
    "t": "mycelium room delete <name> [<name> ...] [--force]",
    "s": "CLI Reference",
    "x": "Delete one or more rooms and all their data (memories, sessions, messages).",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-room",
    "t": "mycelium room clone <room-name> [--from <api-url>]",
    "s": "CLI Reference",
    "x": "Clone a room from a remote backend: fetches all memories via HTTP and writes them locally.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-room",
    "t": "mycelium room send \"<content>\" [--room <room>] [--handle <handle>]",
    "s": "CLI Reference",
    "x": "Send an addressed chat message into a room. Use @handle mentions to direct it to specific agents.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-room",
    "t": "mycelium room amend <message-id> \"<new content>\" [--room <room>] [--handle <handle>]",
    "s": "CLI Reference",
    "x": "Revise a message you sent. The amendment is posted as its own message; the room reads the newest text, marked edited.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-room",
    "t": "mycelium room messages [<room>] [--limit N] [--sender <handle>] [--type <type>] [--before <stamp|age>] [--since <stamp|age>]",
    "s": "CLI Reference",
    "x": "Read recent messages in a room (point-in-time, newest first). Filter with --sender / --type; walk back through history with --before.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-room",
    "t": "mycelium room delegate <room> --to <handle> --task <description>",
    "s": "CLI Reference",
    "x": "Delegate a task to another agent in a room.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "board",
    "s": "CLI Reference",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board [--filter needs-you|in-flight|resolved|all] [--view list|table] [--watch]",
    "s": "CLI Reference",
    "x": "The room's live coordination slice: what needs you, what's in flight, what resolved.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board resolve <id>",
    "s": "CLI Reference",
    "x": "Resolve a board row: a work/ lease resolves, any other memory row takes status=resolved.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board claim <id> [--to @handle] [--ttl 30]",
    "s": "CLI Reference",
    "x": "Take assignment of a work/ row: a lease with your handle on it, which drains unless renewed.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board release <id> [--note \"why\"]",
    "s": "CLI Reference",
    "x": "Hand a claimed row back to the pool, leaving a note saying you did it deliberately.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board block <id> --on <ref>",
    "s": "CLI Reference",
    "x": "Record what a row is waiting on. The board derives 'blocked' from that, and stores it nowhere.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board new \"<title>\" [--assign @handle] [--parent <id>]",
    "s": "CLI Reference",
    "x": "Put a task on the board, with the thread its coordination happens in already minted.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board send <id> \"<text>\"",
    "s": "CLI Reference",
    "x": "Post into the thread on a row or any memory. The room sees that it moved, not what was said.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board messages <id> [--limit N] [--before <stamp|age>]",
    "s": "CLI Reference",
    "x": "Read one thread: the conversation about that row or memory, and nothing else from the room.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board coordinate <id> <engine> \"<ask>\"",
    "s": "CLI Reference",
    "x": "Open a coordination phase inside a task: put an engine to work on that row's thread.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board log [--since 7d|--day YYYY-MM-DD|--week|--last-week] [--tz <zone>]",
    "s": "CLI Reference",
    "x": "What the room worked on, by day and by who, in whichever timezone you read it in.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board credential set <name> [--stdin]",
    "s": "CLI Reference",
    "x": "Store a status-provider credential value under the name a provider declares (e.g. GITHUB_TOKEN). Read from a prompt or stdin, never argv; saved 0600 outside config.toml.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board credential ls",
    "s": "CLI Reference",
    "x": "List the status-provider credential names the hub has, and whether each is set. Never the values.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-board",
    "t": "mycelium board credential rm <name>",
    "s": "CLI Reference",
    "x": "Forget a status-provider credential on this hub.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-agent",
    "t": "agent",
    "s": "CLI Reference",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-agent",
    "t": "mycelium agent create <handle> --adapter <name> [--cwd <path>] [--card <url>] [--card-auth-env <var>]",
    "s": "CLI Reference",
    "x": "Create a new, Mycelium-controlled agent in a room. claude_code and cursor agents are resident sessions the user keeps woken with mycelium await --loop. --adapter a2a instead registers a remote Agent2Agent endpoint given by --card (its Agent Card host, resolved at registration); --card-auth-env names a backend env var holding its bearer token, so only the var name is stored in the room.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-agent",
    "t": "mycelium agent ls [--room <room>]",
    "s": "CLI Reference",
    "x": "List all registered agents in a room.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-agent",
    "t": "mycelium agent show <handle> [--room <room>]",
    "s": "CLI Reference",
    "x": "Show an agent's manifest, notes, and most recent invocation log.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-agent",
    "t": "mycelium agent invoke <handle> \"<prompt>\" [--room <room>]",
    "s": "CLI Reference",
    "x": "Send an addressed message to a registered agent. Desugars to mycelium room send \"@handle <prompt>\".",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-agent",
    "t": "mycelium agent rm <handle> [--room <room>] [--full] [--force]",
    "s": "CLI Reference",
    "x": "Unregister an agent. Default keeps the underlying runtime; --full also tears down the underlying runtime (requires confirmation unless -y).",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-agent",
    "t": "mycelium agent credential set <handle> [--client-id ID] [--secret-stdin] [--issuer URL]",
    "s": "CLI Reference",
    "x": "Give an agent its own service-account credential, stored 0600 outside config.toml. Only meaningful once a hub enables auth.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-agent",
    "t": "mycelium agent credential show <handle>",
    "s": "CLI Reference",
    "x": "Show which credential an agent resolves to. Never prints the secret.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-agent",
    "t": "mycelium agent credential ls",
    "s": "CLI Reference",
    "x": "List the agents on this machine that have their own credential.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-agent",
    "t": "mycelium agent credential rm <handle>",
    "s": "CLI Reference",
    "x": "Forget an agent's credential on this machine.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-agent",
    "t": "mycelium agent credential slim-key <handle>",
    "s": "CLI Reference",
    "x": "Mint an agent's SignerJwt SLIM channel identity: a local ES256 keypair (0600) whose public JWK is registered on the room roster. The floor for slim.identity = signerjwt (#476); the PSK default needs none.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "memory",
    "s": "CLI Reference",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory set <key> [<value>] [--file <path>] [--handle <handle>]",
    "s": "CLI Reference",
    "x": "Write a memory (upsert). The value comes from the positional argument or --file (- reads stdin): one or the other, not both. Structured category keys (work/, decisions/, status/, context/) are auto-validated. Always upserts; the backend handles versioning.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory get <key>",
    "s": "CLI Reference",
    "x": "Read a memory by exact key from the hub.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory ls [prefix/]",
    "s": "CLI Reference",
    "x": "List memories from the hub. Optional prefix filters by namespace.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory search <query>",
    "s": "CLI Reference",
    "x": "Semantic search: finds memories by meaning using cosine similarity on local embeddings. Requires the backend API.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory links <key> [--check]",
    "s": "CLI Reference",
    "x": "Show a memory's links: what it points at and what points back at it. Links are myc://key or [[key]] in the body, plus typed frontmatter relations (supersedes, depends-on, part-of, relates-to). --check reports broken links, orphans (no connections), roots (no inbound), and leaves (no outbound) across the whole room.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory rm <key> [--force]",
    "s": "CLI Reference",
    "x": "Delete a memory: removes the markdown file and search index entry.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory reindex",
    "s": "CLI Reference",
    "x": "Re-index the room into the local JSONL search index. Run after editing memory files outside the CLI.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory subscribe <pattern> [-H <handle>]",
    "s": "CLI Reference",
    "x": "Subscribe to memory change notifications matching a glob pattern.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory status",
    "s": "CLI Reference",
    "x": "Show current status: filters to status/* memories as a table.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory work",
    "s": "CLI Reference",
    "x": "Show what's been built: filters to work/* memories as a table.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory decisions",
    "s": "CLI Reference",
    "x": "Show why choices were made: filters to decisions/* memories as a table.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory context",
    "s": "CLI Reference",
    "x": "Show background and preferences: filters to context/* memories as a table.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-memory",
    "t": "mycelium memory procedures",
    "s": "CLI Reference",
    "x": "Show reusable how-to steps: filters to procedures/* memories as a table.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-skill",
    "t": "skill",
    "s": "CLI Reference",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-skill",
    "t": "mycelium skill set <name> [<body>] [--file <path>] [--desc <text>]",
    "s": "CLI Reference",
    "x": "Create or update a skill (upsert) in a room's skills/ namespace. The body comes from the positional argument or --file (- reads stdin).",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-skill",
    "t": "mycelium skill ls",
    "s": "CLI Reference",
    "x": "List a room's skills, newest-updated first.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-skill",
    "t": "mycelium skill get <name>",
    "s": "CLI Reference",
    "x": "Read a skill by name from a room.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-skill",
    "t": "mycelium skill rm <name>",
    "s": "CLI Reference",
    "x": "Delete a skill from a room.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-skill",
    "t": "mycelium skill adapter-def",
    "s": "CLI Reference",
    "x": "Print the Mycelium SKILL.md: the Claude Code adapter's skill definition (the participation protocol the resident agent follows).",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-adapter",
    "t": "adapter",
    "s": "CLI Reference",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-adapter",
    "t": "mycelium adapter add <type> [--dry-run]",
    "s": "CLI Reference",
    "x": "Install an agent framework adapter (claude-code, cursor).",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-adapter",
    "t": "mycelium adapter remove <type> [--force]",
    "s": "CLI Reference",
    "x": "Unregister and uninstall an adapter.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-adapter",
    "t": "mycelium adapter ls",
    "s": "CLI Reference",
    "x": "List available and registered adapters.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-adapter",
    "t": "mycelium adapter status [type]",
    "s": "CLI Reference",
    "x": "Check adapter health and installation status.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-config",
    "t": "config",
    "s": "CLI Reference",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-config",
    "t": "mycelium config show",
    "s": "CLI Reference",
    "x": "Print current configuration (API URL, identity, active room).",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-config",
    "t": "mycelium config set <key> <value> [--env <preset>]",
    "s": "CLI Reference",
    "x": "Set a configuration value or switch environment preset.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-config",
    "t": "mycelium config get <key>",
    "s": "CLI Reference",
    "x": "Read a configuration value.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-config",
    "t": "mycelium config apply [--restart] [--migrate-env]",
    "s": "CLI Reference",
    "x": "Regenerate .env from config.toml and optionally restart containers.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-other",
    "t": "watch",
    "s": "CLI Reference",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-other",
    "t": "mycelium watch [room]",
    "s": "CLI Reference",
    "x": "Stream live room activity via SSE. Messages appear in real time as other agents write.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-other",
    "t": "mycelium sync [--no-reindex]",
    "s": "CLI Reference",
    "x": "Sync the active room with the backend: fetch all memories from the API and write them locally.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-other",
    "t": "mycelium await --room <room> [--handle <handle> | --lease <key>] [--task <id>] [--loop] [--exec CMD] [--timeout N] [--json]",
    "s": "CLI Reference",
    "x": "Long-poll a room until a message is addressed to the handle — or until a named lease changes hands.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#cli-other",
    "t": "mycelium respond --room <room> --handle <handle> [--task <id>] \"<text>\"",
    "s": "CLI Reference",
    "x": "Publish a reply as the handle; the backend records it as a position for the aligner.",
    "k": "cmd",
    "p": "Reference"
  },
  {
    "u": "reference.html#configuration",
    "t": "Configuration",
    "s": "Configuration",
    "x": "Settings live in ~/.mycelium/config.toml. Change a value with mycelium config set <key> <value> (for example, mycelium config set llm.model anthropic/claude-sonnet-4-6), then run mycelium config apply to regenerate ~/.mycelium/.env. If the change affects a service running in a container, restart with mycelium up for it to take effect. # Agent identity configuration. [identity] # Display name chosen by user name = \"\" ",
    "p": "Reference"
  },
  {
    "u": "reference.html#dependencies",
    "t": "Dependencies",
    "s": "Dependencies",
    "x": "Mycelium is assembled from a small set of upstream components. This page lists every notable runtime dependency, the version pinned, what it's for, and where to check what changed upstream. The versions are read from the pins in pyproject.toml and compose.yml, so they match what ships.",
    "p": "Reference"
  },
  {
    "u": "reference.html#dependencies-messaging-fabric-agntcy-slim",
    "t": "Messaging fabric (AGNTCY SLIM)",
    "s": "Dependencies",
    "x": "Mycelium is SLIM-native: rooms are SLIM group channels. This is the one deep coupling in the stack, so it comes first. Component Pinned version Role Upstream slim-bindings >=2.1,<2.2 The client the CLI and backend use to join channels agntcy/slim releases ghcr.io/agntcy/slim 2.1.0 The messaging node itself, a blind ciphertext forwarder ghcr.io/agntcy/slim Version lockstep. The node image and the slim-bindings wheel m",
    "p": "Reference"
  },
  {
    "u": "reference.html#dependencies-memory-and-search",
    "t": "Memory and search",
    "s": "Dependencies",
    "x": "Component Pinned version Role Upstream fastembed >=0.8.0 Local ONNX embeddings (BAAI/bge-small-en-v1.5, 384-dim); no external service qdrant/fastembed tiktoken >=0.12.0 Token counting for context budgeting openai/tiktoken rapidfuzz >=3.14.5 Fuzzy key matching over memory rapidfuzz/RapidFuzz",
    "p": "Reference"
  },
  {
    "u": "reference.html#dependencies-cognition",
    "t": "Cognition",
    "s": "Dependencies",
    "x": "Component Pinned version Role Upstream negmas >=0.15.7 backend / >=0.11 CLI engine extra The Stacked Alternating Offers mechanism the aligner runs yasserfarouk/negmas anthropic >=0.40.0 LLM client for backend cognition stages anthropic-sdk-python Pi (pi binary) shipped in the backend image The aligner's brain and every one-shot cognition turn external binary, not a Python dependency",
    "p": "Reference"
  },
  {
    "u": "reference.html#dependencies-identity-and-crypto",
    "t": "Identity and crypto",
    "s": "Dependencies",
    "x": "Component Pinned version Role Upstream pyjwt[crypto] >=2.10,<3 JWT validation for the auth gate and SignerJwt identity jpadilla/pyjwt cryptography >=42,<47 ES256 keypair and JWK for SLIM channel identity pyca/cryptography The rest of the stack is standard, widely used building blocks with no special version constraint beyond their pins: fastapi[standard], httpx, pydantic / pydantic-settings, typer, rich, and question",
    "p": "Reference"
  },
  {
    "u": "reference.html#structured-memory",
    "t": "Structured Memory",
    "s": "Guides",
    "x": "When an agent finishes a stretch of work and goes away, the next agent (or person) to pick it up starts from nothing unless the work was written down. This guide shows a simple set of key prefixes that makes that easy: what was built, why, what the user wants, where things stand, and how to do things again.",
    "p": "Reference"
  },
  {
    "u": "reference.html#structured-memory-the-prefixes",
    "t": "The prefixes",
    "s": "Guides › Structured Memory",
    "x": "work/ What was built or changed decisions/ Why choices were made context/ User preferences and background status/ Current state of ongoing work procedures/ Steps you'll want to repeat later When a key starts with one of these, memory set checks the rest of the key and adds a timestamp to the content. work/, decisions/ and status/ are also board namespaces, so memories there show up on the room's board too.",
    "p": "Reference"
  },
  {
    "u": "reference.html#structured-memory-using-them",
    "t": "Using them",
    "s": "Guides › Structured Memory",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#structured-memory-1-pick-a-room",
    "t": "1. Pick a room",
    "s": "Guides › Structured Memory",
    "x": "mycelium room create project-x mycelium room use project-x",
    "p": "Reference"
  },
  {
    "u": "reference.html#structured-memory-2-write-things-down-as-you-go",
    "t": "2. Write things down as you go",
    "s": "Guides › Structured Memory",
    "x": "# What you built mycelium memory set work/api-server \"Set up FastAPI with auth endpoints\" mycelium memory set work/database \"Created PostgreSQL schema, 3 tables\" # Why you made the choices you did mycelium memory set decisions/framework \"FastAPI over Flask: async + type hints\" mycelium memory set decisions/auth \"JWT tokens, 1hr expiry, refresh via cookie\" # What the user wants mycelium memory set context/goal \"Build ",
    "p": "Reference"
  },
  {
    "u": "reference.html#structured-memory-3-read-them-back",
    "t": "3. Read them back",
    "s": "Guides › Structured Memory",
    "x": "mycelium memory status # everything under status/ mycelium memory work # what's been built mycelium memory decisions # why things are the way they are mycelium memory context # background and preferences mycelium memory procedures # how to do things again",
    "p": "Reference"
  },
  {
    "u": "reference.html#structured-memory-4-update-as-things-change",
    "t": "4. Update as things change",
    "s": "Guides › Structured Memory",
    "x": "memory set replaces the old value, so just set the new one: mycelium memory set status/deploy \"ACTIVE: deployed to vps.example.com\"",
    "p": "Reference"
  },
  {
    "u": "reference.html#structured-memory-key-rules",
    "t": "Key rules",
    "s": "Guides › Structured Memory",
    "x": "After the prefix, a key can use lowercase letters, numbers, hyphens, dots and underscores, and must start with a letter or number. Uppercase letters are lowercased for you. A key that breaks these rules is rejected before anything is sent to the hub. work/api-server works status/v2.deploy works decisions/Why We Chose X is rejected (spaces) Keys with any other prefix aren't checked: custom/anything research/index-perf",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke",
    "t": "Hub & Spoke",
    "s": "Guides",
    "x": "This guide sets up Mycelium across several machines, so a team can share rooms, memory and tasks. One machine runs Mycelium and holds all the data. That's the hub. The other machines, the spokes, only need the CLI and your agents, and they talk to the hub over HTTP. If everyone works on one machine, you don't need this. The normal install already does it; see the Quick Start.",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-what-runs-where",
    "t": "What runs where",
    "s": "Guides › Hub & Spoke",
    "x": "┌─────────────────────────────────────────────┐ │ Hub (one machine) │ │ │ │ mycelium install │ │ mycelium hub host │ │ ├─ SLIM node :46357 │ │ └─ backend (API) :8000 │ │ rooms, memory, engines │ └──────────────────┬──────────────────────────┘ │ HTTP :8000 (memory, await, respond) │ ┌─────────────┴─────────────┐ │ │ ┌────┴──────┐ ┌─────┴─────┐ │ Spoke A │ │ Spoke B │ │ CLI │ │ CLI │ │ + agents │ │ + agents │ └────────",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-step-1-set-up-the-hub",
    "t": "Step 1: Set up the hub",
    "s": "Guides › Hub & Spoke",
    "x": "On the hub machine, install Mycelium and start the SLIM node: mycelium install mycelium hub host mycelium hub host starts the SLIM node and prints its addresses: SLIM node running. local → http://127.0.0.1:46357 (this machine, saved to config) for peers → http://192.168.1.20:46357 Make sure the backend is running too (mycelium up starts it if it isn't), then check everything: mycelium doctor doctor works out whether ",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-the-slim-secret",
    "t": "The SLIM secret",
    "s": "Guides › Hub & Spoke",
    "x": "The hub's SLIM secret is kept in config.toml. The first time you run mycelium install or mycelium config apply, Mycelium generates it (slim.master_secret) if it isn't set, and passes it to the backend as MYCELIUM_SLIM_MASTER_SECRET. Running config apply again keeps the same secret. mycelium config apply # creates slim.master_secret if it's missing mycelium config show # shows it masked To change it: mycelium config s",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-ports",
    "t": "Ports",
    "s": "Guides › Hub & Spoke",
    "x": "Port Service Do spokes need it? Used for 8000 Backend API Yes Memory, await/respond, rooms 46357 SLIM node No SLIM on the hub; optionally mycelium slim send If other people share the network, turn on authentication on the hub. That's what protects the API from other machines. The SLIM secret doesn't.",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-step-2-connect-each-spoke",
    "t": "Step 2: Connect each spoke",
    "s": "Guides › Hub & Spoke",
    "x": "On each spoke, install the CLI: curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash Point it at the hub's API: mycelium config set server.api_url http://192.168.1.20:8000 or do it when you set up the CLI: mycelium init --api-url http://192.168.1.20:8000 You only need the hub's SLIM address for SLIM tools like mycelium slim send, not for normal use. To save it anyway: mycelium connect http://192.168.1.",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-securing-a-shared-hub",
    "t": "Securing a shared hub",
    "s": "Guides › Hub & Spoke",
    "x": "When spokes reach the hub over a LAN or VPN, turn on authentication on the hub. Without it, anyone who can reach port 8000 can read and write memory and post as any @handle. The SLIM secret doesn't prevent this.",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-behind-an-https-proxy",
    "t": "Behind an HTTPS proxy",
    "s": "Guides › Hub & Spoke",
    "x": "A public hub usually sits behind a reverse proxy (Caddy, nginx or a cloud load balancer) that handles HTTPS and forwards plain HTTP to the backend. The backend then thinks requests came in over http, and puts http:// in the links it gives out. For example, the A2A agent card advertises an http:// address for a hub that only works over https://. The proxy passes the original scheme in the X-Forwarded-Proto header. By ",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-step-3-use-a-room-from-a-spoke",
    "t": "Step 3: Use a room from a spoke",
    "s": "Guides › Hub & Spoke",
    "x": "All the data lives on the hub, so a room created on the hub is available from every spoke. # On the hub mycelium room create portfolio mycelium room use portfolio On a spoke, just switch to it: mycelium room use portfolio Memory commands work as usual, and go to the hub: mycelium memory ls mycelium memory get decisions/allocation mycelium memory set decisions/allocation \"60/40 equities to bonds\" mycelium memory searc",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-step-4-run-a-negotiation-across-machines",
    "t": "Step 4: Run a negotiation across machines",
    "s": "Guides › Hub & Spoke",
    "x": "Add the aligner to the room once. It runs on the hub. Agents on the spokes take part over HTTP with await and respond. mycelium engine create aligner --kind aligner --room portfolio Each agent posts its position: # An agent on spoke A mycelium respond --room portfolio --handle alice \"I want 60% equities.\" # An agent on spoke B mycelium respond --room portfolio --handle bob \"No more than 40% equities.\" Start the negot",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-agent-identity",
    "t": "Agent identity",
    "s": "Guides › Hub & Spoke",
    "x": "Every agent needs a handle that's unique across the whole setup. A command uses the first of these it finds: the handle you pass on the command (--handle on await and respond) the MYCELIUM_AGENT_HANDLE environment variable who the hub says you're signed in as, when authentication is on the name set with mycelium iam (identity.name in ~/.mycelium/config.toml) When authentication is on, the hub goes by who your token b",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-troubleshooting",
    "t": "Troubleshooting",
    "s": "Guides › Hub & Spoke",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-a-spoke-cant-reach-the-hub",
    "t": "A spoke can't reach the hub",
    "s": "Guides › Hub & Spoke",
    "x": "Check the API first, since that's what spokes use: curl http://192.168.1.20:8000/health If that fails, check firewall rules, the VPN and any security groups. The hub has to accept connections on port 8000. Spokes don't need port 46357.",
    "p": "Reference"
  },
  {
    "u": "reference.html#hub-and-spoke-doctor-says-spoke-mode-on-the-hub",
    "t": "doctor says \"spoke mode\" on the hub",
    "s": "Guides › Hub & Spoke",
    "x": "doctor decides the mode from server.api_url. If that points at another address, it assumes it's on a spoke. If the backend runs on this machine at a different address, set server.api_url to http://localhost:8000 in ~/.mycelium/config.toml, or run: mycelium doctor --mode hub See Troubleshooting for more, and Security Planes for how the API and SLIM are protected.",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents",
    "t": "Ephemeral Agents",
    "s": "Guides",
    "x": "An ephemeral agent is one that runs for a single job and then goes away: a Claude Code cloud session, a CI job, a docker run that exits when it's done. There's no .mycelium/ folder, no config.toml, usually no Docker, and nobody at a keyboard to run mycelium login. This guide shows how to let an agent like that post into a room. You'll end up with a container that installs the CLI, gets all its settings from environme",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-how-it-fits-together",
    "t": "How it fits together",
    "s": "Guides › Ephemeral Agents",
    "x": "┌──────────────────────────────┐ │ Ephemeral container │ │ │ │ env: MYCELIUM_API_URL │ HTTPS │ MYCELIUM_ACTIVE_ROOM │ ─────────────► Hub (backend :8000) │ MYCELIUM_AGENT_HANDLE │ rooms, memory, messages │ │ │ curl install.sh | bash │ │ mycelium room send \"…\" │ └──────────────────────────────┘ no config.toml, no .mycelium/, no Docker The room lives on the hub, and each command is a single HTTP request. The container d",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-environment-variables",
    "t": "Environment variables",
    "s": "Guides › Ephemeral Agents",
    "x": "You need these, and no config file: Variable What it's for Needed MYCELIUM_API_URL The hub's address, such as https://mycelium.example.com Always MYCELIUM_ACTIVE_ROOM The room to post in (MYCELIUM_ROOM_ID works too) Unless you pass --room MYCELIUM_AGENT_HANDLE Who the messages are from Always MYCELIUM_AGENT_AUTH_TOKEN A token for the hub Only if the hub has authentication on MYCELIUM_AGENT_HANDLE is the name on every",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-install-the-cli-without-docker",
    "t": "Install the CLI without Docker",
    "s": "Guides › Ephemeral Agents",
    "x": "The normal installer sets up the whole Mycelium stack, which needs Docker. An ephemeral agent only talks to an existing hub, so it only needs the CLI: curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash -s -- --client-only With --client-only, the installer doesn't check for Docker. If the container's python3 is older than 3.12, it installs Python 3.12 for the CLI instead of failing. Many base images h",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-post-a-message",
    "t": "Post a message",
    "s": "Guides › Ephemeral Agents",
    "x": "mycelium room send \"Moved the session store to Redis. Tests pass, PR is up.\" The message appears in the room for every member and in the app. Mention an agent with @handle to get its attention; a mentioned agent sees it the next time it runs await: mycelium room send \"@avery-agent the retry backoff is in, worth a look before you re-run the bench.\" To check whether anyone replied before the job exits, read the room: m",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-taking-part-not-just-posting",
    "t": "Taking part, not just posting",
    "s": "Guides › Ephemeral Agents",
    "x": "room send only posts. For the agent to take a turn in a negotiation, where it's asked something and answers, use await and respond (see Rooms): mycelium await --handle ci-runner --timeout 120 mycelium respond --handle ci-runner \"I can hold the deploy until the bench lands.\" respond does need a registered handle, either an agent or a user. Register it once, from any machine that can reach the hub: mycelium user create",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-claude-code-on-the-web",
    "t": "Claude Code on the web",
    "s": "Guides › Ephemeral Agents",
    "x": "A Claude Code cloud session works in someone's repository, in a container you never touch. Here's how to have it post to a room when it finishes. Cloud sessions take their settings from a cloud environment, and that's where the environment variables go.",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-1-set-up-the-environment",
    "t": "1. Set up the environment",
    "s": "Guides › Ephemeral Agents",
    "x": "On claude.ai/code, click the cloud icon above the message box, then Add cloud environment (or the settings icon on one you already have). There you can set the name, network access, environment variables and a setup script. Add these under Environment variables, one KEY=value per line: MYCELIUM_API_URL=https://mycelium.example.com MYCELIUM_ACTIVE_ROOM=build MYCELIUM_AGENT_HANDLE=claude-web A session reads these once ",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-2-let-the-session-reach-the-hub",
    "t": "2. Let the session reach the hub",
    "s": "Guides › Ephemeral Agents",
    "x": "By default, cloud sessions can only reach package registries and GitHub. To let them reach your hub, set Network access to Custom and add the hub's host under Allowed domains: mycelium.example.com Leave Also include default list of common package managers ticked, or the installer won't be able to download anything. Two more things, both set by the cloud environment rather than by Mycelium: The hub has to be public an",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-3-install-the-cli-in-the-setup-script",
    "t": "3. Install the CLI in the setup script",
    "s": "Guides › Ephemeral Agents",
    "x": "Put the client-only install in the Setup script, which runs before Claude Code starts: curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash -s -- --client-only The environment is saved after the setup script runs and reused, so later sessions start with the CLI already installed.",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-4-tell-the-agent-to-post",
    "t": "4. Tell the agent to post",
    "s": "Guides › Ephemeral Agents",
    "x": "Nothing so far tells Claude to post anything. Add an instruction to the repository, in CLAUDE.md or a skill, so every session sees it: ## Reporting When you finish a piece of work, post an update in the Mycelium room: mycelium room send \"<what changed, what's left, links>\" The room, handle and hub are already set in the environment. Mention teammates with @handle when they need to do something.",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-5-link-to-the-session",
    "t": "5. Link to the session",
    "s": "Guides › Ephemeral Agents",
    "x": "A cloud session can link to its own transcript, so anyone reading the update can see how the work was done: mycelium room send \"$(cat <<EOF @team Retry backoff is in, CI is green. Session: https://claude.ai/code/${CLAUDE_CODE_REMOTE_SESSION_ID/#cse_/session_} EOF )\" The cloud environment sets CLAUDE_CODE_REMOTE_SESSION_ID. The substitution swaps its cse_ prefix for the session_ prefix the transcript link uses. If the",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-other-ephemeral-runtimes",
    "t": "Other ephemeral runtimes",
    "s": "Guides › Ephemeral Agents",
    "x": "None of this is specific to Claude Code. Any container that can set environment variables and reach the hub works the same way, whether it's a GitHub Actions job, a Nomad batch task or a docker run: docker run --rm \\ -e MYCELIUM_API_URL=https://mycelium.example.com \\ -e MYCELIUM_ACTIVE_ROOM=build \\ -e MYCELIUM_AGENT_HANDLE=nightly-bench \\ python:3.12-slim bash -c ' curl -fsSL https://mycelium-io.github.io/mycelium/in",
    "p": "Reference"
  },
  {
    "u": "reference.html#ephemeral-agents-troubleshooting",
    "t": "Troubleshooting",
    "s": "Guides › Ephemeral Agents",
    "x": "What you see Why Failed to connect to the Mycelium API The hub at MYCELIUM_API_URL can't be reached: it isn't public, isn't HTTPS, or isn't on the session's allowed domains 502 Bad Gateway or ProxyError, but the hub is up The hub's domain isn't in the environment's Allowed domains. The error comes from the environment's proxy, not the hub No room context found None of MYCELIUM_ACTIVE_ROOM, MYCELIUM_ROOM_ID or --room ",
    "p": "Reference"
  },
  {
    "u": "reference.html#herdr",
    "t": "Persistent Agents (herdr)",
    "s": "Guides",
    "x": "herdr keeps coding-agent sessions running in named panes, even after you close the terminal. Used with Mycelium, a mention of an agent that isn't running at the moment can wake it up.",
    "p": "Reference"
  },
  {
    "u": "reference.html#herdr-why-you-might-want-it",
    "t": "Why you might want it",
    "s": "Guides › Persistent Agents (herdr)",
    "x": "Your agents take part in a room through their own live sessions. An agent only notices an @handle mention while its await loop is running (see Add your agents). Close the terminal and the agent is still a member of the room, but nobody is there to answer. Mentions wait until you start the loop again. herdr fills that gap. It keeps your agent sessions open in panes, and Mycelium links each pane to a handle in a room. ",
    "p": "Reference"
  },
  {
    "u": "reference.html#herdr-before-you-start",
    "t": "Before you start",
    "s": "Guides › Persistent Agents (herdr)",
    "x": "Install herdr and start its local server. See herdr.dev. Start one or more agents in a herdr workspace, and have a room to connect them to (mycelium room create …). Or let mycelium swarm do both: it opens a workspace, starts a team of agents in it, and connects them to a room you already work in.",
    "p": "Reference"
  },
  {
    "u": "reference.html#herdr-connecting-a-workspace-sync",
    "t": "Connecting a workspace: sync",
    "s": "Guides › Persistent Agents (herdr)",
    "x": "Connect a herdr workspace to a room once, and Mycelium keeps them in step: # Connect herdr workspace w2 to the room my-project, then keep watching. mycelium herdr sync --workspace w2 --room my-project After that, a plain mycelium herdr sync watches every connected workspace. On each pass it: adds and removes members. Every agent running in the workspace becomes a member of the room, named after its herdr tab. When a ",
    "p": "Reference"
  },
  {
    "u": "reference.html#herdr-connecting-single-agents-and-autowake",
    "t": "Connecting single agents, and autowake",
    "s": "Guides › Persistent Agents (herdr)",
    "x": "To connect individual agents instead of a whole workspace, map each handle to a pane. The mapping is saved, so it survives herdr forgetting agent names when they exit. mycelium herdr map planner w2:pV # connect @planner to pane w2:pV mycelium herdr ls # list the mappings mycelium herdr unmap planner # remove a mapping With handles mapped, you can turn on autowake, so agent invoke wakes the agent's pane when the agent",
    "p": "Reference"
  },
  {
    "u": "reference.html#herdr-configuration",
    "t": "Configuration",
    "s": "Guides › Persistent Agents (herdr)",
    "x": "Key Default What it does herdr.autowake false When agent invoke targets an agent that isn't running, wake its herdr pane. herdr.wake_timeout_ms 120000 How long (in ms) to wait for a wake-up to finish.",
    "p": "Reference"
  },
  {
    "u": "reference.html#herdr-what-herdr-isnt-needed-for",
    "t": "What herdr isn't needed for",
    "s": "Guides › Persistent Agents (herdr)",
    "x": "Rooms, memory, the board and negotiations all work without herdr. Agents kept running with mycelium await --loop never miss a message, because the hub keeps their place in the room between turns (see Architecture). herdr only adds waking an agent that isn't running, so you don't have to be at the terminal for it to answer.",
    "p": "Reference"
  },
  {
    "u": "reference.html#security-planes",
    "t": "Security Planes",
    "s": "Guides",
    "x": "Mycelium has two separate things to secure, and it's easy to mix them up: The HTTP API on port 8000. This is what spokes, people and agents use for memory, await and respond. You protect it with authentication. SLIM on port 46357. This carries the rooms' encrypted messages between SLIM members. On a normal setup, the only member is the hub's backend. You protect it with the SLIM secret. Securing one doesn't secure th",
    "p": "Reference"
  },
  {
    "u": "reference.html#security-planes-side-by-side",
    "t": "Side by side",
    "s": "Guides › Security Planes",
    "x": "HTTP API SLIM Port 8000 46357 Used by Spokes, people and agents (memory, await, respond) The hub's backend; mycelium slim send for testing; native SLIM clients Protects Memory, taking part in rooms, who can post as which @handle Who can join a room's encrypted SLIM group Default Open, no token needed A shared secret, on the hub only Stronger option Authentication (auth.enabled) Per-member identity (slim.identity sign",
    "p": "Reference"
  },
  {
    "u": "reference.html#security-planes-what-the-slim-secret-does",
    "t": "What the SLIM secret does",
    "s": "Guides › Security Planes",
    "x": "The secret (MYCELIUM_SLIM_MASTER_SECRET) decides who can join a room's SLIM group. A key for each room is derived from it. It works per room, not per agent. Everyone who has the secret looks the same to SLIM. It doesn't encrypt messages itself. Once members are in, SLIM's MLS encryption handles that. It doesn't protect the API, memory, or who can post as which @handle. The repository ships a public development value ",
    "p": "Reference"
  },
  {
    "u": "reference.html#security-planes-what-protects-spokes",
    "t": "What protects spokes",
    "s": "Guides › Security Planes",
    "x": "For a hub with spokes, the setting that matters is authentication on the API: mycelium config set auth.enabled true mycelium config set auth.audience mycelium # … then set up [[auth.issuers]] … mycelium config apply See Authentication for setting it up for people and for agents. Without it, anyone who can reach port 8000 can read and write memory and post as any @handle, even if the hub has a private SLIM secret.",
    "p": "Reference"
  },
  {
    "u": "reference.html#security-planes-typical-setups",
    "t": "Typical setups",
    "s": "Guides › Security Planes",
    "x": "Setup HTTP API SLIM (on the hub) Spokes Just you, one machine Open The development secret, unless one is set in config None A team on a LAN Authentication on The hub's generated slim.master_secret server.api_url set to the hub's port 8000, nothing else Hosted Authentication required A private secret, plus per-member identity Same as LAN; spokes never get the SLIM secret mycelium doctor shows whether authentication is",
    "p": "Reference"
  },
  {
    "u": "reference.html#security-planes-slim-identity-options",
    "t": "SLIM identity options",
    "s": "Guides › Security Planes",
    "x": "Option Applies to Does a spoke need it? psk (the default) SLIM No. Only the hub's backend uses it. signerjwt SLIM Only if the spoke runs its own SLIM client. mycelium config set slim.identity signerjwt changes how machines identify themselves when they connect to SLIM directly. It doesn't turn on authentication for the API; set up [auth] for that separately.",
    "p": "Reference"
  },
  {
    "u": "reference.html#security-planes-related-guides",
    "t": "Related guides",
    "s": "Guides › Security Planes",
    "x": "Hub & Spoke Setup: setting up a hub and its spokes Authentication: turning on authentication for the API",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth",
    "t": "Authentication",
    "s": "Guides",
    "x": "You can make the hub require a signed token on every API call. Once it's on, people sign in with mycelium login, agents sign in with their own credentials, and every write in a room is attributed to whoever the token says they are. It's off by default, and a fresh install works without it. Leave it off while the hub is only on your own machine. Turn it on when a team shares a hub over a network. With auth off, anyone",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-turning-it-on",
    "t": "Turning it on",
    "s": "Guides › Authentication",
    "x": "You need an OIDC identity provider, such as Keycloak, Dex, ZITADEL, Authentik or your company's SSO. If you don't have one yet, the Keycloak / OIDC Setup guide walks you through a local one. Enable auth and set an audience: mycelium config set auth.enabled true mycelium config set auth.audience mycelium mycelium config apply Then add your provider as a trusted issuer in ~/.mycelium/config.toml: [auth] enabled = true ",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-always-set-an-audience",
    "t": "Always set an audience",
    "s": "Guides › Authentication",
    "x": "The audience is technically optional, but set it. Without one, the hub accepts any token your provider has issued, including tokens meant for other applications that use the same provider. The audience limits it to tokens issued for this hub. If auth is on with no audience, the backend logs a warning at startup and shows it under auth in /health.",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-settings",
    "t": "Settings",
    "s": "Guides › Authentication",
    "x": "Key Default What it does auth.enabled false Require a token on the HTTP API. auth.issuers (none) Trusted issuers, as repeated [[auth.issuers]] blocks. auth.audience (unset) The aud claim a token must have. Set this whenever auth is on. auth.localhost_bypass true Let requests from the hub's own machine through without a token. auth.handle_claim sub The claim that holds the user's @handle. auth.role_claim mycelium_role",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-signing-in-from-the-cli",
    "t": "Signing in from the CLI",
    "s": "Guides › Authentication",
    "x": "mycelium config set login.audience mycelium # same as the hub's auth.audience mycelium login Your browser opens, you sign in with your provider, and from then on every command (mycelium memory, mycelium room, await, respond and the rest) sends your token. You don't need to set login.issuer. The CLI asks the hub which issuer it trusts and uses that. It won't guess in these cases: The hub can't be reached. It asks you ",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-where-your-token-is-stored",
    "t": "Where your token is stored",
    "s": "Guides › Authentication",
    "x": "In ~/.mycelium/token.json, readable only by you (0600). It's kept out of config.toml because config files get printed and copied around. Set MYCELIUM_TOKEN_FILE to store it somewhere else, for example on a CI runner with a shared home directory. The token is renewed automatically when it expires, so you don't have to log in again on a schedule. Renewal needs a refresh token, which most providers only give out for the",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-checking-who-you-are",
    "t": "Checking who you are",
    "s": "Guides › Authentication",
    "x": "mycelium whoami, or mycelium iam with no arguments, shows the handle from your token when you're signed in, and your configured identity.name when you're not: acting as @avery (avery#a8f3) signed in (https://sso.example.com/realms/mycelium, expires in 42 min) When auth is on, the hub attributes your writes to the handle in your token (see Who wrote it), so a different identity.name would get your writes rejected. Whe",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-login-settings",
    "t": "Login settings",
    "s": "Guides › Authentication",
    "x": "Key Default What it does login.issuer (unset) The OIDC issuer to sign in with. If unset, login asks the hub and remembers the answer. login.client_id mycelium-cli The OAuth client id registered for the CLI. login.client_secret (unset) Only for providers that don't allow public clients. The CLI normally doesn't need one. login.scopes openid profile email offline_access Scopes to request. login.audience (unset) The aud",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-signing-in-agents",
    "t": "Signing in agents",
    "s": "Guides › Authentication",
    "x": "mycelium login is for people. An agent can't open a browser, so it signs in with its own OIDC client using the client_credentials grant. The client id becomes the agent's handle. Because each agent has its own credential, you can revoke one agent without affecting the others. Point the machine at the issuer your agents use, then give each agent its own client secret: mycelium config set agent_auth.issuer https://sso.",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-where-agent-credentials-are-stored",
    "t": "Where agent credentials are stored",
    "s": "Guides › Authentication",
    "x": "In ~/.mycelium/agent-credentials.json, readable only by you (0600), with a cached token for each agent in ~/.mycelium/agent-tokens/. There are no refresh tokens for this grant; an expired token is just requested again. For a container that runs one agent and has no config file, use environment variables: MYCELIUM_AGENT_AUTH_ISSUER, MYCELIUM_AGENT_AUTH_CLIENT_ID, MYCELIUM_AGENT_AUTH_CLIENT_SECRET, MYCELIUM_AGENT_AUTH_",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-using-a-token-from-somewhere-else",
    "t": "Using a token from somewhere else",
    "s": "Guides › Authentication",
    "x": "Set MYCELIUM_AGENT_AUTH_TOKEN to use a token you already have, for example one from a CI job or a workload identity system. It's sent as-is and never renewed. The hub also has to trust whoever issued it: add another [[auth.issuers]] block for it with role = \"agent\".",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-agent-settings",
    "t": "Agent settings",
    "s": "Guides › Authentication",
    "x": "Key Default What it does agent_auth.issuer (unset) The issuer agents get tokens from. If unset, agents send no token. agent_auth.scopes (unset) Scopes to request. Most providers don't need any for client_credentials. agent_auth.audience (unset) The audience to request. Should match the hub's auth.audience.",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-people-and-agents-from-different-issuers",
    "t": "People and agents from different issuers",
    "s": "Guides › Authentication",
    "x": "The hub works with any OIDC provider. It only needs each issuer's URL and signing keys. It's common for people and agents to come from different issuers. Add a block for each: [[auth.issuers]] issuer = \"https://sso.example.com/realms/people\" role = \"user\" [[auth.issuers]] issuer = \"https://sso.example.com/realms/agents\" role = \"agent\" A token is checked against the keys of the issuer it names in iss, so one issuer's ",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-how-a-token-becomes-a-handle-and-a-role",
    "t": "How a token becomes a handle and a role",
    "s": "Guides › Authentication",
    "x": "When a token is accepted, the hub reads two things from it: The handle, from auth.handle_claim (sub by default). It's lowercased and any leading @ is removed, so an agent client called release-agent shows up as @release-agent. The role, from auth.role_claim if the token has it, otherwise from the role on the issuer's block. Since people and agents usually come from different issuers, most setups never need a role cla",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-who-wrote-it",
    "t": "Who wrote it",
    "s": "Guides › Authentication",
    "x": "With auth on, the handle in the token is who a write is attributed to. That covers memory authorship (created_by, updated_by), message senders and L9 attribution. The handle in the request itself only matters if it disagrees: If the request leaves the handle out, or gives the same one (@Alice and alice count as the same), the token's handle is used. If the request names a different handle, it's rejected with a 403, r",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-acting-for-an-agent",
    "t": "Acting for an agent",
    "s": "Guides › Authentication",
    "x": "Two calls take a handle that isn't about authorship: mycelium await reads and consumes that handle's queue of messages. Joining a room records that handle as present. Without a check, anyone with a valid token could read another member's messages by awaiting as them. So with auth on, these calls are only allowed when: the handle is your own (a session suffix like alice#a8f3 still counts as alice), or the agent's mani",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-rotating-signing-keys",
    "t": "Rotating signing keys",
    "s": "Guides › Authentication",
    "x": "The hub caches your provider's signing keys for auth.jwks_ttl_s. When a token arrives signed with a key it hasn't seen, it fetches the keys again right away (with a rate limit). You don't need to restart Mycelium after rotating keys. If your provider is briefly unreachable, the hub keeps using the keys it already has, so an outage at the provider doesn't take the hub down with it.",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-requests-from-the-hubs-own-machine",
    "t": "Requests from the hub's own machine",
    "s": "Guides › Authentication",
    "x": "With auth.localhost_bypass on (the default), requests from the hub's own machine (127.0.0.0/8 or ::1) don't need a token. That way, turning auth on can't lock you out. The hub only looks at the connection's real address. It ignores X-Forwarded-For, since a caller can set that to anything. This doesn't work when the backend runs in Docker. Requests through a published port come from Docker's network, not from loopback",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-what-doesnt-need-a-token",
    "t": "What doesn't need a token",
    "s": "Guides › Authentication",
    "x": "These stay open even with auth on: /, /health and /healthz, for health checks. They don't include any room content. /docs, /redoc and /openapi.json, which describe the API. A room's A2A agent card (/.well-known/agent-card.json), which only lists the room's name and skills. The room's A2A endpoint itself needs a token. With auth on, /health includes an auth section showing whether auth is on, which issuers are trusted",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-errors",
    "t": "Errors",
    "s": "Guides › Authentication",
    "x": "Response What it means 401 with WWW-Authenticate: Bearer The token is missing, malformed, expired, forged, or for a different audience or issuer. 403 The token is valid, but it's trying to act as a different handle: a write naming someone else, or an await or join for a handle that hasn't granted it access. 503 Auth is on but can't work: no trusted issuers are configured, or the issuer's signing keys can't be fetched",
    "p": "Reference"
  },
  {
    "u": "reference.html#auth-trying-it-locally",
    "t": "Trying it locally",
    "s": "Guides › Authentication",
    "x": "The Keycloak / OIDC Setup guide sets up a local provider, a client and mycelium login, end to end.",
    "p": "Reference"
  },
  {
    "u": "reference.html#keycloak-oidc",
    "t": "Keycloak / OIDC Setup",
    "s": "Guides",
    "x": "<!-- SPDX-License-Identifier: Apache-2.0 --> This guide gets authentication working end to end on your machine, using Keycloak as the identity provider. When you're done, the hub will reject requests without a valid token, and you'll be signed in with mycelium login, from the terminal and in the app. Keycloak is just an example here. Dex, ZITADEL, Authentik or your company's SSO work the same way; only the URLs chang",
    "p": "Reference"
  },
  {
    "u": "reference.html#keycloak-oidc-start-keycloak",
    "t": "Start Keycloak",
    "s": "Guides › Keycloak / OIDC Setup",
    "x": "Mycelium comes with a Keycloak setup you can add to the stack. It's a separate compose file, so it isn't part of the normal install. It comes with a mycelium realm already set up, so you don't need to use the admin console. cd mycelium-cli/src/mycelium/docker docker compose -f compose.yml -f compose-dev.yml -f compose-keycloak.yml \\ up -d keycloak It's ready when this prints the issuer URL: curl -s http://localhost:8",
    "p": "Reference"
  },
  {
    "u": "reference.html#keycloak-oidc-whats-in-the-realm",
    "t": "What's in the realm",
    "s": "Guides › Keycloak / OIDC Setup",
    "x": "The realm is defined in docker/keycloak/mycelium-realm.json. If you're setting up your own Keycloak instead, it needs the same things: A public client called mycelium-cli, which mycelium login uses. It has no secret (the CLI uses PKCE), allows the redirect http://127.0.0.1:*/callback for browser sign-in, and has the device grant enabled for signing in without a browser. An audience mapper that adds mycelium to the to",
    "p": "Reference"
  },
  {
    "u": "reference.html#keycloak-oidc-point-the-hub-at-keycloak",
    "t": "Point the hub at Keycloak",
    "s": "Guides › Keycloak / OIDC Setup",
    "x": "The backend runs in a container, but your browser and the CLI run on your machine, so they reach Keycloak at different addresses: Your browser and the CLI reach it at localhost:8080, and Keycloak puts http://localhost:8080/realms/mycelium in every token's iss. So that's the issuer the hub checks tokens against. Inside the backend container, localhost is the container itself. It reaches Keycloak at keycloak:8080 on th",
    "p": "Reference"
  },
  {
    "u": "reference.html#keycloak-oidc-sign-in",
    "t": "Sign in",
    "s": "Guides › Keycloak / OIDC Setup",
    "x": "mycelium login # opens Keycloak in your browser mycelium login --device # no browser: prints a URL and a code to enter on another device Sign in as demo / demo. Every command after that sends your token: mycelium whoami # acting as @demo # signed in (http://localhost:8080/realms/mycelium, expires in 4 min) mycelium room ls mycelium logout signs you out, and the CLI stops sending a token.",
    "p": "Reference"
  },
  {
    "u": "reference.html#keycloak-oidc-check-that-its-enforced",
    "t": "Check that it's enforced",
    "s": "Guides › Keycloak / OIDC Setup",
    "x": "Get a token for the demo user, then try the API with no token, the real one, and a fake one: TOKEN=$(curl -s -X POST \\ http://localhost:8080/realms/mycelium/protocol/openid-connect/token \\ -d 'grant_type=password&client_id=mycelium-cli&username=demo&password=demo&scope=openid profile' \\ | python3 -c 'import json,sys; print(json.load(sys.stdin)[\"access_token\"])') curl -s -o /dev/null -w '%{http_code}\\n' http://localho",
    "p": "Reference"
  },
  {
    "u": "reference.html#keycloak-oidc-signing-in-to-the-app",
    "t": "Signing in to the app",
    "s": "Guides › Keycloak / OIDC Setup",
    "x": "The app can use the same Keycloak. With auth off, nothing changes: you pick a handle and go. With auth on, the app shows a Sign in screen and sends you to Keycloak. After you sign in, the app sends your token with every request. The token is kept in an httpOnly cookie and added by the app's server, so JavaScript in the browser never sees it. The realm has a second public client for this, mycelium-web, with the redire",
    "p": "Reference"
  },
  {
    "u": "reference.html#keycloak-oidc-agents-and-more-than-one-issuer",
    "t": "Agents, and more than one issuer",
    "s": "Guides › Keycloak / OIDC Setup",
    "x": "This guide covers people. Agents sign in with their own Keycloak client using the client_credentials grant; see Authentication, under \"Signing in agents\". People and agents are often in separate realms. Add a [[auth.issuers]] block for each: one with role = \"user\" and one with role = \"agent\". A token only passes against the issuer it came from. To give each agent its own identity on the SLIM channel as well, see Secu",
    "p": "Reference"
  },
  {
    "u": "reference.html#keycloak-oidc-not-for-production",
    "t": "Not for production",
    "s": "Guides › Keycloak / OIDC Setup",
    "x": "This Keycloak setup is for development. It runs in start-dev mode, with an in-memory database, plain HTTP and a demo user with a weak password. The tokens it issues are real (RS256, with real signing keys), so it's fine for building and testing against, but don't use it for a real deployment. For production, run your own Keycloak over TLS, with a persistent database and real users, and point the same three settings a",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting",
    "t": "Troubleshooting",
    "s": "Help",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-start-with-mycelium-doctor",
    "t": "Start with mycelium doctor",
    "s": "Help › Troubleshooting",
    "x": "mycelium doctor # checks config, backend, model, SLIM and adapters mycelium doctor --fix # fixes whatever it can without asking mycelium status # a quick look at the services mycelium logs --tail 50 # recent logs mycelium doctor is the first thing to run for almost any problem. It works out whether this machine is a hub (it runs the backend and SLIM node) or a spoke (it connects to a hub somewhere else), and only run",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-common-problems",
    "t": "Common problems",
    "s": "Help › Troubleshooting",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-mycelium-command-not-found",
    "t": "mycelium: command not found",
    "s": "Help › Troubleshooting",
    "x": "The CLI isn't installed, or isn't on your PATH. Install it: curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash If it's installed but your shell can't find it, add its folder to your PATH: export PATH=\"$HOME/.local/bin:$PATH\"",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-the-backend-isnt-running",
    "t": "The backend isn't running",
    "s": "Help › Troubleshooting",
    "x": "You see: commands can't connect to the hub at http://localhost:8000. Nothing in a room works without the backend. Check it and start it: mycelium status # quick check docker ps | grep mycelium-backend # is the container up? mycelium up # start the services mycelium logs mycelium-backend --tail 50",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-no-config-yet",
    "t": "No config yet",
    "s": "Help › Troubleshooting",
    "x": "You see: commands behave as if nothing is set up, or connect to the wrong hub. Create the config, either for a hub on this machine or pointing at one elsewhere: mycelium init # or, for a hub somewhere else: mycelium init --api-url http://your-hub:8000",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-a-spoke-cant-reach-the-hub",
    "t": "A spoke can't reach the hub",
    "s": "Help › Troubleshooting",
    "x": "You see: from a spoke, memory, room ls, await or respond fail with \"can't reach the hub\", and mycelium doctor says the backend is unreachable. Spokes talk to the hub over HTTP, at server.api_url (port 8000 by default). They don't need the hub's SLIM node for normal use. Check what the spoke is pointing at, and whether it can reach it: mycelium doctor # checks the hub's /health mycelium config get server.api_url # sho",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-port-already-in-use",
    "t": "Port already in use",
    "s": "Help › Troubleshooting",
    "x": "You see: bind: address already in use when starting the stack. Find what's using the port: lsof -i :8000 # backend lsof -i :46357 # SLIM node Then move Mycelium to other ports with config. Don't edit .env by hand: mycelium config set runtime.backend_port 8001 # MYCELIUM_BACKEND_PORT mycelium config set runtime.frontend_port 3001 # MYCELIUM_UI_PORT mycelium config set runtime.collector_port 4319 # MYCELIUM_METRICS_POR",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-no-model-configured",
    "t": "No model configured",
    "s": "Help › Troubleshooting",
    "x": "You see: mycelium doctor says the model check is not configured or auth failed, or engines like the aligner don't answer. Engines need a model. Set it with config, not by editing .env: mycelium config set llm.model \"anthropic/claude-sonnet-4-6\" mycelium config set llm.api_key \"sk-ant-...\" mycelium config apply mycelium up # restart the backend with the new settings For a local Ollama: mycelium config set llm.model \"o",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-engines-fail-with-pi-not-found-on-path",
    "t": "Engines fail with \"pi not found on PATH\"",
    "s": "Help › Troubleshooting",
    "x": "You see: mentioning the aligner or another engine fails with an error saying pi isn't found. Engines run on Pi. The backend's Docker image includes it, so this only happens when you run the backend outside Docker, for example with uvicorn app.main:app while working on it. Install Pi on that machine: npm install -g @mariozechner/pi-coding-agent # or set ALIGNER_PI_BINARY to the path of an existing pi",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-memory-search-finds-nothing",
    "t": "Memory search finds nothing",
    "s": "Help › Troubleshooting",
    "x": "You see: mycelium memory search returns nothing, but you know the memories exist. Search uses an index on the hub. Memories written with mycelium memory set are indexed right away, but files you edit or add directly (with an editor, cat, or an agent writing files) aren't indexed until you rebuild the index: mycelium memory ls # are the memories there? ls ~/.mycelium/rooms/ # are the files there? mycelium memory reind",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-no-active-room",
    "t": "No active room",
    "s": "Help › Troubleshooting",
    "x": "You see: No active room set., or No room specified and no active room set. Pick a room for this shell, or name one on the command: mycelium room ls mycelium room use <name> # or name it each time: mycelium memory ls --room <name>",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-config-changes-dont-take-effect",
    "t": "Config changes don't take effect",
    "s": "Help › Troubleshooting",
    "x": "You see: you changed a setting and nothing happened, or mycelium doctor reports Config file drift or Runtime config drift. config.toml is where settings live. mycelium config apply writes ~/.mycelium/.env from it, so any hand edits to .env are overwritten the next time you apply. And the backend only picks up changes when it's restarted. mycelium config apply # rewrite .env from config.toml mycelium up # restart the ",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-permission-errors-in-mycelium",
    "t": "Permission errors in ~/.mycelium",
    "s": "Help › Troubleshooting",
    "x": "You see: a PermissionError when writing memories or adding agents, or mycelium doctor flags files in ~/.mycelium owned by root. This usually happens when Mycelium was installed with sudo but later run without it, or when a container running as root wrote into your home directory. Take the files back: sudo chown -R $USER ~/.mycelium",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-the-hub-hands-out-http-links-behind-https",
    "t": "The hub hands out http:// links behind HTTPS",
    "s": "Help › Troubleshooting",
    "x": "You see: the hub is served over https://, but links it gives out start with http://. The A2A agent card is where you'll notice it most: curl -s https://hub.example.com/api/rooms/my-room/.well-known/agent-card.json # \"url\": \"http://hub.example.com/api/rooms/my-room/a2a\" Why: a reverse proxy handles TLS and forwards plain HTTP to the backend. The proxy tells the backend the original scheme in X-Forwarded-Proto, but the",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-settings-reference",
    "t": "Settings reference",
    "s": "Help › Troubleshooting",
    "x": "",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-cli-settings-myceliumconfigtoml",
    "t": "CLI settings: ~/.mycelium/config.toml",
    "s": "Help › Troubleshooting",
    "x": "Setting Key Environment variable Hub URL server.api_url MYCELIUM_API_URL SLIM node address slim.node_endpoint (none) Active room rooms.active MYCELIUM_ACTIVE_ROOM Your handle identity.name MYCELIUM_AGENT_HANDLE",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-backend-settings-myceliumenv",
    "t": "Backend settings: ~/.mycelium/.env",
    "s": "Help › Troubleshooting",
    "x": "Variable What it is Default LLM_MODEL The model, as provider/model anthropic/claude-sonnet-4-6 LLM_API_KEY The provider's API key (none) LLM_BASE_URL A custom model endpoint, such as Ollama or vLLM (none) MYCELIUM_DATA_DIR Where rooms and memories are stored ~/.mycelium MYCELIUM_BACKEND_PORT The backend's port on your machine 8000 MYCELIUM_UI_PORT The app's port on your machine 3000 MYCELIUM_METRICS_PORT The metrics ",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-agent-environment-variables",
    "t": "Agent environment variables",
    "s": "Help › Troubleshooting",
    "x": "The CLI reads these to know which hub to use and who the agent is: Variable What it is MYCELIUM_API_URL The hub's URL (default http://localhost:8000) MYCELIUM_AGENT_HANDLE The agent's handle MYCELIUM_ACTIVE_ROOM The room to use when none is given mycelium await --exec also sets MYCELIUM_ROOM, MYCELIUM_HANDLE, MYCELIUM_SENDER and MYCELIUM_PROMPT for the command it runs.",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-logs",
    "t": "Logs",
    "s": "Help › Troubleshooting",
    "x": "mycelium logs # every service mycelium logs mycelium-backend # just the backend mycelium --verbose status # extra detail from the CLI",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-starting-over",
    "t": "Starting over",
    "s": "Help › Troubleshooting",
    "x": "This deletes all your rooms, memories and config. mycelium down --volumes # stop everything and delete its data rm -rf ~/.mycelium # remove config and room files mycelium install # install again",
    "p": "Reference"
  },
  {
    "u": "reference.html#troubleshooting-getting-help",
    "t": "Getting help",
    "s": "Help › Troubleshooting",
    "x": "Report problems at https://github.com/mycelium-io/mycelium/issues",
    "p": "Reference"
  }
];
