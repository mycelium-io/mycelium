"""Environment-driven URLs for the Mycelium E2E test suite."""

import os

ROOM_PREFIX = "e2e-test"

BACKEND_URL = os.environ.get("MYCELIUM_BACKEND_URL", "http://localhost:8000/api")
CFN_MGMT_URL = os.environ.get("CFN_MGMT_URL", "http://localhost:9000")
CFN_SVC_URL = os.environ.get("CFN_SVC_URL", "http://localhost:9002")
MATRIX_URL = os.environ.get("MATRIX_URL", "http://localhost:8008")
