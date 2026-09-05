# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""The built-in scenarios ``mycelium onboard`` runs, and the briefing each agent gets.

A scenario is a real, ordinary disagreement between two people on a software
team, written the way they would say it: a release date, a database, a cloud
bill. Nothing here is abstract, and none of it needs a dataset fetched at run
time. The two agents are the user's own coding agents (Claude Code, Cursor,
anything with a shell), each handed a briefing that tells it who it is playing,
what it wants, what it would give, and how to talk to the room.

The briefing is the whole contract between the wizard and the agent: the agent
needs nothing else pasted in, and the text names every command it will run.
"""

from __future__ import annotations

from dataclasses import dataclass, field

# The reserved engine handle the wizard registers and summons.
ALIGNER_HANDLE = "aligner"


@dataclass(frozen=True)
class DemoAgent:
    """One seat at the table: a handle, a job title, and what that person wants."""

    handle: str
    name: str
    role: str
    #: What they want, what they'd give, and their hard line, in the second person.
    brief: str

    @property
    def label(self) -> str:
        return f"{self.name}, the {self.role}"


@dataclass(frozen=True)
class Scenario:
    """A disagreement worth mediating, and the board work that follows it."""

    id: str
    title: str
    #: One sentence for the picker: what the room is about.
    blurb: str
    #: The board row the whole thing runs inside.
    task: str
    #: What the aligner is asked to settle, phrased as the ask on the row.
    question: str
    agents: tuple[DemoAgent, ...]
    #: Follow-up tasks the human files by hand once the agreement is in, as
    #: ``(title, assignee handle)``. The first one is the one the tour pings.
    followups: tuple[tuple[str, str], ...] = field(default_factory=tuple)

    @property
    def room(self) -> str:
        return f"demo-{self.id}"

    @property
    def handles(self) -> list[str]:
        return [a.handle for a in self.agents]


SCENARIOS: dict[str, Scenario] = {
    "release-plan": Scenario(
        id="release-plan",
        title="Plan the 2.0 release",
        blurb="A release manager who wants to ship in two weeks, a QA lead who wants four.",
        task="Plan the 2.0 release: date, what goes in it, and how much testing before we ship",
        question=(
            "agree on a release date, whether dark mode ships in 2.0 or waits, "
            "and how much testing happens before we ship"
        ),
        agents=(
            DemoAgent(
                handle="maya",
                name="Maya",
                role="release manager",
                brief=(
                    "You want 2.0 out the door in two weeks. Sales has promised it to three "
                    "customers and every week of delay costs a renewal conversation. Dark "
                    "mode is nice to have; ship without it if it isn't finished. On testing, "
                    "the automated suite plus a one-day smoke test is enough for you.\n"
                    "You can give: slip one week if that buys a real regression pass on the "
                    "billing flow.\n"
                    "Your hard line: no later than three weeks from today."
                ),
            ),
            DemoAgent(
                handle="theo",
                name="Theo",
                role="QA lead",
                brief=(
                    "You want a full regression pass before 2.0 ships. That takes two weeks "
                    "on its own, so you're asking for four weeks. The billing changes worry "
                    "you: the last release shipped a refund bug that took a month to clean "
                    "up. You'd rather dark mode ship in 2.0, because it touches every screen "
                    "and you want to test it once, not twice.\n"
                    "You can give: three weeks, if billing gets its own regression pass and "
                    "dark mode ships behind a setting that defaults to off.\n"
                    "Your hard line: no release without the billing regression pass."
                ),
            ),
        ),
        followups=(
            ("Write the 2.0 release notes", "maya"),
            ("Run the billing regression pass", "theo"),
        ),
    ),
    "database-choice": Scenario(
        id="database-choice",
        title="Pick a database for the orders service",
        blurb="Platform wants Postgres because they already run it; the orders team wants Mongo.",
        task="Pick the database for the new orders service",
        question=(
            "agree on which database the orders service uses, who owns the migrations, "
            "and when the decision is final"
        ),
        agents=(
            DemoAgent(
                handle="priya",
                name="Priya",
                role="platform engineer",
                brief=(
                    "You want Postgres. The team already runs it in production, backups and "
                    "monitoring exist, and one more database engine is one more thing to get "
                    "paged for at 3am. Schema changes are fine with a migrations tool.\n"
                    "You can give: a JSON column for the parts of an order that genuinely "
                    "vary by vendor.\n"
                    "Your hard line: no new database engine in production this quarter."
                ),
            ),
            DemoAgent(
                handle="sam",
                name="Sam",
                role="orders team lead",
                brief=(
                    "You want MongoDB. Orders look different for every vendor and you don't "
                    "want to write a migration each time a vendor adds a field. Your team "
                    "has shipped on Mongo before and knows it well.\n"
                    "You can give: Postgres, if the order payload lives in a JSON column and "
                    "the platform team owns the migrations tooling so your team is never "
                    "blocked on it.\n"
                    "Your hard line: your team must be able to add a vendor field without "
                    "a schema review meeting."
                ),
            ),
        ),
        followups=(
            ("Set up the migrations tool for the orders service", "priya"),
            ("Load the vendor sample orders into the new schema", "sam"),
        ),
    ),
    "cloud-costs": Scenario(
        id="cloud-costs",
        title="Cut the cloud bill by 30%",
        blurb="Finance needs 30% off by end of quarter; the SRE won't give up staging.",
        task="Cut the monthly cloud bill by 30% before the end of the quarter",
        question=(
            "agree on which environments get downsized, whether we commit to reserved "
            "instances, and the deadline"
        ),
        agents=(
            DemoAgent(
                handle="jordan",
                name="Jordan",
                role="finance ops lead",
                brief=(
                    "You need 30% off the cloud bill by the end of the quarter, six weeks "
                    "from now. The biggest line items are the three staging environments "
                    "and the on-demand instances behind the API. Reserved instances would "
                    "cut 25% on their own with a one-year commitment.\n"
                    "You can give: keep one staging environment running full time.\n"
                    "Your hard line: the number has to be at least 30%, and it has to land "
                    "this quarter."
                ),
            ),
            DemoAgent(
                handle="alex",
                name="Alex",
                role="SRE",
                brief=(
                    "You'll take cost cuts, but not by removing the staging environments the "
                    "release process depends on: two is the minimum for testing a release "
                    "while a hotfix is in flight. You're wary of a one-year reserved "
                    "commitment on the API tier, because it's being rewritten and its "
                    "footprint will change.\n"
                    "You can give: reserved instances for the databases, which aren't "
                    "changing, and shutting staging down outside working hours.\n"
                    "Your hard line: at least two staging environments during release weeks."
                ),
            ),
        ),
        followups=(
            ("Schedule the staging environments to stop overnight", "alex"),
            ("Get quotes for one-year reserved database instances", "jordan"),
        ),
    ),
}

DEFAULT_SCENARIO = "release-plan"


def kickoff_text(scenario: Scenario) -> str:
    """What the human posts in the task's thread to open it.

    No ``@``-mentions on purpose: a mention would queue a wake for agents that
    are not in the room yet, and the briefing already tells each one to come
    and state its position here.
    """
    names = " and ".join(a.name for a in scenario.agents)
    return (
        f"{names}, this one is yours to settle. State your positions here, "
        "then we'll bring in the aligner to work out an agreement."
    )


def briefing(
    scenario: Scenario,
    agent: DemoAgent,
    *,
    room: str,
    row: str,
    hub_url: str,
    gated: bool,
) -> str:
    """The text pasted into one coding agent: who it is, and how to take part.

    Self-contained: it installs the CLI if it's missing, points it at the hub,
    signs in when the hub asks for it, posts an opening position into the task's
    thread, and then keeps awaiting so the aligner can address it. Every command
    is on its own line and simple, because a coding agent's allowlist matches
    simple commands and not compound shell.
    """
    others = ", ".join(f"@{a.handle} ({a.label})" for a in scenario.agents if a is not agent)
    sign_in = (
        "3. This hub asks people to sign in. If `mycelium whoami` says you are not signed "
        "in, run `mycelium login --device` and hand the URL and code to the person you're "
        "working with.\n"
        if gated
        else "3. This hub is open, so there is nothing to sign in to.\n"
    )
    return f"""You are joining a Mycelium room as the agent @{agent.handle}.

Mycelium is a shared board and chat that people and coding agents use to coordinate work. You talk to it with the `mycelium` command-line tool. Another agent is in the room with you: {others}. A person is watching the room and will bring in a mediator (the aligner) once both of you have stated your positions.

## Who you are

{agent.name}, the {agent.role}. {agent.brief}

Speak as {agent.name}, in plain language, two to four sentences per message. Argue your position, say what you would give and what you won't, and be willing to make a deal when the offer is one you can live with.

## Setup (once)

1. Check the CLI is installed: `mycelium --version`. If it is missing, install it: `curl -fsSL https://mycelium-io.github.io/mycelium/install.sh | bash` and open a new shell.
2. Point it at the hub: `mycelium config set server.api_url {hub_url}`
{sign_in}4. Use the room: `mycelium room use {room}`

## Step 1: state your position

Read the task and what has been said in its thread so far:

    mycelium board messages {row} --room {room}

Then post your opening position into that thread, as {agent.name}, in your own words. End it with a confidence marker (0 to 1, how sure you are):

    mycelium respond --room {room} --handle {agent.handle} --task {row} "<your position> [[mycelium: confidence=0.8]]"

## Step 2: stay in the conversation

The aligner will address you one turn at a time. Wait for it:

    mycelium await --room {room} --handle {agent.handle} --json --timeout 600

When that returns a message, read the prompt, decide as {agent.name}, and reply:

    mycelium respond --room {room} --handle {agent.handle} "<your reply> [[mycelium: confidence=0.7 stance=accept]]"

- `stance=accept` when you can live with the offer on the table, `stance=reject` when you can't. Say why in the reply itself.
- If `await` times out with no message, run it again. Keep going until a message says the team reached an agreement or no agreement, or the person you are working with tells you to stop.
- Run each `mycelium` command on its own: no `&&`, pipes, loops or scripts, and one `await` per command.

## Afterwards

The agreement becomes tasks on the board. If someone assigns one to you or mentions you in it, claim it and say how you'd start, in that task's thread:

    mycelium board --room {room}
    mycelium board claim <task id> --room {room}
    mycelium board send <task id> "<what you'll do first>" --room {room}

Then go back to waiting with `mycelium await` as above.
"""
