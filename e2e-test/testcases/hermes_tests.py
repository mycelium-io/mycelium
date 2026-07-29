"""Hermes adapter topology constants.

Provides SSH topology constants used by ``suites/_hermes_prereq.py`` and
lab provisioning scripts.  The loop-suppression testcase (formerly Test 89)
was removed — it is now covered by the unit test
``mycelium-cli/tests/test_hermes_adapter.py``.
"""

from __future__ import annotations

import os

# ── topology constants ────────────────────────────────────────────────────────

OCLW4_IP = os.environ.get("OCLW4_IP", "10.0.50.125")
OCLW3_IP = os.environ.get("OCLW3_IP", "10.0.50.171")
OCLW5_IP = os.environ.get("OCLW5_IP", "10.0.50.142")

HUB_HOST = os.environ.get("HERMES_HUB_HOST", OCLW4_IP)
HERMES_SPOKE1 = os.environ.get("HERMES_SPOKE1_HOST", OCLW3_IP)
HERMES_SPOKE2 = os.environ.get("HERMES_SPOKE2_HOST", OCLW5_IP)

SSH_KEY = os.environ.get("SSH_KEY_PATH", "~/.ssh/ioc.pem")
SSH_USER = os.environ.get("SSH_USER", "ubuntu")
SSH_CONNECT_TIMEOUT = int(os.environ.get("SSH_CONNECT_TIMEOUT", "5"))
