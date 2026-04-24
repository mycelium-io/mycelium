#!/bin/bash
# Clean up stale negotiating sessions and remote agent processes
#
# Usage:
#   ./cleanup-sessions.sh                    # Clean all negotiating sessions
#   ./cleanup-sessions.sh --prefix e2e-      # Clean only e2e- prefixed sessions
#   ./cleanup-sessions.sh --dry-run          # Show what would be cleaned
#   ./cleanup-sessions.sh --agents           # Also clean remote agent processes

set -e

BACKEND_URL="${MYCELIUM_API_URL:-http://localhost:8000}"
PREFIX=""
DRY_RUN=false
CLEAN_AGENTS=false
SSH_KEY="${SSH_KEY:-~/.ssh/ioc.pem}"
REMOTE_HOSTS="${REMOTE_HOSTS:-10.0.50.171 10.0.50.142}"  # oclw3 and oclw5

while [[ $# -gt 0 ]]; do
    case $1 in
        --prefix)
            PREFIX="$2"
            shift 2
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        --backend-url)
            BACKEND_URL="$2"
            shift 2
            ;;
        --agents)
            CLEAN_AGENTS=true
            shift
            ;;
        --hosts)
            REMOTE_HOSTS="$2"
            shift 2
            ;;
        -h|--help)
            echo "Usage: $0 [--prefix PREFIX] [--dry-run] [--backend-url URL] [--agents] [--hosts 'IP1 IP2']"
            echo ""
            echo "Options:"
            echo "  --prefix PREFIX    Only clean sessions matching this prefix"
            echo "  --dry-run          Show what would be cleaned without deleting"
            echo "  --backend-url URL  Backend URL (default: http://localhost:8000)"
            echo "  --agents           Also clean remote openclaw-agent processes"
            echo "  --hosts 'IP1 IP2'  Remote hosts to clean (default: oclw3 + oclw5)"
            exit 0
            ;;
        *)
            echo "Unknown option: $1"
            exit 1
            ;;
    esac
done

echo "Fetching rooms from $BACKEND_URL..."

# Get all rooms and filter for negotiating/waiting state
SESSIONS=$(curl -s "$BACKEND_URL/rooms" | jq -r '.[] | select(.coordination_state == "negotiating" or .coordination_state == "waiting") | .name')

if [[ -z "$SESSIONS" ]]; then
    echo "No stale sessions found."
    exit 0
fi

COUNT=0
while IFS= read -r session; do
    # Filter by prefix if specified
    if [[ -n "$PREFIX" && ! "$session" =~ ^$PREFIX ]]; then
        continue
    fi
    
    if [[ "$DRY_RUN" == "true" ]]; then
        echo "[dry-run] Would delete: $session"
    else
        ENCODED=$(python3 -c "import urllib.parse; print(urllib.parse.quote('$session', safe=''))")
        if curl -s -X DELETE "$BACKEND_URL/rooms/$ENCODED" > /dev/null; then
            echo "Deleted: $session"
        else
            echo "Failed to delete: $session"
        fi
    fi
    ((COUNT++)) || true
done <<< "$SESSIONS"

if [[ "$DRY_RUN" == "true" ]]; then
    echo ""
    echo "Would clean up $COUNT session(s). Run without --dry-run to delete."
else
    echo ""
    echo "Cleaned up $COUNT session(s)."
fi

# Clean remote agent processes if requested
if [[ "$CLEAN_AGENTS" == "true" ]]; then
    echo ""
    echo "Cleaning remote openclaw-agent processes..."
    
    for host in $REMOTE_HOSTS; do
        echo "  Checking $host..."
        
        # Get count of running agents
        AGENT_COUNT=$(ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "ubuntu@$host" \
            "pgrep -f openclaw-agent | wc -l" 2>/dev/null || echo "0")
        
        if [[ "$AGENT_COUNT" == "0" ]]; then
            echo "    No agents running on $host"
            continue
        fi
        
        echo "    Found $AGENT_COUNT agent(s), sending SIGTERM..."
        
        if [[ "$DRY_RUN" == "true" ]]; then
            echo "    [dry-run] Would kill $AGENT_COUNT agent(s) on $host"
            continue
        fi
        
        # Phase 1: SIGTERM
        ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "ubuntu@$host" \
            "pkill -TERM -f openclaw-agent" 2>/dev/null || true
        
        # Wait up to 30 seconds for graceful shutdown
        for i in {1..15}; do
            sleep 2
            REMAINING=$(ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "ubuntu@$host" \
                "pgrep -f openclaw-agent | wc -l" 2>/dev/null || echo "0")
            if [[ "$REMAINING" == "0" ]]; then
                echo "    All agents exited gracefully on $host"
                break
            fi
            echo "    $REMAINING agent(s) still running after $((i*2))s..."
        done
        
        # Phase 2: SIGKILL if any remain
        REMAINING=$(ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "ubuntu@$host" \
            "pgrep -f openclaw-agent | wc -l" 2>/dev/null || echo "0")
        if [[ "$REMAINING" != "0" ]]; then
            echo "    Sending SIGKILL to $REMAINING remaining agent(s)..."
            ssh -i "$SSH_KEY" -o ConnectTimeout=5 -o StrictHostKeyChecking=no "ubuntu@$host" \
                "pkill -KILL -f openclaw-agent" 2>/dev/null || true
        fi
    done
    
    echo ""
    echo "Remote agent cleanup complete."
fi
