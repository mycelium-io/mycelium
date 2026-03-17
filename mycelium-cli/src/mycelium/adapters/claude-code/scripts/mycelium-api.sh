#!/bin/bash
# mycelium-api.sh
# API wrapper for the mycelium backend.
# Usage: ./mycelium-api.sh <METHOD> <endpoint> [json_body]
#
# Examples:
#   ./mycelium-api.sh GET  "rooms/my-room/memory"
#   ./mycelium-api.sh POST "rooms/my-room/memory" '{"key":"val"}'

set -euo pipefail

# ---------------------------------------------------------------------------
# Arguments
# ---------------------------------------------------------------------------
METHOD="${1:?Usage: mycelium-api.sh <METHOD> <endpoint> [json_body]}"
ENDPOINT="${2:?Usage: mycelium-api.sh <METHOD> <endpoint> [json_body]}"
BODY="${3:-}"

# ---------------------------------------------------------------------------
# Config resolution: env vars > ~/.mycelium/config.toml > defaults
# ---------------------------------------------------------------------------
CONFIG_FILE="${HOME}/.mycelium/config.toml"

read_toml_value() {
    local key="$1"
    if [[ -f "$CONFIG_FILE" ]]; then
        sed -n "s/^[[:space:]]*${key}[[:space:]]*=[[:space:]]*\"\?\([^\"]*\)\"\?[[:space:]]*$/\1/p" "$CONFIG_FILE" | head -1
    fi
}

MYCELIUM_API_URL="${MYCELIUM_API_URL:-$(read_toml_value "api_url")}"
MYCELIUM_API_URL="${MYCELIUM_API_URL:-http://localhost:8000}"

# Strip trailing slash
MYCELIUM_API_URL="${MYCELIUM_API_URL%/}"

# Strip leading slash from endpoint
ENDPOINT="${ENDPOINT#/}"

URL="${MYCELIUM_API_URL}/${ENDPOINT}"

# ---------------------------------------------------------------------------
# Build curl command
# ---------------------------------------------------------------------------
CURL_ARGS=(
    -s
    -X "$METHOD"
    -H "Content-Type: application/json"
    -H "Accept: application/json"
    --max-time 10
)

# Include auth token if available
if [[ -n "${MYCELIUM_API_TOKEN:-}" ]]; then
    CURL_ARGS+=(-H "Authorization: Bearer ${MYCELIUM_API_TOKEN}")
fi

# Include body for methods that support it
if [[ -n "$BODY" ]] && [[ "$METHOD" =~ ^(POST|PUT|PATCH)$ ]]; then
    CURL_ARGS+=(-d "$BODY")
fi

# ---------------------------------------------------------------------------
# Execute and return response
# ---------------------------------------------------------------------------
curl "${CURL_ARGS[@]}" "$URL"
