# SPDX-License-Identifier: Apache-2.0
# Copyright 2026 Mycelium Contributors

"""``mycelium hub serve`` — host-side runner for web-triggered coordinations.

Lets non-technical users kick off a real coordination (a demo today; ad-hoc
host agents next) from the Mycelium web GUI, with no terminal and no SSH.

**Why this is a host process, not a container.** In the hub-and-spoke
deployment the OpenClaw gateway runs as a *process on the host*, not as a
service in the compose stack. Provisioning an agent has to edit
``~/.openclaw/openclaw.json`` and run ``openclaw gateway restart`` — host-level
operations a container can't perform without mounting the host filesystem and
baking in the CLIs (exactly the coupling we're avoiding). So the executor lives
on the host, next to the gateway, and the containerized backend reaches it over
localhost (gated behind ``MYCELIUM_HUB_RUNNER_URL``).

It is deliberately thin: it reuses the ``mycelium demo`` orchestration in-process
rather than reimplementing it, runs provisioning on a background thread, and
exposes a tiny JSON API the backend proxies:

    GET  /health           liveness
    GET  /scenarios        discoverable demo scenarios
    POST /demos            start a demo; returns {job_id, room}
    GET  /demos/{job_id}   poll provisioning status

If ``MYCELIUM_HUB_TOKEN`` is set, every request must carry
``Authorization: Bearer <token>``.
"""

from __future__ import annotations

import io
import json
import os
import threading
import uuid
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any

import typer
from rich.console import Console

from mycelium.commands import demo

app = typer.Typer(help="Host-side runner for web-triggered coordinations (demos, host agents).")
console = Console()

# Job registry. A hub runs at most one provision at a time (provisioning mutates
# the shared gateway), so this stays small; in-memory is fine — a restart drops
# history, not live agents (those live in the gateway/room).
_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.Lock()
# Serializes gateway-mutating provisions *and* the demo.console swap inside the
# worker, so concurrent jobs can't interleave global-console writes.
_provision_lock = threading.Lock()


def _set_job(job_id: str, **fields: Any) -> None:
    with _jobs_lock:
        if job_id in _jobs:
            _jobs[job_id].update(fields)


def _run_demo_job(
    job_id: str,
    scenario_id: str,
    adapter: str,
    model: str | None,
    room: str,
    auth_from: str | None,
) -> None:
    """Provision a demo on a background thread, recording status on the job.

    Reuses ``demo._resolve_scenario`` / ``demo._provision`` verbatim. Both write
    to ``demo.console`` and raise ``typer.Exit`` on failure, so we redirect that
    console into a buffer (under ``_provision_lock``, which already serializes
    provisions) and surface its tail as the job error.
    """
    buf = io.StringIO()
    original = demo.console
    with _provision_lock:
        demo.console = Console(file=buf, force_terminal=False, width=100)
        try:
            scenario = demo._resolve_scenario(scenario_id)  # noqa: SLF001
            demo._provision(scenario, adapter, model, room, auth_from)  # noqa: SLF001
            _set_job(job_id, status="ready")
        except typer.Exit:
            tail = buf.getvalue().strip().splitlines()
            _set_job(
                job_id,
                status="failed",
                error=tail[-1] if tail else "provisioning failed",
            )
        except Exception as exc:  # noqa: BLE001 — report any failure to the caller
            _set_job(job_id, status="failed", error=str(exc))
        finally:
            demo.console = original
            _set_job(job_id, log=buf.getvalue())


class _Handler(BaseHTTPRequestHandler):
    """Minimal JSON router over the demo orchestration."""

    server_version = "MyceliumHub/1.0"

    def _send(self, code: int, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        token = os.environ.get("MYCELIUM_HUB_TOKEN")
        if not token:
            return True
        return self.headers.get("Authorization") == f"Bearer {token}"

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 — stdlib signature
        """Route stdlib access logs through Rich (quiet, single line)."""
        console.log(f"{self.address_string()} {format % args}")

    def do_GET(self) -> None:  # noqa: N802 — stdlib dispatch name
        """Handle health, scenario discovery, and job status reads."""
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        if self.path == "/health":
            self._send(200, {"status": "ok", "service": "mycelium-hub"})
            return
        if self.path == "/scenarios":
            self._handle_scenarios()
            return
        if self.path.startswith("/demos/"):
            job_id = self.path.rsplit("/", 1)[-1]
            with _jobs_lock:
                job = _jobs.get(job_id)
            if job is None:
                self._send(404, {"error": "no such job"})
                return
            self._send(200, job)
            return
        self._send(404, {"error": "not found"})

    def do_POST(self) -> None:  # noqa: N802 — stdlib dispatch name
        """Start a demo provisioning job."""
        if not self._authorized():
            self._send(401, {"error": "unauthorized"})
            return
        if self.path != "/demos":
            self._send(404, {"error": "not found"})
            return
        self._handle_start_demo()

    def _handle_scenarios(self) -> None:
        try:
            ids = demo._list_scenarios()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001 — network/parse errors → 502
            self._send(502, {"error": f"could not reach agent-personas: {exc}"})
            return
        self._send(
            200,
            {
                "scenarios": [
                    {
                        "id": sid,
                        "topic": demo._pretty_topic(sid),  # noqa: SLF001
                        "default": sid == demo.DEFAULT_SCENARIO,
                    }
                    for sid in ids
                ]
            },
        )

    def _read_json_body(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length") or 0)
        raw = self.rfile.read(length) if length else b""
        return json.loads(raw or b"{}")

    def _handle_start_demo(self) -> None:
        try:
            data = self._read_json_body()
        except ValueError:
            self._send(400, {"error": "invalid JSON body"})
            return

        adapter = str(data.get("adapter") or "openclaw").replace("-", "_")
        if adapter not in demo._KNOWN_ADAPTERS:  # noqa: SLF001
            self._send(400, {"error": f"unknown adapter '{adapter}'"})
            return

        scenario_id = str(data.get("scenario") or demo.DEFAULT_SCENARIO)
        try:
            scenarios = demo._list_scenarios()  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            self._send(502, {"error": f"could not reach agent-personas: {exc}"})
            return
        if scenario_id not in scenarios:
            self._send(400, {"error": f"unknown scenario '{scenario_id}'"})
            return

        # Room name mirrors demo._resolve_scenario so we can return it now and let
        # the GUI deep-link before provisioning finishes. (demo.py: "demo-"+topic.)
        topic = demo._pretty_topic(scenario_id)  # noqa: SLF001
        room = str(data.get("room") or "demo-" + topic.replace(" ", "-"))

        job_id = uuid.uuid4().hex[:12]
        with _jobs_lock:
            _jobs[job_id] = {
                "id": job_id,
                "status": "provisioning",
                "scenario": scenario_id,
                "adapter": adapter,
                "room": room,
                "error": None,
                "log": "",
            }
        threading.Thread(
            target=_run_demo_job,
            args=(job_id, scenario_id, adapter, data.get("model"), room, data.get("auth_from")),
            daemon=True,
        ).start()
        self._send(202, {"job_id": job_id, "room": room, "status": "provisioning"})


@app.command()
def serve(
    host: str = typer.Option("127.0.0.1", "--host", help="Bind address (localhost-only default)."),
    port: int = typer.Option(8765, "--port", "-p", help="Bind port."),
) -> None:
    """Run the host-side runner so the web GUI can trigger coordinations on this box.

    Bind to localhost by default; the backend reaches it over the host network.
    Set MYCELIUM_HUB_TOKEN to require a bearer token on every request.
    """
    httpd = ThreadingHTTPServer((host, port), _Handler)
    secured = "on" if os.environ.get("MYCELIUM_HUB_TOKEN") else "off (set MYCELIUM_HUB_TOKEN)"
    console.print(
        f"[green]mycelium hub[/green] listening on [cyan]http://{host}:{port}[/cyan]  "
        f"[dim]auth: {secured}[/dim]"
    )
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        console.print("\n[dim]hub runner stopped.[/dim]")
    finally:
        httpd.server_close()
