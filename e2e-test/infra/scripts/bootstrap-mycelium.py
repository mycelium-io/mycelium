#!/usr/bin/env python3
"""Bootstrap Mycelium backend for E2E tests.

Waits for the backend health check, fetches WORKSPACE_ID from CFN mgmt plane,
and writes configuration to /shared/mycelium-config.json.
"""

import json
import os
import sys
import time
import urllib.error
import urllib.request

BACKEND_URL = os.environ.get("BACKEND_URL", "http://mycelium-backend:8000")
CFN_MGMT_URL = os.environ.get("CFN_MGMT_URL", "http://ioc-cfn-mgmt-plane-svc:9000")
CONFIG_OUTPUT = os.environ.get("CONFIG_OUTPUT", "/shared/mycelium-config.json")


def _get(url, timeout=10):
    try:
        req = urllib.request.Request(url)
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        body = e.read().decode() if e.fp else ""
        try:
            return e.code, json.loads(body)
        except json.JSONDecodeError:
            return e.code, {"error": body}
    except Exception as exc:
        return -1, {"error": str(exc)}


def wait_for_service(name, url, max_wait=120):
    deadline = time.time() + max_wait
    while time.time() < deadline:
        status, _ = _get(url)
        if 200 <= status < 300:
            print(f"{name} is ready")
            return True
        time.sleep(2)
    print(f"ERROR: {name} did not become ready at {url}", file=sys.stderr)
    return False


def get_workspace_id():
    """Fetch the primary workspace ID from CFN mgmt plane."""
    status, data = _get(f"{CFN_MGMT_URL}/api/workspaces")
    if status != 200:
        status, data = _get(f"{CFN_MGMT_URL}/workspaces")
    if status != 200:
        print(f"  Could not list workspaces: {status}", file=sys.stderr)
        return None

    workspaces = data if isinstance(data, list) else data.get("workspaces", data.get("items", []))
    if not workspaces:
        print("  No workspaces found (CFN may need a few seconds to auto-create)")
        for attempt in range(10):
            time.sleep(3)
            status, data = _get(f"{CFN_MGMT_URL}/api/workspaces")
            if status != 200:
                status, data = _get(f"{CFN_MGMT_URL}/workspaces")
            workspaces = data if isinstance(data, list) else data.get("workspaces", data.get("items", []))
            if workspaces:
                break
            print(f"  Retry {attempt + 1}/10...")

    if not workspaces:
        return None

    ws = workspaces[0]
    ws_id = ws.get("id") or ws.get("workspace_id")
    print(f"  Found workspace: {ws_id}")
    return ws_id


def get_mas_id(workspace_id):
    """Fetch the first MAS ID for *workspace_id* from CFN mgmt plane."""
    if not workspace_id:
        return None
    enc = urllib.parse.quote(workspace_id, safe="")
    status, data = _get(f"{CFN_MGMT_URL}/api/workspaces/{enc}/multi-agentic-systems")
    if status != 200:
        print(f"  Could not list MAS: {status}", file=sys.stderr)
        return None
    items = data if isinstance(data, list) else data.get("systems", data.get("items", []))
    if not items:
        print("  No MAS found — creating default MAS")
        try:
            body = json.dumps({"name": "e2e-default"}).encode()
            req = urllib.request.Request(
                f"{CFN_MGMT_URL}/api/workspaces/{enc}/multi-agentic-systems",
                data=body,
                headers={"Content-Type": "application/json"},
                method="POST",
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                created = json.loads(resp.read().decode())
                mas_id = created.get("id") or created.get("mas_id")
                if mas_id:
                    print(f"  Created MAS: {mas_id}")
                    return mas_id
        except urllib.error.HTTPError as exc:
            if exc.code == 409:
                print("  MAS already exists — re-listing")
                return get_mas_id(workspace_id)
            print(f"  Failed to create MAS: {exc}", file=sys.stderr)
        except Exception as exc:
            print(f"  Failed to create MAS: {exc}", file=sys.stderr)
        return None
    mas_id = items[0].get("id") or items[0].get("mas_id")
    print(f"  Found MAS: {mas_id}")
    return mas_id


def main():
    print("Waiting for services...")
    if not wait_for_service("Backend", f"{BACKEND_URL}/health"):
        sys.exit(1)
    if not wait_for_service("CFN Mgmt", f"{CFN_MGMT_URL}/health"):
        print("  WARNING: CFN mgmt not ready, continuing without workspace ID")

    print("\nFetching workspace ID...")
    workspace_id = get_workspace_id()

    print("\nFetching MAS ID...")
    mas_id = get_mas_id(workspace_id)

    print("\nBackend health:")
    status, health = _get(f"{BACKEND_URL}/health")
    print(json.dumps(health, indent=2) if isinstance(health, dict) else f"  status={status}")

    config = {
        "backend_url": BACKEND_URL,
        "cfn_mgmt_url": CFN_MGMT_URL,
        "workspace_id": workspace_id or "",
        "mas_id": mas_id or "",
        "health": health if isinstance(health, dict) else {},
    }

    os.makedirs(os.path.dirname(CONFIG_OUTPUT), exist_ok=True)
    with open(CONFIG_OUTPUT, "w") as f:
        json.dump(config, f, indent=2)
    print(f"\nConfig written to {CONFIG_OUTPUT}")

    if workspace_id:
        print(f"\nWORKSPACE_ID={workspace_id}")
    if mas_id:
        print(f"MAS_ID={mas_id}")

    print("\nBootstrap complete.")


if __name__ == "__main__":
    main()
