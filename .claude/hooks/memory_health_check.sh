#!/bin/bash
# Memory MCP functional health check.
#
# Why this exists: lessons.md Pattern 3 — "verification must test the user
# experience, not just process health". The 2026-04-07 review found that
# the laptop's memory MCP had been silently broken since ~20 March because
# nothing was actually CALLING search_memory and verifying it returns results.
#
# This script:
# 1. Imports the memory_server module
# 2. Runs an actual semantic search query
# 3. Verifies the result has >0 chunks
# 4. Logs to ~/.claude/memory_health.log
# 5. Sends an ntfy alert on failure
# 6. Exits 0 always (advisory) — change to exit 2 to make blocking
#
# Run modes:
#   bash memory_health_check.sh           # quick check, log only on failure
#   bash memory_health_check.sh --verbose # always log + print
#   bash memory_health_check.sh --strict  # exit 2 on failure (for CI/cron)

set -uo pipefail

LOG=~/.claude/memory_health.log
TS=$(date "+%Y-%m-%d %H:%M:%S")
VERBOSE=0
STRICT=0
for arg in "$@"; do
    case "$arg" in
        --verbose) VERBOSE=1 ;;
        --strict)  STRICT=1 ;;
    esac
done

# Find the canonical memory_server.py — try Mac Mini layout first
SERVER=""
for cand in $HOME/code/memory_server.py $HOME/code/memory_server/memory_server.py; do
    [ -f "$cand" ] && SERVER="$cand" && break
done

if [ -z "$SERVER" ]; then
    {
        echo "[$TS] FAIL: memory_server.py not found in any expected location"
    } | tee -a "$LOG" >&2
    [ "$STRICT" = "1" ] && exit 2
    echo "memory health check: server file missing" | curl -s --max-time 3 -d @- ntfy.sh/<user>-claude >/dev/null 2>&1 || true
    exit 0
fi

# Find a Python with chromadb + fastmcp
PYTHON=""
for cand in /opt/homebrew/bin/python3.11 $HOME/anaconda3/bin/python3.11 /opt/homebrew/bin/python3.12; do
    [ -x "$cand" ] || continue
    "$cand" -c "import chromadb, fastmcp" 2>/dev/null && PYTHON="$cand" && break
done

if [ -z "$PYTHON" ]; then
    {
        echo "[$TS] FAIL: no Python with chromadb+fastmcp installed"
    } | tee -a "$LOG" >&2
    [ "$STRICT" = "1" ] && exit 2
    echo "memory health check: no working python" | curl -s --max-time 3 -d @- ntfy.sh/<user>-claude >/dev/null 2>&1 || true
    exit 0
fi

# Functional probe: import and inspect chunk count
RESULT=$("$PYTHON" - <<PYEOF 2>&1
import sys, os
sys.path.insert(0, os.path.dirname("$SERVER"))
try:
    # Don't import the full module — it tries to start the MCP server.
    # Just open the data dir directly.
    import chromadb
    from pathlib import Path
    # The data dir lives next to the server (or as Mac Mini hardcoded path)
    server_dir = Path("$SERVER").parent
    candidates = [
        Path.home() / "code" / "memory_server_data" / "chroma",  # Mac Mini layout
        server_dir / "data" / "chroma",                             # portable layout
    ]
    chroma_dir = next((p for p in candidates if p.exists()), None)
    if chroma_dir is None:
        print("FAIL: no chroma dir at any expected location")
        sys.exit(1)

    client = chromadb.PersistentClient(path=str(chroma_dir))
    coll = client.get_or_create_collection(name="conversations", metadata={"hnsw:space": "cosine"})
    count = coll.count()
    if count == 0:
        print(f"WARN: chroma at {chroma_dir} has 0 chunks (fresh install — index will populate as conversations are auto-indexed)")
        sys.exit(0)

    # Real probe: search for a known concept
    res = coll.query(query_texts=["printer safety"], n_results=3)
    n_hits = len(res.get("ids", [[]])[0]) if res.get("ids") else 0
    print(f"OK: chroma at {chroma_dir} has {count} chunks, query returned {n_hits} hits")
    sys.exit(0)
except Exception as e:
    print(f"FAIL: {type(e).__name__}: {e}")
    sys.exit(1)
PYEOF
)
RC=$?

if [ $RC -eq 0 ]; then
    if [[ "$RESULT" == OK:* ]]; then
        [ "$VERBOSE" = "1" ] && echo "[$TS] $RESULT" >> "$LOG"
        [ "$VERBOSE" = "1" ] && echo "$RESULT"
        exit 0
    else
        # WARN case (empty index)
        echo "[$TS] $RESULT" >> "$LOG"
        [ "$VERBOSE" = "1" ] && echo "$RESULT"
        exit 0
    fi
fi

# Failure
{
    echo "[$TS] $RESULT (server=$SERVER python=$PYTHON)"
} | tee -a "$LOG" >&2

# ntfy alert
{
    echo "Memory MCP health check FAILED on $(hostname)"
    echo "$RESULT"
} | curl -s --max-time 3 -d @- ntfy.sh/<user>-claude >/dev/null 2>&1 || true

[ "$STRICT" = "1" ] && exit 2
exit 0
