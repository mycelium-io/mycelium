"""HTTP client for CFN management plane and node service."""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

log = logging.getLogger(__name__)


class CfnMgmtAPI:
    """Client for the CFN management plane (ioc-cfn-mgmt-plane-svc)."""

    def __init__(self, base_url: str = "http://localhost:9000"):
        self.base_url = base_url.rstrip("/")

    def _get(self, path: str, timeout: int = 10) -> tuple[int, str]:
        url = f"{self.base_url}{path}"
        try:
            with urllib.request.urlopen(url, timeout=timeout) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode() if e.fp else ""
        except Exception as e:
            return -1, str(e)

    def _get_json(self, path: str, timeout: int = 10) -> tuple[int, Any]:
        status, body = self._get(path, timeout)
        if status < 0:
            return status, None
        try:
            return status, json.loads(body)
        except json.JSONDecodeError:
            return status, body

    def health(self) -> tuple[int, str]:
        return self._get("/health")

    def is_reachable(self) -> bool:
        status, _ = self.health()
        return status == 200

    def list_workspaces(self) -> tuple[int, Any]:
        return self._get_json("/api/workspaces")

    def list_memory_providers(self) -> tuple[int, Any]:
        return self._get_json("/api/memory-providers")

    def list_mas(self, workspace_id: str) -> tuple[int, Any]:
        enc = urllib.parse.quote(workspace_id, safe="")
        return self._get_json(f"/api/workspaces/{enc}/multi-agentic-systems")

    def list_cfn_nodes(self) -> tuple[int, Any]:
        return self._get_json("/api/cognition-fabric-nodes")

    def get_primary_workspace_id(self) -> Optional[str]:
        status, data = self.list_workspaces()
        if status != 200 or not data:
            return None
        if isinstance(data, list):
            workspaces = data
        elif isinstance(data, dict):
            workspaces = data.get("workspaces", data.get("items", []))
        else:
            return None
        if not workspaces:
            return None
        return workspaces[0].get("id") or workspaces[0].get("workspace_id")

    def get_primary_mas_id(self, workspace_id: str) -> Optional[str]:
        """Return the first MAS ID for *workspace_id*, or ``None``.

        CFN mgmt returns ``{"systems": [{"id": "..."}]}`` for the MAS list.
        """
        status, data = self.list_mas(workspace_id)
        if status != 200 or not data:
            return None
        if isinstance(data, list):
            items = data
        elif isinstance(data, dict):
            items = data.get("systems", data.get("items", []))
        else:
            return None
        if not items:
            return None
        return items[0].get("id") or items[0].get("mas_id")

    def create_mas(self, workspace_id: str, name: str) -> Optional[str]:
        """Create a MAS in the given workspace. Returns the new MAS ID or ``None``.

        On 409 Conflict (MAS already exists), falls back to listing and
        returning the existing one.
        """
        enc = urllib.parse.quote(workspace_id, safe="")
        url = f"{self.base_url}/api/workspaces/{enc}/multi-agentic-systems"
        try:
            body = json.dumps({"name": name}).encode()
            req = urllib.request.Request(url, data=body, headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode())
                return data.get("id") or data.get("mas_id")
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                log.info("MAS '%s' already exists — fetching existing ID", name)
                return self.get_primary_mas_id(workspace_id)
            log.warning("Failed to create MAS '%s': %s", name, exc)
            return None
        except Exception as exc:
            log.warning("Failed to create MAS '%s': %s", name, exc)
            return None


class CfnNodeSvcAPI:
    """Client for the CFN node service (ioc-cognition-fabric-node-svc)."""

    def __init__(self, base_url: str = "http://localhost:9002"):
        self.base_url = base_url.rstrip("/")

    def _request(self, method: str, path: str, data: dict | None = None, timeout: int = 30) -> tuple[int, str]:
        url = f"{self.base_url}{path}"
        try:
            body = json.dumps(data).encode() if data else None
            headers = {"Content-Type": "application/json"} if data else {}
            req = urllib.request.Request(url, data=body, headers=headers, method=method)
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.status, resp.read().decode()
        except urllib.error.HTTPError as e:
            return e.code, e.read().decode() if e.fp else ""
        except Exception as e:
            return -1, str(e)

    def health(self) -> tuple[int, str]:
        status, body = self._request("GET", "/api/internal/diagnostics/health")
        if status < 0:
            status, body = self._request("GET", "/health")
        return status, body

    def is_reachable(self) -> bool:
        status, _ = self.health()
        return status == 200

    def start_negotiation(self, workspace_id: str, mas_id: str, data: dict) -> tuple[int, Any]:
        path = f"/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/semantic-negotiation/start"
        status, body = self._request("POST", path, data=data, timeout=120)
        try:
            return status, json.loads(body) if status >= 0 else None
        except json.JSONDecodeError:
            return status, body

    def query_shared_memories(self, workspace_id: str, mas_id: str, query: dict) -> tuple[int, Any]:
        path = f"/api/workspaces/{workspace_id}/multi-agentic-systems/{mas_id}/shared-memories/query"
        status, body = self._request("POST", path, data=query, timeout=30)
        try:
            return status, json.loads(body) if status >= 0 else None
        except json.JSONDecodeError:
            return status, body
