#!/bin/bash
# mycelium-stop.sh
# Claude Code hook: fires when Claude finishes responding.
# Syncs room files from the backend. With ETag caching this is a cheap
# no-op (304) when nothing has changed on the remote.

mycelium sync --no-reindex 2>/dev/null &
