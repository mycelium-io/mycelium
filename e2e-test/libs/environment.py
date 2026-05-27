"""Environment detection — probes all services and determines skip flags."""

from __future__ import annotations

import json
import logging
import os
import uuid
from typing import Any, Optional

from libs.mycelium_api import MyceliumAPI
from libs.cfn_api import CfnMgmtAPI, CfnNodeSvcAPI
from libs.matrix_client import check_matrix_reachable

log = logging.getLogger(__name__)


class EnvironmentInfo:
    """Collects reachability and configuration state across all services."""

    def __init__(self):
        self.backend_reachable: bool = False
        self.backend_status: Optional[str] = None
        self.backend_health: dict = {}
        self.llm_available: bool = False
        self.cfn_mgmt_reachable: bool = False
        self.cfn_node_svc_reachable: bool = False
        self.cfn_primary_workspace_id: Optional[str] = None
        self.matrix_reachable: bool = False
        self.coordination_blocked_reason: Optional[str] = None

    @property
    def skip_llm_tests(self) -> bool:
        return not self.llm_available

    @property
    def skip_cfn_tests(self) -> bool:
        return not self.cfn_mgmt_reachable

    @property
    def skip_matrix_tests(self) -> bool:
        return not self.matrix_reachable

    def as_dict(self) -> dict[str, Any]:
        return {
            "backend_reachable": self.backend_reachable,
            "backend_status": self.backend_status,
            "llm_available": self.llm_available,
            "cfn_mgmt_reachable": self.cfn_mgmt_reachable,
            "cfn_node_svc_reachable": self.cfn_node_svc_reachable,
            "cfn_primary_workspace_id": self.cfn_primary_workspace_id,
            "matrix_reachable": self.matrix_reachable,
            "coordination_blocked_reason": self.coordination_blocked_reason,
        }


def detect_environment(
    backend: MyceliumAPI,
    cfn_mgmt: CfnMgmtAPI,
    cfn_node_svc: CfnNodeSvcAPI,
    matrix_url: str,
    room_prefix: str = "e2e-test",
) -> EnvironmentInfo:
    """Probe all services and return a populated EnvironmentInfo."""
    env = EnvironmentInfo()

    # Backend health
    health = backend.health_json()
    if health:
        env.backend_reachable = True
        env.backend_status = "ok"
        env.backend_health = health
        llm_status = health.get("llm", {})
        if isinstance(llm_status, dict):
            env.llm_available = llm_status.get("status") != "auth_error"
        elif isinstance(llm_status, str):
            env.llm_available = llm_status != "auth_error"
        else:
            env.llm_available = True
        log.info(
            "Backend: reachable=%s llm=%s",
            env.backend_reachable,
            "available" if env.llm_available else "unavailable",
        )
    else:
        env.backend_status = "unreachable"
        log.warning("Backend unreachable")

    # CFN management plane
    env.cfn_mgmt_reachable = cfn_mgmt.is_reachable()
    if env.cfn_mgmt_reachable:
        env.cfn_primary_workspace_id = cfn_mgmt.get_primary_workspace_id()
        log.info("CFN mgmt: reachable, workspace=%s", env.cfn_primary_workspace_id)
    else:
        log.info("CFN mgmt: unreachable")

    # CFN node service
    env.cfn_node_svc_reachable = cfn_node_svc.is_reachable()
    log.info("CFN node-svc: reachable=%s", env.cfn_node_svc_reachable)

    # Matrix
    env.matrix_reachable = check_matrix_reachable(matrix_url)
    log.info("Matrix: reachable=%s", env.matrix_reachable)

    # Workspace alignment probe
    if env.cfn_mgmt_reachable and env.cfn_primary_workspace_id and env.backend_reachable:
        _probe_workspace_alignment(backend, cfn_mgmt, env, room_prefix)

    return env


def _probe_workspace_alignment(
    backend: MyceliumAPI,
    cfn_mgmt: CfnMgmtAPI,
    env: EnvironmentInfo,
    room_prefix: str,
) -> None:
    """Check if backend's WORKSPACE_ID aligns with CFN mgmt workspaces."""
    probe_name = f"{room_prefix}-wsprobe-{uuid.uuid4().hex[:8]}"
    st, room_data = backend.create_room(probe_name, description="workspace alignment probe")
    if st not in (200, 201):
        return

    mas_id = room_data.get("mas_id") if isinstance(room_data, dict) else None
    backend.delete_room(probe_name)

    if env.cfn_primary_workspace_id and not mas_id:
        env.coordination_blocked_reason = (
            f"Backend has WORKSPACE_ID unset: new rooms return mas_id=null "
            f"while CFN mgmt has workspace {env.cfn_primary_workspace_id}. "
            f"Add WORKSPACE_ID={env.cfn_primary_workspace_id} to ~/.mycelium/.env "
            f"and recreate mycelium-backend."
        )
        log.warning("Workspace alignment check FAILED: %s", env.coordination_blocked_reason)
