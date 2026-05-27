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
        workspaces = data.get("workspaces", []) if isinstance(data, dict) else []
        return workspaces[0].get("id") if workspaces else None


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
