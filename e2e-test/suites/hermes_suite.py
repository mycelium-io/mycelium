"""Hermes adapter E2E suite — gateway health, return-address, notify-home,
and loop suppression.

Tests 85-89: cover the changes landed in mycelium-cli commit 28aca63
(PID file format tolerance, pre_gateway_dispatch hook, return-address sidecar,
deque-based loop suppression, notify-home via GatewayRunner).

Prerequisites:
  - hermes installed (``hermes`` on PATH of hub and spoke)
  - mycelium CLI up to date on all devices
  - hermes gateway running on hub (oclw4) and spoke1 (oclw3)
  - SSH key at $SSH_KEY_PATH (default: ~/.ssh/ioc.pem)

Run standalone:
    python suites/hermes_suite.py

Run via job:
    pyats run job jobs/hermes_job.py
"""

import hashlib
import hmac
import logging
import os
import subprocess
import sys
import time
import uuid

import httpx
from pyats import aetest

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from libs.matrix_client import check_matrix_reachable
from testcases.hermes_tests import (
    HermesGatewayPidFormats,
    HermesLoopSuppression,
    HermesNotifyHomeGatewayRunner,
    HermesReturnAddressFallback,
    HermesReturnAddressSidecar,
    HERMES_SPOKE1,
    HUB_HOST,
    SSH_KEY,
    SSH_USER,
)

log = logging.getLogger(__name__)

_MATRIX_HOMESERVER = os.environ.get("MATRIX_HOMESERVER", "http://localhost:8008")
_SYNAPSE_CONTAINER = os.environ.get("SYNAPSE_CONTAINER", "matrix-synapse")
# Dedicated Matrix identities for each hermes node — distinct from OpenClaw agent accounts.
_HUB_MATRIX_USER = os.environ.get("HERMES_MATRIX_USER", "hermes-oclw4")
_SPOKE1_MATRIX_USER = "hermes-oclw3"
_SPOKE2_MATRIX_USER = "hermes-oclw5"


def _matrix_admin_token(homeserver: str) -> str:
    """Create a short-lived Synapse admin user via shared secret; return its token."""
    raw = subprocess.check_output(
        ["docker", "exec", _SYNAPSE_CONTAINER,
         "grep", "registration_shared_secret:", "/data/homeserver.yaml"],
        text=True,
    )
    secret = raw.split('"')[1]

    nonce = httpx.get(f"{homeserver}/_synapse/admin/v1/register").json()["nonce"]
    admin_user = f"mycelium-admin-{uuid.uuid4().hex[:12]}"
    admin_pass = uuid.uuid4().hex

    mac = hmac.new(secret.encode(), digestmod=hashlib.sha1)
    for part in [nonce, "\x00", admin_user, "\x00", admin_pass, "\x00", "admin"]:
        mac.update(part.encode())

    resp = httpx.post(
        f"{homeserver}/_synapse/admin/v1/register",
        json={
            "nonce": nonce,
            "username": admin_user,
            "password": admin_pass,
            "admin": True,
            "mac": mac.hexdigest(),
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _synapse_server_name() -> str:
    raw = subprocess.check_output(
        ["docker", "exec", _SYNAPSE_CONTAINER,
         "grep", "server_name:", "/data/homeserver.yaml"],
        text=True,
    )
    return raw.split('"')[1]


def _matrix_impersonate(homeserver: str, admin_token: str, username: str) -> str:
    """Return a fresh token for *username* via Synapse admin impersonation API."""
    server_name = _synapse_server_name()
    resp = httpx.post(
        f"{homeserver}/_synapse/admin/v1/users/@{username}:{server_name}/login",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={},
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def _matrix_ensure_user(homeserver: str, admin_token: str, username: str) -> None:
    """Create *username* on Synapse if it does not already exist."""
    server_name = _synapse_server_name()
    user_id = f"@{username}:{server_name}"
    resp = httpx.get(
        f"{homeserver}/_synapse/admin/v2/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
    )
    if resp.status_code == 200:
        return  # already exists
    # Create via admin v2 upsert
    httpx.put(
        f"{homeserver}/_synapse/admin/v2/users/{user_id}",
        headers={"Authorization": f"Bearer {admin_token}"},
        json={"password": uuid.uuid4().hex, "admin": False, "displayname": username},
    ).raise_for_status()


def _ssh_hub(cmd: str, timeout: float = 20.0) -> tuple[int, str, str]:
    key = os.path.expanduser(SSH_KEY)
    full = f'export PATH="$HOME/.local/bin:$PATH"; {cmd}'
    proc = subprocess.run(
        ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=5", f"{SSH_USER}@{HUB_HOST}", full],
        capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


def _ssh_spoke1(cmd: str, timeout: float = 20.0) -> tuple[int, str, str]:
    key = os.path.expanduser(SSH_KEY)
    full = f'export PATH="$HOME/.local/bin:$PATH"; {cmd}'
    proc = subprocess.run(
        ["ssh", "-i", key, "-o", "StrictHostKeyChecking=no",
         "-o", "ConnectTimeout=5", f"{SSH_USER}@{HERMES_SPOKE1}", full],
        capture_output=True, text=True, timeout=timeout,
    )
    return proc.returncode, proc.stdout, proc.stderr


class CommonSetup(aetest.CommonSetup):
    @aetest.subsection
    def check_cli(self):
        import shutil
        if not shutil.which("mycelium"):
            self.failed("mycelium CLI not found on PATH")

    @aetest.subsection
    def check_ssh_key(self):
        key = os.path.expanduser(os.environ.get("SSH_KEY_PATH", "~/.ssh/ioc.pem"))
        if not os.path.exists(key):
            self.skipped(f"SSH key not found at {key} — set SSH_KEY_PATH")

    @aetest.subsection
    def check_hermes_prereqs(self, testscript):
        """Verify mautrix and the hermes adapter are installed on the hub.

        Does not install anything — that is handled by
        ``scripts/provision_hermes_lab.py``.  Skips the suite with a clear
        message if prereqs are missing so CI catches the gap early.
        """
        from libs.hermes_lab import check_prereqs
        issues = check_prereqs(
            HUB_HOST, SSH_USER, SSH_KEY,
            matrix_homeserver=_MATRIX_HOMESERVER,
            matrix_user=_HUB_MATRIX_USER,
        )
        if issues:
            self.skipped(
                "Hermes lab prerequisites not met — run scripts/provision_hermes_lab.py:\n"
                + "\n".join(f"  • {i}" for i in issues)
            )

    @aetest.subsection
    def setup_matrix_home_channel(self, testscript):
        """Configure Matrix on the hub's hermes gateway and create a test room.

        Uses Synapse admin impersonation (no passwords needed) to obtain tokens
        for the hub hermes user and an observer watcher account.

        Order of operations:
          1. Get tokens for hermes-oclw4 and observer
          2. Create the Matrix test room (observer invites hermes-oclw4)
          3. Write MATRIX_* env vars + MATRIX_HOME_ROOM to ~/.hermes/.env
          4. Restart gateway once (now has token + home room)
          5. Send a seed message as observer (m.notice — bots ignore notices)
             so pre_gateway_dispatch fires and writes the sidecar

        Stores in testscript.parameters:
          matrix_homeserver     (str | None)
          matrix_room_id        (str | None)   room 088 monitors for notify-home
          matrix_observer_token (str | None)   token to read that room
        """
        _unset = {"matrix_homeserver": None, "matrix_room_id": None,
                  "matrix_observer_token": None}

        if not check_matrix_reachable(_MATRIX_HOMESERVER):
            log.warning("Matrix not reachable at %s — skipping matrix setup", _MATRIX_HOMESERVER)
            testscript.parameters.update(_unset)
            return

        try:
            admin_token = _matrix_admin_token(_MATRIX_HOMESERVER)
            for user in (_HUB_MATRIX_USER, _SPOKE1_MATRIX_USER, "observer"):
                _matrix_ensure_user(_MATRIX_HOMESERVER, admin_token, user)
            hub_token = _matrix_impersonate(_MATRIX_HOMESERVER, admin_token, _HUB_MATRIX_USER)
            spoke1_token = _matrix_impersonate(_MATRIX_HOMESERVER, admin_token, _SPOKE1_MATRIX_USER)
            observer_token = _matrix_impersonate(_MATRIX_HOMESERVER, admin_token, "observer")
        except Exception as exc:
            log.warning("Matrix token acquisition failed (%s) — skipping matrix setup", exc)
            testscript.parameters.update(_unset)
            return

        # Create the test room first so we can include MATRIX_HOME_ROOM in
        # the single gateway restart below.  Invite both hermes nodes upfront.
        try:
            obs = httpx.Client(
                base_url=_MATRIX_HOMESERVER,
                headers={"Authorization": f"Bearer {observer_token}"},
                timeout=20.0,
            )
            hub = httpx.Client(
                base_url=_MATRIX_HOMESERVER,
                headers={"Authorization": f"Bearer {hub_token}"},
                timeout=20.0,
            )
            spoke1 = httpx.Client(
                base_url=_MATRIX_HOMESERVER,
                headers={"Authorization": f"Bearer {spoke1_token}"},
                timeout=20.0,
            )
            room_resp = obs.post(
                "/_matrix/client/v3/createRoom",
                json={
                    "preset": "private_chat",
                    "invite": [
                        f"@{_HUB_MATRIX_USER}:local",
                        f"@{_SPOKE1_MATRIX_USER}:local",
                    ],
                    "name": f"hermes-notify-test-{uuid.uuid4().hex[:8]}",
                },
            )
            room_resp.raise_for_status()
            room_id = room_resp.json()["room_id"]
            hub.post(f"/_matrix/client/v3/join/{room_id}", json={}).raise_for_status()
            spoke1.post(f"/_matrix/client/v3/join/{room_id}", json={}).raise_for_status()
            obs.close()
            hub.close()
            spoke1.close()
        except Exception as exc:
            log.warning("Matrix room creation failed (%s) — skipping matrix setup", exc)
            testscript.parameters.update(_unset)
            return

        def _write_matrix_env(ssh_fn, token: str, user: str, homeserver: str) -> None:
            new_vars = [
                f"MATRIX_HOMESERVER={homeserver}",
                f"MATRIX_ACCESS_TOKEN={token}",
                f"MATRIX_USER_ID=@{user}:local",
                f"MATRIX_HOME_ROOM={room_id}",
                "MATRIX_REQUIRE_MENTION=true",
                "MATRIX_AUTO_THREAD=false",
            ]
            env_snippet = (
                "import pathlib; "
                "p = pathlib.Path.home() / '.hermes' / '.env'; "
                "txt = p.read_text() if p.exists() else ''; "
                "keep = [l for l in txt.splitlines() if not l.startswith('MATRIX_')]; "
                f"p.write_text('\\n'.join(keep + {new_vars!r}) + '\\n')"
            )
            rc, _, err = ssh_fn(f"python3 -c {env_snippet!r}", timeout=15.0)
            if rc != 0:
                log.warning("Failed to write Matrix env to %s: %s", user, err[:200])

            # gateway_restart_notification is a YAML-only config key — there
            # is no env-var equivalent.  Use PyYAML to merge it cleanly into
            # platforms.matrix without touching the rest of config.yaml.
            yaml_snippet = (
                "import pathlib, yaml; "
                "p = pathlib.Path.home() / '.hermes' / 'config.yaml'; "
                "cfg = yaml.safe_load(p.read_text()) if p.exists() else {}; "
                "cfg = cfg or {}; "
                "cfg.setdefault('platforms', {}).setdefault('matrix', {})['gateway_restart_notification'] = False; "
                "p.write_text(yaml.dump(cfg, default_flow_style=False, allow_unicode=True))"
            )
            rc, _, err = ssh_fn(f"python3 -c {yaml_snippet!r}", timeout=15.0)
            if rc != 0:
                log.warning("Failed to patch config.yaml restart notification for %s: %s", user, err[:200])

        # Hub uses localhost; spoke reaches Synapse via hub's LAN IP.
        _write_matrix_env(_ssh_hub, hub_token, _HUB_MATRIX_USER, _MATRIX_HOMESERVER)
        _write_matrix_env(_ssh_spoke1, spoke1_token, _SPOKE1_MATRIX_USER,
                          f"http://{HUB_HOST}:8008")

        # Delete leftover hermes-notify-* rooms from prior incomplete test runs.
        # The gateway subscribes to all registered rooms on boot; stale rooms
        # cause CE to flood them with ticks, competing with the live negotiation
        # and slowing hub responses to 60-70s per round.
        for label, ssh_fn in [("hub", _ssh_hub), ("spoke1", _ssh_spoke1)]:
            rc, out, _ = ssh_fn(
                'mycelium room ls 2>/dev/null | grep hermes-notify- | awk \'{print $1}\'',
                timeout=15.0,
            )
            if rc == 0:
                for stale in out.strip().splitlines():
                    stale = stale.strip()
                    if stale:
                        rc2, _, _ = ssh_fn(
                            f"mycelium room delete {stale} --force 2>/dev/null",
                            timeout=15.0,
                        )
                        log.info("Deleted stale room %s on %s (rc=%d)", stale, label, rc2)

        # Restart both gateways so they pick up the new credentials together.
        rc, out, _ = _ssh_hub("hermes gateway restart 2>&1", timeout=90.0)
        log.info("hub gateway restart: rc=%d %s", rc, out.strip()[:150])
        rc, out, _ = _ssh_spoke1("hermes gateway restart 2>&1", timeout=90.0)
        log.info("spoke1 gateway restart: rc=%d %s", rc, out.strip()[:150])
        time.sleep(4)  # let both gateways settle and connect to Matrix

        # MATRIX_HOME_ROOM is already written to ~/.hermes/.env above and is
        # picked up by read_home_address() as a final fallback — no sidecar needed.

        testscript.parameters.update({
            "matrix_homeserver": _MATRIX_HOMESERVER,
            "matrix_room_id": room_id,
            "matrix_observer_token": observer_token,
        })
        log.info("Matrix home channel ready (hub+spoke1): room=%s", room_id)


class test_85_hermes_gateway_pid_formats(HermesGatewayPidFormats):
    pass

class test_86_hermes_return_address_sidecar(HermesReturnAddressSidecar):
    pass

class test_87_hermes_return_address_fallback(HermesReturnAddressFallback):
    pass

class test_88_hermes_notify_home_gateway_runner(HermesNotifyHomeGatewayRunner):
    pass

class test_89_hermes_loop_suppression(HermesLoopSuppression):
    pass


class CommonCleanup(aetest.CommonCleanup):
    @aetest.subsection
    def teardown_matrix_home_channel(self, testscript):
        """Delete the Matrix test room and remove ephemeral Matrix env from nodes."""
        room_id = testscript.parameters.get("matrix_room_id")
        observer_token = testscript.parameters.get("matrix_observer_token")
        homeserver = testscript.parameters.get("matrix_homeserver")

        # Remove MATRIX_* lines from ~/.hermes/.env on both nodes so the next
        # run gets a clean slate (tokens are ephemeral and must be refreshed).
        _clear_snippet = (
            "import pathlib; "
            "p = pathlib.Path.home() / '.hermes' / '.env'; "
            "txt = p.read_text() if p.exists() else ''; "
            "keep = [l for l in txt.splitlines() if not l.startswith('MATRIX_')]; "
            "p.write_text('\\n'.join(keep) + '\\n')"
        )
        for ssh_fn in (_ssh_hub, _ssh_spoke1):
            try:
                ssh_fn(f"python3 -c {_clear_snippet!r}", timeout=10.0)
            except Exception as exc:
                log.warning("Failed to clear Matrix env: %s", exc)

        if not (room_id and observer_token and homeserver):
            return
        try:
            admin_token = _matrix_admin_token(homeserver)
            httpx.delete(
                f"{homeserver}/_synapse/admin/v1/rooms/{room_id}",
                headers={"Authorization": f"Bearer {admin_token}"},
                json={"block": False, "purge": True},
                timeout=15.0,
            )
            log.info("Deleted Matrix test room %s", room_id)
        except Exception as exc:
            log.warning("Failed to delete Matrix test room %s: %s", room_id, exc)


if __name__ == "__main__":
    aetest.main()
