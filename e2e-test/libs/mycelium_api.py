"""HTTP client for the Mycelium backend REST API."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

log = logging.getLogger(__name__)


class MyceliumAPI:
    """Thin wrapper around the Mycelium backend HTTP API.

    Uses only stdlib (urllib) so the library has zero extra dependencies
    for basic HTTP — matching the original harness's philosophy.
    """

    def __init__(self, base_url: str = "http://localhost:8000", api_path: str = "/api"):
        self.base_url = base_url.rstrip("/")
        self.api_url = f"{self.base_url}{api_path}"

    # ── Generic HTTP ──────────────────────────────────────────────────────

    def _request(
        self,
        method: str,
        url: str,
        data: dict | None = None,
        timeout: int = 10,
    ) -> tuple[int, str]:
        start = time.time()
        try:
            body_bytes = json.dumps(data).encode() if data else None
            headers = {"Content-Type": "application/json"} if data else {}
            req = urllib.request.Request(url, data=body_bytes, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                resp_body = resp.read().decode()
                elapsed = int((time.time() - start) * 1000)
                log.debug("HTTP %s %s -> %s (%dms)", method, url, resp.status, elapsed)
                return resp.status, resp_body
        except urllib.error.HTTPError as e:
            resp_body = e.read().decode() if e.fp else ""
            elapsed = int((time.time() - start) * 1000)
            log.debug("HTTP %s %s -> %s (%dms)", method, url, e.code, elapsed)
            return e.code, resp_body
        except Exception as e:
            elapsed = int((time.time() - start) * 1000)
            log.warning("HTTP %s %s failed (%dms): %s", method, url, elapsed, e)
            return -1, str(e)

    def get(self, path: str, timeout: int = 10) -> tuple[int, str]:
        return self._request("GET", f"{self.api_url}{path}", timeout=timeout)

    def post(self, path: str, data: dict | None = None, timeout: int = 10) -> tuple[int, str]:
        return self._request("POST", f"{self.api_url}{path}", data=data, timeout=timeout)

    def delete(self, path: str, timeout: int = 10) -> tuple[int, str]:
        return self._request("DELETE", f"{self.api_url}{path}", timeout=timeout)

    def get_json(self, path: str, timeout: int = 10) -> tuple[int, Any]:
        status, body = self.get(path, timeout=timeout)
        if status < 0:
            return status, None
        try:
            return status, json.loads(body)
        except json.JSONDecodeError:
            return status, body

    def post_json(self, path: str, data: dict | None = None, timeout: int = 10) -> tuple[int, Any]:
        status, body = self.post(path, data=data, timeout=timeout)
        if status < 0:
            return status, None
        try:
            return status, json.loads(body)
        except json.JSONDecodeError:
            return status, body

    # ── Health ────────────────────────────────────────────────────────────

    def health(self) -> tuple[int, dict]:
        return self._request("GET", f"{self.base_url}/health")

    def health_json(self) -> dict | None:
        status, body = self.health()
        if status != 200:
            return None
        try:
            return json.loads(body)
        except json.JSONDecodeError:
            return None

    # ── Rooms ─────────────────────────────────────────────────────────────

    def _enc(self, name: str) -> str:
        return urllib.parse.quote(name, safe="")

    def create_room(self, name: str, description: str = "") -> tuple[int, Any]:
        return self.post_json("/rooms", {"name": name, "description": description})

    def get_room(self, name: str) -> tuple[int, Any]:
        return self.get_json(f"/rooms/{self._enc(name)}")

    def list_rooms(self) -> tuple[int, Any]:
        return self.get_json("/rooms")

    def delete_room(self, name: str) -> tuple[int, str]:
        return self.delete(f"/rooms/{self._enc(name)}")

    def get_room_messages(self, name: str, limit: int = 50) -> tuple[int, list]:
        status, data = self.get_json(f"/rooms/{self._enc(name)}/messages?limit={limit}", timeout=15)
        if status != 200:
            return status, []
        return status, data.get("messages", []) if isinstance(data, dict) else []

    def synthesize(self, name: str) -> tuple[int, Any]:
        return self.post_json(f"/rooms/{self._enc(name)}/synthesize", timeout=120)

    def catchup(self, name: str) -> tuple[int, Any]:
        return self.get_json(f"/rooms/{self._enc(name)}/catchup", timeout=30)

    def reindex(self, name: str) -> tuple[int, Any]:
        return self.post_json(f"/rooms/{self._enc(name)}/reindex", timeout=60)

    # ── Memory ────────────────────────────────────────────────────────────

    def get_memory(self, room: str, key: str) -> tuple[int, Any]:
        return self.get_json(f"/rooms/{self._enc(room)}/memory/{self._enc(key)}")

    def list_memory(self, room: str) -> tuple[int, Any]:
        return self.get_json(f"/rooms/{self._enc(room)}/memory")

    def search_memory(self, room: str, query: str) -> tuple[int, Any]:
        return self.post_json(f"/rooms/{self._enc(room)}/memory/search", {"query": query})

    # ── Sessions ──────────────────────────────────────────────────────────

    def spawn_session(self, room: str, data: dict | None = None) -> tuple[int, Any]:
        return self.post_json(f"/rooms/{self._enc(room)}/sessions/spawn", data=data, timeout=30)

    def list_sessions(self, room: str) -> tuple[int, Any]:
        return self.get_json(f"/rooms/{self._enc(room)}/sessions")

    def get_coordination_sessions(
        self, parent_room: str | None = None, limit: int = 10
    ) -> tuple[int, Any]:
        params = f"?limit={limit}"
        if parent_room:
            params += f"&parent_room={urllib.parse.quote(parent_room, safe='')}"
        return self.get_json(f"/coordination-sessions{params}")

    def get_coordination_session(self, session_id: str) -> tuple[int, Any]:
        return self.get_json(f"/coordination-sessions/{self._enc(session_id)}")

    def get_coordination_messages(self, session_id: str) -> tuple[int, Any]:
        return self.get_json(f"/coordination-sessions/{self._enc(session_id)}/messages")

    # ── Observability ─────────────────────────────────────────────────────

    def observability(self) -> tuple[int, Any]:
        return self.get_json("/observability")

    # ── Knowledge / CFN proxy ─────────────────────────────────────────────

    def ingest_knowledge(self, data: dict, timeout: int = 180) -> tuple[int, Any]:
        return self.post_json("/knowledge/ingest", data, timeout=timeout)

    def query_knowledge(
        self, query: str, mas_id: str | None = None, timeout: int = 180,
    ) -> tuple[int, Any]:
        payload: dict[str, Any] = {"intent": query}
        if mas_id:
            payload["mas_id"] = mas_id
        return self.post_json("/cfn/knowledge/query", payload, timeout=timeout)

    def list_knowledge(self, mas_id: str | None = None) -> tuple[int, Any]:
        qs = f"?mas_id={mas_id}" if mas_id else ""
        return self.get_json(f"/cfn/knowledge/list{qs}")

    # ── Round Traces ──────────────────────────────────────────────────────

    def get_round_traces(self) -> tuple[int, Any]:
        return self.get_json("/internal/coordination/round-traces")

    def delete_round_traces(self) -> tuple[int, str]:
        return self.delete("/internal/coordination/round-traces")

    # ── Coordination helpers ──────────────────────────────────────────────

    def find_session_room(self, parent_namespace: str) -> Optional[str]:
        status, data = self.get_coordination_sessions(parent_room=parent_namespace, limit=1)
        if status != 200 or not data:
            return None
        sessions = data if isinstance(data, list) else data.get("sessions", [])
        for s in sessions:
            if s.get("status") in ("active", "negotiating", "waiting"):
                return s.get("display_name") or s.get("session_room")
        return None

    def wait_for_consensus(
        self,
        room_name: str,
        timeout: int = 600,
        poll_interval: int = 5,
    ) -> dict | None:
        """Poll room coordination state until consensus or timeout."""
        deadline = time.time() + timeout
        while time.time() < deadline:
            status, data = self.get_room(room_name)
            if status == 200 and isinstance(data, dict):
                state = data.get("coordination_state")
                if state == "complete":
                    return data
                if state in ("failed", "aborted"):
                    log.warning("Coordination ended with state=%s for %s", state, room_name)
                    return data
            time.sleep(poll_interval)
        log.warning("Consensus timeout after %ds for %s", timeout, room_name)
        return None

    def cleanup_rooms(self, prefix: str, max_age_minutes: int = 0, exclude: set[str] | None = None) -> int:
        """Delete rooms matching prefix. Returns count of deleted rooms.

        When *max_age_minutes* > 0, only rooms whose ``created_at``
        timestamp is older than that threshold are deleted — this avoids
        interfering with concurrent test runs.
        Rooms whose name is in *exclude* are skipped (protects owned rooms).
        """
        status, data = self.list_rooms()
        if status != 200:
            return 0
        rooms = data if isinstance(data, list) else data.get("rooms", []) if isinstance(data, dict) else []
        skip = exclude or set()
        deleted = 0

        if max_age_minutes > 0:
            from datetime import datetime, timezone
            cutoff_seconds = max_age_minutes * 60
            now = datetime.now(timezone.utc)

        for room in rooms:
            name = room.get("name", "")
            if not name.startswith(prefix) or name in skip:
                continue

            if max_age_minutes > 0:
                created_at = room.get("created_at")
                if created_at:
                    try:
                        created = datetime.fromisoformat(
                            created_at.replace("Z", "+00:00")
                        )
                        if (now - created).total_seconds() < cutoff_seconds:
                            continue
                    except (ValueError, TypeError):
                        pass

            st, _ = self.delete_room(name)
            if 200 <= st < 300:
                deleted += 1
        return deleted
