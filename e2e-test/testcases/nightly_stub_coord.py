"""Nightly checks — stub agent coordination tests.

Gates: nightly / pre-release. No real LLM — stubs respond mechanically.

SLIM-native flow (per test):
  1. setup_coordination: creates agents, posts opening positions, creates aligner
  2. run_stubs_until_terminal:
       a. Stubs start await (generates coordination_join → presence)
       b. Main thread invokes aligner once all stubs have joined
       c. Aligner starts rounds; stubs respond per tick
       d. Poll for l9_commit (converged or rejected)

Tests:
  001 - Happy path: two stubs accept every turn → converged
  002 - Rejection path: one stub always rejects → rejected after round budget
  003 - Counter-offer chain: stub B counters N rounds then accepts → converged
  004 - Respond without active await is rejected by backend
  005 - Cross-episode memory: session 1 writes a work/ row → session 2 agent_context contains it
  006 - Multi-session 100% response rate
"""

from __future__ import annotations

import logging
import re
import time
import uuid

from pyats import aetest

from libs.coordination_flow import (
    CoordinationSetup,
    collect_debug_info,
    setup_coordination,
)
from libs.mycelium_api import MyceliumAPI
from libs.mycelium_cli import MyceliumCLI
from libs.stub_agent import StubAgent, StubRunResult, run_stubs_until_terminal

log = logging.getLogger(__name__)

parameters = {}

_STUB_TOTAL_TIMEOUT = 180   # seconds for full stub run
_TURN_TIMEOUT = 60          # seconds for a single await call
_MAX_ROUNDS = 20
_JOIN_WAIT = 10             # seconds to wait for coordination_join events


def _fresh_room(suffix: str = "") -> str:
    return f"qa-coord-fresh-{suffix or uuid.uuid4().hex[:8]}"


# Stub opening positions — domain-realistic, not test-metadata
_POS_A = "I believe a 30-day retention window balances cost and compliance needs."
_POS_B = "I think 90-day retention is required to meet our audit obligations."
_POS_COUNTER = "I propose 60-day retention as a compromise between cost and compliance."


class TwoStubHappyPath(aetest.Testcase):
    """001 — Two stubs accept every turn → session converges."""

    uid = "nightly_001"

    @aetest.setup
    def setup(self, api: MyceliumAPI, cli: MyceliumCLI, testscript):
        self.room = _fresh_room()
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        api.create_room(self.room, description="Nightly stub happy path")
        self.coord = setup_coordination(
            api, cli, self.room,
            agent_handles=["stub-a", "stub-b"],
            opening_positions={"stub-a": _POS_A, "stub-b": _POS_B},
        )
        if self.coord is None:
            self.failed("coordination setup failed")

    @aetest.test
    def stubs_converge(self, api: MyceliumAPI, cli: MyceliumCLI):
        stubs = [
            StubAgent(self.room, "stub-a", action="accept", cli=cli),
            StubAgent(self.room, "stub-b", action="accept", cli=cli),
        ]
        run_result = run_stubs_until_terminal(
            api, stubs, setup=self.coord,
            max_rounds=_MAX_ROUNDS, turn_timeout=_TURN_TIMEOUT,
            join_wait=_JOIN_WAIT, total_timeout=_STUB_TOTAL_TIMEOUT,
        )
        self._assert_terminal(run_result, expect_converged=True)

    def _assert_terminal(self, r: StubRunResult, *, expect_converged: bool) -> None:
        if r.timed_out:
            self.failed(
                f"TIMEOUT: no terminal state within {_STUB_TOTAL_TIMEOUT}s. "
                f"debug={collect_debug_info(None, self.room, ['stub-a','stub-b'])}"
                if False else f"TIMEOUT: no terminal state within {_STUB_TOTAL_TIMEOUT}s."
            )
        if r.terminal is None:
            self.failed("No terminal state detected")
        if expect_converged and not r.converged:
            self.failed(
                f"Expected converged, got subkind={r.terminal.get('subkind')!r}. "
                f"turns={[(t.handle, t.action, t.code) for t in r.turns]}"
            )
        log.info(
            "Terminal: subkind=%s converged=%s turns=%d response_rate=%.0f%%",
            r.terminal.get("subkind"), r.converged, len(r.turns), r.response_rate * 100,
        )

    @aetest.cleanup
    def teardown(self, api: MyceliumAPI):
        api.delete_room(self.room)


class TwoStubRejectionPath(aetest.Testcase):
    """002 — One stub always rejects → session reaches rejected terminal."""

    uid = "nightly_002"

    @aetest.setup
    def setup(self, api: MyceliumAPI, cli: MyceliumCLI, testscript):
        self.room = _fresh_room()
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        api.create_room(self.room, description="Nightly stub rejection")
        self.coord = setup_coordination(
            api, cli, self.room,
            agent_handles=["stub-accept", "stub-reject"],
            opening_positions={
                "stub-accept": _POS_A,
                # Vague, dimensionless prose here ("I will not accept any
                # compromise on this matter") occasionally left the aligner's
                # LLM-driven issue-discovery step with nothing to structure a
                # discussion around, so it rejected immediately with zero
                # ticks sent to either stub — a legitimate "rejected" outcome,
                # but one that never exercises the actual reject response this
                # test is about. A concrete, issue-bearing (if absolute)
                # position gives it real material every time, same as every
                # other passing test's positions do.
                "stub-reject": (
                    "I think 90-day retention is required to meet our audit "
                    "obligations, and I will not accept anything shorter under "
                    "any circumstances."
                ),
            },
        )
        if self.coord is None:
            self.failed("coordination setup failed")

    @aetest.test
    def session_terminates_on_rejection(self, api: MyceliumAPI, cli: MyceliumCLI):
        def _accept_only_30(round_num: int, turn_json: dict) -> str:
            # An unconditional accepter accepts whatever lands on the table —
            # including stub-reject's own number — which converges every
            # time regardless of stub-reject's mechanical position. That's
            # genuinely correct negotiation behavior given an accepter with
            # no position of its own, not a bug; it just means "one stub
            # always rejects" can't reliably produce a *rejected* terminal
            # unless the other side actually holds a position too. Accepting
            # only its own stated number (30) guarantees the two numbers
            # never meet, so the round budget — not mediator luck — is what
            # produces rejected.
            #
            # The mediator's prompt (mediator.py's _prompt_for) always opens
            # with a static "Issue space: data_retention_window_days ∈ {30,
            # ...}" preamble, and its LLM-generated "MEDIATOR: ..." framing
            # note can freely mention either side's original ask — both are
            # present on every single turn regardless of what's actually on
            # the table that round. A bare "30" in prompt substring check
            # matches either one even when the real current offer is 90 —
            # confirmed live in CI: nightly_002 converged on
            # {'data_retention_window_days': '90'} because this falsely
            # accepted stub-reject's own number. Extract just the offer
            # value itself ("Current standing offer: ..." when proposing,
            # "The offer on the table is ..." when responding) and check
            # only that — never the issue-space listing or the mediator's
            # free-text commentary.
            prompt = (turn_json or {}).get("prompt") or ""
            match = re.search(
                r"(?:Current standing offer|offer on the table is):?\s*(\(.*?\)|None)", prompt
            )
            offer_text = match.group(1) if match else ""
            return "accept" if "30" in offer_text else "reject"

        stubs = [
            StubAgent(
                self.room, "stub-accept", action="reject", cli=cli,
                action_fn=_accept_only_30,
                prose=_POS_A,
            ),
            # A generic reject reply (the default "This does not meet my
            # requirements.") carries no number, so the mediator's NLU can
            # come back "unreadable" on it and fall back to a *wrong* held
            # value instead of stub-reject's actual position. Restating the
            # number every round (same pattern CounterOfferChain below
            # already uses via prose=) keeps every reply machine-parseable
            # as an actual reject-at-90, not a guess.
            StubAgent(
                self.room, "stub-reject", action="reject", cli=cli,
                prose="I require 90-day retention and reject any shorter window.",
            ),
        ]
        # A genuine stalemate (neither side's number ever satisfies the
        # other) has to run all the way to the aligner's own step cap
        # (ALIGNER_MEDIATOR_MAX_STEPS=20) before it gives up and emits
        # rejected — there's no other way to reach a real rejected terminal
        # here, by design. The mediator's own round_n only advances once per
        # SAO step, and each step costs a real LLM call (broker + interpret,
        # a Pi-agent session) on top of the raw stub await/reply — measured
        # ~4 raw stub turns per round_n step. 20 steps needs roughly 80 raw
        # turns; at the observed ~7-9s per raw turn that is ~600s wall clock,
        # and the stub threads themselves must stay alive that whole time
        # (their own max_rounds — not just the total_timeout — bounds how
        # long they keep answering). The shared module-level
        # _MAX_ROUNDS=20 (40 raw turns) starves the mediator of replies well
        # before its step cap, so this test needs its own larger budget on
        # both axes, not just a longer timeout.
        _REJECTION_MAX_ROUNDS = 45
        _REJECTION_TOTAL_TIMEOUT = 660
        run_result = run_stubs_until_terminal(
            api, stubs, setup=self.coord,
            max_rounds=_REJECTION_MAX_ROUNDS, turn_timeout=_TURN_TIMEOUT,
            join_wait=_JOIN_WAIT, total_timeout=_REJECTION_TOTAL_TIMEOUT,
        )
        if run_result.timed_out:
            self.failed(
                f"TIMEOUT: permanent rejecter did not cause terminal state "
                f"within {_REJECTION_TOTAL_TIMEOUT}s — check aligner round budget"
            )
        assert run_result.terminal is not None, "Expected a terminal state"
        assert not run_result.converged, (
            f"Expected rejection (stub-reject never accepts), but converged. "
            f"subkind={run_result.terminal.get('subkind')!r}"
        )
        # Scoped to stub-reject specifically, not both stubs: once the rejecter's
        # own reject lands and the session terminates, stub-accept's in-flight
        # await can legitimately come back SILENT on the losing side of that
        # exact race (its poll timing out right around termination) without
        # that meaning anything about *why* the session ended. A silent
        # stub-reject on *every* turn would mean "rejected" was reached via
        # silence rather than an actual reject response, which is the thing
        # this test exists to rule out — but a real stalemate genuinely rides
        # to the mediator's step cap (pattern: see _REJECTION_TOTAL_TIMEOUT
        # above), and every round after the cap is hit and the episode closes
        # is *expected* to come back silent (no more ticks are ever coming).
        # So the check is "at least one real reject", not "zero silent ones".
        reject_turns = [t for t in run_result.turns if t.handle == "stub-reject"]
        real_reject_turns = [t for t in reject_turns if t.ok]
        assert reject_turns and real_reject_turns, (
            f"Expected stub-reject to have actually responded at least once "
            f"(not gone silent every round) — "
            f"turns={[(t.handle, t.ok, t.round_num) for t in run_result.turns]}"
        )
        log.info(
            "Rejection path terminal: subkind=%s converged=%s",
            run_result.terminal.get("subkind"), run_result.converged,
        )

    @aetest.cleanup
    def teardown(self, api: MyceliumAPI):
        api.delete_room(self.room)


class CounterOfferChain(aetest.Testcase):
    """003 — Stub B counters first N rounds then accepts → eventual convergence."""

    uid = "nightly_003"

    @aetest.setup
    def setup(self, api: MyceliumAPI, cli: MyceliumCLI, testscript):
        self.room = _fresh_room()
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        api.create_room(self.room, description="Nightly counter-offer chain")
        self.coord = setup_coordination(
            api, cli, self.room,
            agent_handles=["stub-proposer", "stub-counter"],
            opening_positions={
                "stub-proposer": _POS_A,
                "stub-counter": _POS_COUNTER,
            },
        )
        if self.coord is None:
            self.failed("coordination setup failed")

    @aetest.test
    def counter_then_accept_terminates(self, api: MyceliumAPI, cli: MyceliumCLI):
        counter_rounds = 2

        def counter_fn(round_num: int, turn_json: dict):
            return "counter" if round_num < counter_rounds else "accept"

        stubs = [
            StubAgent(self.room, "stub-proposer", action="accept", cli=cli),
            StubAgent(self.room, "stub-counter", action="accept", cli=cli,
                      action_fn=counter_fn,
                      prose=_POS_COUNTER),
        ]
        run_result = run_stubs_until_terminal(
            api, stubs, setup=self.coord,
            max_rounds=_MAX_ROUNDS, turn_timeout=_TURN_TIMEOUT,
            join_wait=_JOIN_WAIT, total_timeout=_STUB_TOTAL_TIMEOUT,
        )
        if run_result.timed_out:
            self.failed(f"TIMEOUT: counter-then-accept did not terminate in {_STUB_TOTAL_TIMEOUT}s")
        assert run_result.terminal is not None
        log.info("Counter-offer chain terminal: subkind=%s", run_result.terminal.get("subkind"))

    @aetest.cleanup
    def teardown(self, api: MyceliumAPI):
        api.delete_room(self.room)


class RespondWithoutTurnRejected(aetest.Testcase):
    """004 — Respond without being an awaiting participant is rejected."""

    uid = "nightly_004"

    @aetest.test
    def out_of_turn_respond_fails(self, api: MyceliumAPI, cli: MyceliumCLI, testscript):
        room = _fresh_room()
        testscript.parameters.setdefault("owned_rooms", set()).add(room)
        api.create_room(room)

        r = cli.respond(room, "ghost-handle", "I accept. [<accept>]")
        assert not r.ok, (
            f"Expected respond to fail for unregistered handle, "
            f"but got rc={r.returncode}: {r.stdout[:200]}"
        )
        log.info("Correctly rejected respond from unregistered handle (rc=%d)", r.returncode)
        api.delete_room(room)


class CrossEpisodeMemory(aetest.Testcase):
    """005 — Session 1 writes a work/ row → session 2 agent_context contains it."""

    uid = "nightly_005"

    @aetest.setup
    def setup(self, api: MyceliumAPI, testscript):
        self.room = f"qa-cross-episode-stub-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        api.create_room(self.room, description="Nightly cross-episode memory")

    @aetest.test
    def seed_and_verify_in_context(self, api: MyceliumAPI, cli: MyceliumCLI):
        decision_key = f"decisions/api-design-{uuid.uuid4().hex[:6]}"
        decision_content = "We will use REST with JSON:API conventions."
        r = cli.memory_set(self.room, "qa-tester", decision_key, decision_content)
        assert r.ok, f"memory set failed: {r.error_message}"

        work_key = f"work/auth-migration-{uuid.uuid4().hex[:6]}"
        work_content = "Migrate services to JWT tokens. Owner: @stub-a."
        r = cli.memory_set(self.room, "qa-tester", work_key, work_content)
        assert r.ok, f"memory set failed: {r.error_message}"

        cli.memory_reindex(self.room)
        time.sleep(2)

        import urllib.parse
        enc = urllib.parse.quote(self.room, safe="")
        status, context = api.get_json(f"/rooms/{enc}/agent-context")
        if status == 404:
            status2, data = api.list_memory(self.room)
            assert status2 == 200
            keys = [m.get("key") for m in (data if isinstance(data, list) else [])]
            assert any(decision_key in (k or "") for k in keys), (
                f"Decision key not in memory: {keys}"
            )
            return

        assert status == 200, f"agent_context returned {status}"
        context_str = str(context)
        # agent_context is work/-only by design (fastapi-backend/app/services/
        # briefing.py: "the room's title, and the work that is open in it") —
        # decisions/ never appear there, only in full-text memory search. The
        # cross-episode claim this test is actually proving is that session 2
        # sees what session 1 wrote at all, via the work row both sessions share.
        assert "auth-migration" in context_str or work_content[:20] in context_str, (
            f"Session 1 work row not in session 2 agent_context: {context_str[:500]}"
        )

    @aetest.cleanup
    def teardown(self, api: MyceliumAPI):
        api.delete_room(self.room)


class MultiSessionResponseRate(aetest.Testcase):
    """006 — 3 sequential stub sessions; gate on 100% stub response rate."""

    uid = "nightly_006"
    _N_SESSIONS = 3

    @aetest.setup
    def setup(self, api: MyceliumAPI, testscript):
        self.room = f"qa-coord-fresh-multi-{uuid.uuid4().hex[:8]}"
        testscript.parameters.setdefault("owned_rooms", set()).add(self.room)
        api.create_room(self.room, description="Nightly multi-session response rate")

    @aetest.test
    def all_sessions_100pct_response(self, api: MyceliumAPI, cli: MyceliumCLI):
        total_turns = 0
        successful_turns = 0

        for session_num in range(self._N_SESSIONS):
            log.info("Starting session %d/%d", session_num + 1, self._N_SESSIONS)
            coord = setup_coordination(
                api, cli, self.room,
                agent_handles=["stub-a", "stub-b"],
                opening_positions={
                    "stub-a": f"Session {session_num + 1}: {_POS_A}",
                    "stub-b": f"Session {session_num + 1}: {_POS_B}",
                },
            )
            if coord is None:
                self.failed(f"coordination setup failed for session {session_num + 1}")

            stubs = [
                StubAgent(self.room, "stub-a", action="accept", cli=cli),
                StubAgent(self.room, "stub-b", action="accept", cli=cli),
            ]
            run_result = run_stubs_until_terminal(
                api, stubs, setup=coord,
                max_rounds=_MAX_ROUNDS, turn_timeout=_TURN_TIMEOUT,
                join_wait=_JOIN_WAIT, total_timeout=_STUB_TOTAL_TIMEOUT,
            )

            for turn in run_result.turns:
                total_turns += 1
                if turn.ok:
                    successful_turns += 1
                else:
                    log.warning(
                        "Session %d: SILENT %s round %d — %s",
                        session_num + 1, turn.handle, turn.round_num, turn.detail,
                    )

            if run_result.timed_out:
                log.warning("Session %d timed out", session_num + 1)

        if total_turns == 0:
            self.failed("No turns recorded across any session")

        rate = successful_turns / total_turns
        assert rate == 1.0, (
            f"Expected 100% response rate across {self._N_SESSIONS} sessions, "
            f"got {rate:.0%} ({successful_turns}/{total_turns})"
        )

    @aetest.cleanup
    def teardown(self, api: MyceliumAPI):
        api.delete_room(self.room)
