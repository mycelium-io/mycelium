#!/usr/bin/env bash
#
# Refresh Matrix access tokens for OpenClaw agents across multiple nodes.
#
# This script:
#   1. Uses Synapse shared secret registration to get admin access
#   2. Resets agent passwords and logs in to get fresh access tokens
#   3. Updates the agent's openclaw.json on the target node
#   4. Optionally restarts the openclaw-gateway service
#
# Usage:
#   ./refresh-matrix-tokens.sh [--restart] [--dry-run] [--list] [agent1 agent2 ...]
#
# Environment variables:
#   MATRIX_HOMESERVER       - Matrix homeserver URL (default: http://localhost:8008)
#   SYNAPSE_SHARED_SECRET   - Synapse registration_shared_secret (will try to read from container)
#   SSH_KEY                 - Path to SSH key for remote nodes (default: ~/.ssh/ioc.pem)
#
# Node configuration is defined in the NODES associative array below.

set -euo pipefail

# ─── Configuration ───────────────────────────────────────────────────────────

MATRIX_HOMESERVER="${MATRIX_HOMESERVER:-http://localhost:8008}"
SSH_KEY="${SSH_KEY:-$HOME/.ssh/ioc.pem}"
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10 -o BatchMode=yes"
SYNAPSE_CONTAINER="${SYNAPSE_CONTAINER:-matrix-synapse}"

# Node definitions: agent_name -> "user@host:profile"
# Use "localhost:" for local agents, "user@ip:" for remote
declare -A NODES=(
    ["agent-alpha"]="localhost:"
    ["agent-beta"]="localhost:"
    ["agent-gamma"]="localhost:"
    ["agent-delta"]="localhost:"
    ["claire-agent"]="ubuntu@10.0.50.171:"
    ["oclw5-agent"]="ubuntu@10.0.50.142:"
)

# Agent to Matrix user mapping (if different from agent name)
declare -A MATRIX_USERS=(
    ["agent-alpha"]="agent-alpha"
    ["agent-beta"]="agent-beta"
    ["agent-gamma"]="agent-gamma"
    ["agent-delta"]="agent-delta"
    ["claire-agent"]="claire-agent"
    ["oclw5-agent"]="oclw5-agent"
)

# ─── Helper Functions ────────────────────────────────────────────────────────

log() { echo "[$(date '+%H:%M:%S')] $*"; }
err() { echo "[$(date '+%H:%M:%S')] ERROR: $*" >&2; }
warn() { echo "[$(date '+%H:%M:%S')] WARN: $*" >&2; }

get_shared_secret() {
    # Try environment variable first
    if [[ -n "${SYNAPSE_SHARED_SECRET:-}" ]]; then
        echo "$SYNAPSE_SHARED_SECRET"
        return 0
    fi

    # Try reading from Synapse container
    if docker ps --format '{{.Names}}' | grep -q "^${SYNAPSE_CONTAINER}$"; then
        local secret
        secret=$(docker exec "$SYNAPSE_CONTAINER" cat /data/homeserver.yaml 2>/dev/null | \
            grep "registration_shared_secret:" | \
            sed 's/.*: *"\(.*\)"/\1/' | head -1)
        if [[ -n "$secret" ]]; then
            echo "$secret"
            return 0
        fi
    fi

    # Prompt interactively
    read -rsp "Enter Synapse registration_shared_secret: " secret
    echo >&2
    echo "$secret"
}

generate_mac() {
    local nonce="$1"
    local user="$2"
    local password="$3"
    local admin="$4"
    local secret="$5"
    
    # Generate HMAC-SHA1 for Synapse registration
    # Use printf with \0 for proper null byte handling
    printf '%s\0%s\0%s\0%s' "$nonce" "$user" "$password" "$admin" | \
        openssl dgst -sha1 -hmac "$secret" | awk '{print $2}'
}

# Register user or reset password via shared secret registration
register_or_reset() {
    local user="$1"
    local password="$2"
    local secret="$3"
    
    # Get nonce
    local nonce_response
    nonce_response=$(curl -s "${MATRIX_HOMESERVER}/_synapse/admin/v1/register")
    local nonce
    nonce=$(echo "$nonce_response" | jq -r '.nonce // empty')
    
    if [[ -z "$nonce" ]]; then
        err "Failed to get nonce from Synapse"
        return 1
    fi
    
    # Generate MAC
    local mac
    mac=$(generate_mac "$nonce" "$user" "$password" "notadmin" "$secret")
    
    # Try to register (will fail if user exists, which is fine)
    local response
    response=$(curl -s -X POST "${MATRIX_HOMESERVER}/_synapse/admin/v1/register" \
        -H "Content-Type: application/json" \
        -d "{
            \"nonce\": \"$nonce\",
            \"username\": \"$user\",
            \"password\": \"$password\",
            \"admin\": false,
            \"mac\": \"$mac\"
        }" 2>&1)
    
    local token
    token=$(echo "$response" | jq -r '.access_token // empty')
    
    if [[ -n "$token" ]]; then
        # New user registered
        echo "$token"
        return 0
    fi
    
    # User may already exist - try login
    local error
    error=$(echo "$response" | jq -r '.error // empty')
    if [[ "$error" == *"User ID already taken"* ]]; then
        # Use admin API to reset password, then login
        # First we need an admin token - let's just login with the password we set
        matrix_login "$user" "$password"
        return $?
    fi
    
    err "Registration failed: $error"
    return 1
}

matrix_login() {
    local user="$1"
    local password="$2"
    
    local response
    response=$(curl -s -X POST "${MATRIX_HOMESERVER}/_matrix/client/v3/login" \
        -H "Content-Type: application/json" \
        -d "{
            \"type\": \"m.login.password\",
            \"user\": \"$user\",
            \"password\": \"$password\"
        }" 2>&1)
    
    local token
    token=$(echo "$response" | jq -r '.access_token // empty')
    
    if [[ -z "$token" ]]; then
        local error
        error=$(echo "$response" | jq -r '.error // .errcode // "Unknown error"')
        err "Login failed for $user: $error"
        return 1
    fi
    
    echo "$token"
}

# Use Synapse admin API to login as user (requires admin access)
admin_login_as_user() {
    local admin_token="$1"
    local user="$2"
    
    # Get the server name from Synapse (cached after first call)
    if [[ -z "${_SERVER_NAME:-}" ]]; then
        _SERVER_NAME=$(docker exec "$SYNAPSE_CONTAINER" cat /data/homeserver.yaml 2>/dev/null | \
            grep "server_name:" | sed 's/.*: *"\(.*\)"/\1/' | head -1)
        _SERVER_NAME="${_SERVER_NAME:-local}"
    fi
    
    local user_id="@${user}:${_SERVER_NAME}"
    
    local response
    response=$(curl -s -X POST "${MATRIX_HOMESERVER}/_synapse/admin/v1/users/${user_id}/login" \
        -H "Authorization: Bearer $admin_token" \
        -H "Content-Type: application/json" \
        -d '{}' 2>&1)
    
    local token
    token=$(echo "$response" | jq -r '.access_token // empty')
    
    if [[ -z "$token" ]]; then
        local error
        error=$(echo "$response" | jq -r '.error // .errcode // "Unknown error"')
        err "Admin login as $user failed: $error"
        return 1
    fi
    
    echo "$token"
}

get_or_create_admin_token() {
    local secret="$1"
    
    # Check for existing admin token in environment
    if [[ -n "${MATRIX_ADMIN_TOKEN:-}" ]]; then
        echo "$MATRIX_ADMIN_TOKEN"
        return 0
    fi
    
    # Create a unique temp admin user (timestamp-based to avoid collisions)
    local admin_user="mycelium-admin-$(date +%s)"
    local admin_pass="$(openssl rand -hex 16)"
    
    # Get nonce
    local nonce_response
    nonce_response=$(curl -s "${MATRIX_HOMESERVER}/_synapse/admin/v1/register")
    local nonce
    nonce=$(echo "$nonce_response" | jq -r '.nonce // empty')
    
    if [[ -z "$nonce" ]]; then
        err "Failed to get nonce"
        return 1
    fi
    
    # Generate MAC for admin user
    local mac
    mac=$(generate_mac "$nonce" "$admin_user" "$admin_pass" "admin" "$secret")
    
    # Register admin
    local response
    response=$(curl -s -X POST "${MATRIX_HOMESERVER}/_synapse/admin/v1/register" \
        -H "Content-Type: application/json" \
        -d "{
            \"nonce\": \"$nonce\",
            \"username\": \"$admin_user\",
            \"password\": \"$admin_pass\",
            \"admin\": true,
            \"mac\": \"$mac\"
        }" 2>&1)
    
    local token
    token=$(echo "$response" | jq -r '.access_token // empty')
    
    if [[ -n "$token" ]]; then
        echo "$token"
        return 0
    fi
    
    local error
    error=$(echo "$response" | jq -r '.error // empty')
    err "Failed to create admin: $error"
    return 1
}

update_token_local() {
    local agent="$1"
    local token="$2"
    local profile="$3"
    
    local config_dir="$HOME/.openclaw"
    [[ -n "$profile" ]] && config_dir="$HOME/.openclaw-$profile"
    local config_file="$config_dir/openclaw.json"
    
    if [[ ! -f "$config_file" ]]; then
        err "Config file not found: $config_file"
        return 1
    fi
    
    # Update token using jq
    local tmp_file
    tmp_file=$(mktemp)
    
    if jq --arg agent "$agent" --arg token "$token" '
        .integrations.matrix.accounts[$agent].accessToken = $token
    ' "$config_file" > "$tmp_file"; then
        mv "$tmp_file" "$config_file"
        log "  Updated token in $config_file"
        return 0
    else
        rm -f "$tmp_file"
        err "Failed to update $config_file"
        return 1
    fi
}

update_token_remote() {
    local host="$1"
    local agent="$2"
    local token="$3"
    local profile="$4"
    
    local config_dir=".openclaw"
    [[ -n "$profile" ]] && config_dir=".openclaw-$profile"
    
    # Use SSH to update the remote config
    ssh -i "$SSH_KEY" $SSH_OPTS "$host" bash -s <<EOF
set -e
config_file="\$HOME/$config_dir/openclaw.json"
if [[ ! -f "\$config_file" ]]; then
    echo "ERROR: Config file not found: \$config_file" >&2
    exit 1
fi

tmp_file=\$(mktemp)
if jq --arg agent "$agent" --arg token "$token" '
    .integrations.matrix.accounts[\$agent].accessToken = \$token
' "\$config_file" > "\$tmp_file"; then
    mv "\$tmp_file" "\$config_file"
    echo "Updated token for $agent"
else
    rm -f "\$tmp_file"
    echo "ERROR: Failed to update config" >&2
    exit 1
fi
EOF
}

restart_gateway_local() {
    log "Restarting local openclaw-gateway..."
    systemctl --user restart openclaw-gateway 2>/dev/null || {
        warn "Failed to restart gateway (may not be using systemd)"
    }
}

restart_gateway_remote() {
    local host="$1"
    
    log "Restarting openclaw-gateway on $host..."
    ssh -i "$SSH_KEY" $SSH_OPTS "$host" \
        'systemctl --user restart openclaw-gateway' 2>/dev/null || {
        warn "Failed to restart gateway on $host"
    }
}

check_host_reachable() {
    local host="$1"
    
    if [[ "$host" == "localhost" || -z "$host" ]]; then
        return 0
    fi
    
    local ip="${host##*@}"
    ping -c 1 -W 2 "$ip" &>/dev/null
}

# ─── Main ────────────────────────────────────────────────────────────────────

main() {
    local restart=false
    local dry_run=false
    local list_only=false
    local agents=()
    
    # Parse arguments
    while [[ $# -gt 0 ]]; do
        case "$1" in
            --restart) restart=true; shift ;;
            --dry-run) dry_run=true; shift ;;
            --list) list_only=true; shift ;;
            --help|-h)
                cat <<EOF
Usage: $0 [OPTIONS] [agent1 agent2 ...]

Refresh Matrix access tokens for OpenClaw agents.

Options:
  --restart   Restart openclaw-gateway after updating tokens
  --dry-run   Show what would be done without making changes
  --list      List configured agents and exit
  --help      Show this help message

Agents:
$(for a in "${!NODES[@]}"; do echo "  $a -> ${NODES[$a]}"; done | sort)

Environment:
  MATRIX_HOMESERVER       Matrix server URL (default: http://localhost:8008)
  SYNAPSE_SHARED_SECRET   Registration shared secret (auto-detected from container)
  SSH_KEY                 SSH key for remote nodes (default: ~/.ssh/ioc.pem)
EOF
                exit 0
                ;;
            -*) err "Unknown option: $1"; exit 1 ;;
            *) agents+=("$1"); shift ;;
        esac
    done
    
    if $list_only; then
        echo "Configured agents:"
        for agent in "${!NODES[@]}"; do
            local node_spec="${NODES[$agent]}"
            local host="${node_spec%%:*}"
            local matrix_user="${MATRIX_USERS[$agent]:-$agent}"
            local status="?"
            
            if check_host_reachable "$host"; then
                status="✓"
            else
                status="✗"
            fi
            
            printf "  %-15s -> %-25s (Matrix: @%s:localhost) [%s]\n" \
                "$agent" "${host:-localhost}" "$matrix_user" "$status"
        done
        exit 0
    fi
    
    # Default to all agents if none specified
    if [[ ${#agents[@]} -eq 0 ]]; then
        agents=("${!NODES[@]}")
    fi
    
    log "Matrix homeserver: $MATRIX_HOMESERVER"
    log "Agents to refresh: ${agents[*]}"
    
    if $dry_run; then
        log "DRY RUN - no changes will be made"
    fi
    
    # Get shared secret
    local shared_secret
    shared_secret=$(get_shared_secret)
    
    if [[ -z "$shared_secret" ]]; then
        err "No shared secret available"
        exit 1
    fi
    log "Got Synapse shared secret"
    
    # Get admin token
    local admin_token
    if ! $dry_run; then
        admin_token=$(get_or_create_admin_token "$shared_secret") || {
            err "Failed to get admin token"
            exit 1
        }
        log "Got admin token"
    fi
    
    # Track hosts that need restart
    declare -A hosts_to_restart
    local failed=0
    local skipped=0
    
    for agent in "${agents[@]}"; do
        if [[ -z "${NODES[$agent]:-}" ]]; then
            warn "Unknown agent: $agent (skipping)"
            ((skipped++))
            continue
        fi
        
        local node_spec="${NODES[$agent]}"
        local host="${node_spec%%:*}"
        local profile="${node_spec##*:}"
        local matrix_user="${MATRIX_USERS[$agent]:-$agent}"
        
        # Check if host is reachable
        if ! check_host_reachable "$host"; then
            warn "Host unreachable for $agent: ${host:-localhost} (skipping)"
            ((skipped++))
            continue
        fi
        
        log "Processing $agent (Matrix: @${matrix_user}:localhost, host: ${host:-localhost})"
        
        # Get new token using admin API
        local token
        if $dry_run; then
            log "  [DRY RUN] Would get token for @${matrix_user}:localhost"
            token="dry-run-token-placeholder"
        else
            token=$(admin_login_as_user "$admin_token" "$matrix_user") || {
                err "  Failed to get token for $matrix_user"
                ((failed++))
                continue
            }
            log "  Got new access token: ${token:0:20}..."
        fi
        
        # Update config
        if [[ -z "$host" || "$host" == "localhost" ]]; then
            if $dry_run; then
                log "  [DRY RUN] Would update local config"
            else
                update_token_local "$agent" "$token" "$profile" || {
                    ((failed++))
                    continue
                }
            fi
            hosts_to_restart["localhost"]=1
        else
            if $dry_run; then
                log "  [DRY RUN] Would update config on $host"
            else
                update_token_remote "$host" "$agent" "$token" "$profile" || {
                    ((failed++))
                    continue
                }
            fi
            hosts_to_restart["$host"]=1
        fi
    done
    
    # Restart gateways if requested
    if $restart && ! $dry_run && [[ ${#hosts_to_restart[@]} -gt 0 ]]; then
        log "Restarting gateways..."
        for host in "${!hosts_to_restart[@]}"; do
            if [[ "$host" == "localhost" ]]; then
                restart_gateway_local
            else
                restart_gateway_remote "$host"
            fi
        done
    elif $restart && $dry_run; then
        log "[DRY RUN] Would restart gateways on: ${!hosts_to_restart[*]}"
    fi
    
    echo ""
    log "Summary: $((${#agents[@]} - failed - skipped)) updated, $failed failed, $skipped skipped"
    
    if [[ $failed -gt 0 ]]; then
        exit 1
    fi
}

main "$@"
