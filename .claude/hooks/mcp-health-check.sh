#!/bin/bash
# SessionStart hook: verify memory MCP server dependencies are available
# Returns a warning if something is missing; always exits 0 (informational only)

MCP_SCRIPT="$HOME/code/memory_server/memory_server.py"
PYTHON="/opt/homebrew/bin/python3.11"

# Check script exists
if [ ! -f "$MCP_SCRIPT" ]; then
    echo "WARNING: Memory MCP server script not found at $MCP_SCRIPT"
    exit 0
fi

# Find working python — check configured path first, then fall back
if ! command -v "$PYTHON" &>/dev/null; then
    PYTHON=$(command -v python3.11 2>/dev/null || command -v python3 2>/dev/null || true)
    if [ -z "$PYTHON" ]; then
        echo "WARNING: No python3 found — memory MCP server cannot start"
        exit 0
    fi
fi

# Check required dependencies
"$PYTHON" -c "
import sys
missing = []
for mod in ['chromadb', 'sqlite3']:
    try:
        __import__(mod)
    except ImportError:
        missing.append(mod)
if missing:
    print('WARNING: Memory MCP server missing dependencies: ' + ', '.join(missing))
" 2>/dev/null

exit 0
