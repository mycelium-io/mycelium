# SPDX-License-Identifier: Apache-2.0
"""Spike #662 v2: the cases v1 could not test -- faithful two-process restarts.

v1 proved the primitive (persistence API reachable, N SignerJwt twins in one
GROUP, restore returns a session) but left the load-bearing questions open. This
harness answers them with REAL subprocesses (`twin_runner.py`) that can be
SIGKILL'd, so a restart drops the connection and the node forgets the subscription
-- exactly a backend/twin bounce, without v1's stale-subscription confounder.

Isolation: every test uses DISTINCT handles (its own SLIM Names) and its own store
root + rooms. Reusing a handle across tests leaked queued messages between them on
the shared node (a per-Name multicast queue re-serves a new subscription under the
same Name), so each scenario gets unique Names.

Scenarios:

  C   PSK cannot persist            API fact: no create_app_with_secret_and_persistence
  D1  clean restart, recv NEW msg   the inbound-after-restore proof v1 skipped
      (+ confirm SLIM does NOT replay a message sent while the twin was down)
  D2  epoch change while offline    twin dead -> moderator rekeys (removes a member)
      -> twin restores: can it still send/recv, or is it stranded past the epoch?
  D3  moderator restart             the group CREATOR (the backend) bounces + restores
  A   wrong passphrase              a fresh App with the WRONG key must NOT be usable
  B   multi-room restore            restore_sessions returns ALL of a twin's rooms

Prints a PASS/FAIL/FINDING matrix. FINDING = a real behavior worth recording that
is not a clean pass/fail (e.g. "rekey strands the twin -> re-invite required").
"""

from __future__ import annotations

import asyncio
import json
import os
import signal
import sys
from pathlib import Path

HERE = Path(__file__).parent
ENDPOINT = os.environ.get("SLIM_ENDPOINT", "http://127.0.0.1:46360")
KEYDIR = os.environ.get("KEYDIR", "/tmp/twin-sessions-spike")
STORE_ROOT = os.environ.get("TWIN_STORE", f"{KEYDIR}/v2-store")
CMD_ROOT = f"{KEYDIR}/v2-cmd"

results: list[tuple[str, str, str]] = []  # (test, verdict, detail)


class Twin:
    """Orchestrator-side handle to one twin subprocess."""

    def __init__(self, handle: str, store_root: str) -> None:
        self.handle = handle
        self.store_root = store_root
        self.proc: asyncio.subprocess.Process | None = None
        self.cmddir: Path | None = None
        self.seq = 0
        self.gen = 0

    async def launch(self, *, wrong_passphrase: bool = False) -> dict:
        self.gen += 1
        self.seq = 0
        self.cmddir = Path(CMD_ROOT) / self.handle / f"gen{self.gen}"
        self.cmddir.mkdir(parents=True, exist_ok=True)
        argv = [
            sys.executable, str(HERE / "twin_runner.py"),
            "--handle", self.handle, "--endpoint", ENDPOINT,
            "--keydir", KEYDIR, "--store", self.store_root, "--cmddir", str(self.cmddir),
        ]
        if wrong_passphrase:
            argv.append("--wrong-passphrase")
        self.proc = await asyncio.create_subprocess_exec(
            *argv, cwd=str(HERE), stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
        )
        return await self._await_file(self.cmddir / "ready.json", timeout=30)

    def post(self, op: str, **kw) -> int:
        assert self.cmddir is not None
        self.seq += 1
        payload = {"op": op, **kw}
        tmp = self.cmddir / f"cmd-{self.seq}.json.tmp"
        tmp.write_text(json.dumps(payload))
        tmp.rename(self.cmddir / f"cmd-{self.seq}.json")
        return self.seq

    async def wait(self, seq: int, *, timeout: float = 30) -> dict:
        assert self.cmddir is not None
        return await self._await_file(self.cmddir / f"res-{seq}.json", timeout=timeout)

    async def cmd(self, op: str, *, timeout: float = 30, **kw) -> dict:
        return await self.wait(self.post(op, **kw), timeout=timeout)

    async def _await_file(self, path: Path, *, timeout: float) -> dict:
        waited = 0.0
        while waited < timeout:
            if path.exists():
                return json.loads(path.read_text())
            await asyncio.sleep(0.03)
            waited += 0.03
        return {"ok": False, "error": f"timeout waiting for {path.name}"}

    async def kill(self) -> None:
        if self.proc and self.proc.returncode is None:
            try:
                self.proc.send_signal(signal.SIGKILL)
            except ProcessLookupError:
                pass
            await self.proc.wait()

    async def quit(self) -> None:
        try:
            self.post("quit")
            if self.proc:
                await asyncio.wait_for(self.proc.wait(), timeout=5)
        except (asyncio.TimeoutError, Exception):  # noqa: BLE001
            await self.kill()


def record(test: str, verdict: str, detail: str) -> None:
    results.append((test, verdict, detail))
    print(f"  [{verdict:7}] {test}: {detail}", flush=True)


async def _join(mod: Twin, member: Twin) -> dict:
    """Member joins mod's group; returns the member's join result (with epoch)."""
    js = member.post("join")
    await mod.cmd("invite", handle=member.handle)
    return await member.wait(js)


async def _recv_broadcast(mod: Twin, member: Twin, *, rounds: int = 8) -> dict:
    """Have `mod` broadcast until `member` receives inbound after a restore.

    The load-bearing detail (confirmed via deepwiki against the SLIM source, and
    present in 2.1.0): restore_sessions sends the member's online `rejoin()`, but
    the MODERATOR only re-adds the member to its fan-out list when it *processes*
    that rejoin control message -- which happens only while the moderator is
    actively draining its session (get_message). A moderator that only publishes
    never re-adds the member, so inbound stays dead. This is exactly mycelium's
    production posture: the backend moderator's persister IS an always-draining
    receive loop. So each round we make the moderator drain (recv, which processes
    the rejoin as a side effect) before broadcasting.
    """
    for i in range(1, rounds + 1):
        await mod.cmd("recv", timeout=1)  # drain control (processes the rejoin); data may time out
        await mod.cmd("send", text=f"probe-{i}")
        r = await member.cmd("recv", timeout=2)
        if r.get("ok") and str(r.get("payload", "")).startswith("probe-"):
            return {"ok": True, "rounds": i, "payload": r["payload"], "sender": r.get("sender")}
    return {"ok": False, "rounds": rounds}


# --------------------------------------------------------------------------- C
def test_c_psk_cannot_persist() -> None:
    import slim_bindings as s

    combo = any("secret" in m and "persist" in m for m in dir(s.Service))
    if combo:
        record("C psk-persist", "FINDING", "a secret+persistence method exists after all -- re-check")
    else:
        record(
            "C psk-persist", "PASS",
            "no create_app_with_secret_and_persistence: persistence REQUIRES the "
            "identity tier (signerjwt/spire); default PSK cannot persist.",
        )


# -------------------------------------------------------------------------- D1
async def test_d1_clean_restart() -> None:
    store = f"{STORE_ROOT}/d1"
    mod, alice = Twin("d1mod", store), Twin("d1alice", store)
    try:
        await mod.launch(); await alice.launch()
        await mod.cmd("create_group", room="d1room")
        await _join(mod, alice)
        await mod.cmd("send", text="hello-1")
        r = await alice.cmd("recv", timeout=10)
        if r.get("payload") != "hello-1":
            record("D1 restart-recv", "FAIL", f"baseline delivery broken: {r}"); return

        await alice.kill()
        await mod.cmd("send", text="while-down")  # SLIM has no offline replay -> should be LOST
        await alice.launch()
        rr = await alice.cmd("restore")
        if not rr.get("n_sessions"):
            record("D1 restart-recv", "FAIL", f"restore returned no sessions: {rr}"); return

        miss = await alice.cmd("recv", timeout=3)
        replayed = miss.get("payload") == "while-down"

        # Inbound after restore, tolerating async rejoin propagation (see helper).
        got = await _recv_broadcast(mod, alice)
        recv_ok = got.get("ok")

        await alice.cmd("send", text="alice-back")
        mg = await mod.cmd("recv", timeout=10)
        send_ok = mg.get("payload") == "alice-back"

        replay_note = "missed msg NOT replayed (correct)" if not replayed else "UNEXPECTED replay"
        if recv_ok and send_ok:
            record("D1 restart-recv", "PASS",
                   f"post-restore recv+send both work once the moderator drains the rejoin "
                   f"(inbound resumed after {got.get('rounds')} round(s)); {replay_note}. "
                   "mycelium's persister is already an always-draining loop, so this holds in prod.")
        elif send_ok and not recv_ok:
            record("D1 restart-recv", "FINDING",
                   f"restored twin can SEND (mod saw {mg.get('payload')!r}) but never received a "
                   f"broadcast across {got.get('rounds')} rounds even with the moderator draining; "
                   f"{replay_note}. Contradicts the documented rejoin design -- file upstream.")
        else:
            record("D1 restart-recv", "FAIL",
                   f"recv_ok={recv_ok} send_ok={send_ok} recv={got} send-seen={mg}; {replay_note}")
    finally:
        await mod.quit(); await alice.quit()


# -------------------------------------------------------------------------- D2
async def test_d2_epoch_change_offline() -> None:
    store = f"{STORE_ROOT}/d2"
    mod, alice, bob = Twin("d2mod", store), Twin("d2alice", store), Twin("d2bob", store)
    try:
        await mod.launch(); await alice.launch(); await bob.launch()
        await mod.cmd("create_group", room="d2room")
        ae = await _join(mod, alice)
        await _join(mod, bob)
        await mod.cmd("send", text="e-hello")
        a1 = await alice.cmd("recv", timeout=10)
        await bob.cmd("recv", timeout=10)
        if a1.get("payload") != "e-hello":
            record("D2 epoch-offline", "FAIL", f"baseline group broken: {a1}"); return
        epoch_before = ae.get("epoch")

        await alice.kill()
        re = await mod.cmd("remove", handle=bob.handle)  # rekey; alice never sees this Commit
        epoch_after = re.get("epoch")

        await alice.launch()
        rr = await alice.cmd("restore")
        n = rr.get("n_sessions")
        if not n:
            record("D2 epoch-offline", "FINDING",
                   f"restore after rekey returned {n} sessions (epoch {epoch_before}->{epoch_after}): "
                   "a twin that misses a Commit is STRANDED and needs re-invite."); return

        await mod.cmd("send", text="post-epoch")
        got = await alice.cmd("recv", timeout=8)
        recv_ok = got.get("payload") == "post-epoch"
        await alice.cmd("send", text="alice-post-epoch")
        mg = await mod.cmd("recv", timeout=8)
        send_ok = mg.get("payload") == "alice-post-epoch"

        if recv_ok and send_ok:
            record("D2 epoch-offline", "PASS",
                   f"twin resumed ACROSS a rekey (epoch {epoch_before}->{epoch_after}) and still "
                   "sends+receives -- SLIM self-heals the epoch on rejoin.")
        else:
            record("D2 epoch-offline", "FINDING",
                   f"restore returned a session but recv_ok={recv_ok} send_ok={send_ok} "
                   f"(epoch {epoch_before}->{epoch_after}): the resumed twin is at a STALE epoch "
                   "and cannot transact -- re-invite required after a rekey.")
    finally:
        await mod.quit(); await alice.quit(); await bob.quit()


# -------------------------------------------------------------------------- D3
async def test_d3_moderator_restart() -> None:
    store = f"{STORE_ROOT}/d3"
    mod, alice = Twin("d3mod", store), Twin("d3alice", store)
    try:
        await mod.launch(); await alice.launch()
        await mod.cmd("create_group", room="d3room")
        await _join(mod, alice)
        await mod.cmd("send", text="m1")
        if (await alice.cmd("recv", timeout=10)).get("payload") != "m1":
            record("D3 moderator-restart", "FAIL", "baseline moderator->member broken"); return

        await mod.kill()  # the backend / group creator dies
        await mod.launch()
        rr = await mod.cmd("restore")
        n = rr.get("n_sessions")
        if not n:
            record("D3 moderator-restart", "FINDING",
                   f"the group CREATOR restored {n} sessions: a backend bounce cannot resume the "
                   "moderator role from persistence -- the room must be re-created/re-invited."); return

        await mod.cmd("send", text="m2")
        recv_ok = (await alice.cmd("recv", timeout=10)).get("payload") == "m2"
        await alice.cmd("send", text="a1")
        mg = await mod.cmd("recv", timeout=10)
        send_ok = mg.get("payload") == "a1"
        if recv_ok and send_ok:
            record("D3 moderator-restart", "PASS",
                   "restored moderator keeps the room live: member still receives moderator "
                   "broadcasts and the moderator receives member replies.")
        else:
            record("D3 moderator-restart", "FINDING",
                   f"moderator restored a session but recv_ok={recv_ok} send_ok={send_ok}: "
                   "the room is not fully live after a moderator bounce.")
    finally:
        await mod.quit(); await alice.quit()


# --------------------------------------------------------------------------- A
async def test_a_wrong_passphrase() -> None:
    store = f"{STORE_ROOT}/a"
    mod, alice = Twin("amod", store), Twin("aalice", store)
    try:
        await mod.launch(); await alice.launch()
        await mod.cmd("create_group", room="aroom")
        await _join(mod, alice)
        await mod.cmd("send", text="persist-me")
        await alice.cmd("recv", timeout=10)  # establish + persist state
        await alice.kill()

        # Relaunch alice pointed at her EXISTING store but with the WRONG passphrase.
        ready = await alice.launch(wrong_passphrase=True)
        if ready.get("error"):
            record("A wrong-passphrase", "PASS",
                   f"App refused to open the store with a wrong key at startup: {ready.get('error')}")
            return
        rr = await alice.cmd("restore")
        if rr.get("error") or not rr.get("n_sessions"):
            record("A wrong-passphrase", "PASS",
                   f"restore with wrong passphrase yielded no usable session: {rr}")
            return
        # restore enumerated a session ROW -- that alone does not prove the key
        # worked (the MLS secrets may decrypt lazily). Prove USABILITY: can the
        # wrong-key twin actually receive a group message? If yes, the at-rest key
        # is NOT load-bearing (a real hole). If no, the key IS load-bearing.
        await mod.cmd("send", text="after-wrong")
        got = await alice.cmd("recv", timeout=6)
        if got.get("ok") and got.get("payload") == "after-wrong":
            record("A wrong-passphrase", "FAIL",
                   f"wrong-passphrase twin RECEIVED group traffic ({got}) -- at-rest key is NOT load-bearing!")
        else:
            record("A wrong-passphrase", "PASS",
                   f"restore returned a row (n={rr.get('n_sessions')}) but the wrong-key twin cannot "
                   f"transact ({got.get('error')}) -- the passphrase IS load-bearing for MLS state.")
    finally:
        await mod.quit(); await alice.quit()


# --------------------------------------------------------------------------- B
async def test_b_multi_room_restore() -> None:
    store = f"{STORE_ROOT}/b"
    moda, modb, alice = Twin("bmod", store), Twin("bmod2", store), Twin("balice", store)
    try:
        await moda.launch(); await modb.launch(); await alice.launch()
        await moda.cmd("create_group", room="broomA")
        await modb.cmd("create_group", room="broomB")
        await _join(moda, alice)
        await _join(modb, alice)  # same twin, second room -> second persisted session
        await alice.kill()
        await alice.launch()
        rr = await alice.cmd("restore")
        n = rr.get("n_sessions")
        if n == 2:
            record("B multi-room", "PASS", "restore_sessions returned BOTH of the twin's rooms (n=2).")
        else:
            record("B multi-room", "FINDING",
                   f"restore_sessions returned n={n} for a twin in 2 rooms -- multi-room resume "
                   "does not restore every session in one call.")
    finally:
        await moda.quit(); await modb.quit(); await alice.quit()


async def main() -> int:
    import shutil

    shutil.rmtree(STORE_ROOT, ignore_errors=True)
    shutil.rmtree(CMD_ROOT, ignore_errors=True)

    print("== spike v2: faithful two-process twin restart matrix ==", flush=True)
    test_c_psk_cannot_persist()
    for name, coro in [
        ("D1", test_d1_clean_restart()),
        ("D2", test_d2_epoch_change_offline()),
        ("D3", test_d3_moderator_restart()),
        ("A", test_a_wrong_passphrase()),
        ("B", test_b_multi_room_restore()),
    ]:
        try:
            await coro
        except Exception as exc:  # noqa: BLE001
            record(name, "ERROR", f"{type(exc).__name__}: {exc}")

    print("\n== summary ==", flush=True)
    for test, verdict, detail in results:
        print(f"  {verdict:7} {test:22} {detail}", flush=True)
    failed = [r for r in results if r[1] in ("FAIL", "ERROR")]
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
